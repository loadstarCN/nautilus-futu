"""Futu live execution client for NautilusTrader."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.core.datetime import unix_nanos_to_dt
from nautilus_trader.execution.reports import (
    FillReport,
    OrderStatusReport,
    PositionStatusReport,
)
from nautilus_trader.live.execution_client import LiveExecutionClient
from nautilus_trader.model.enums import (
    AccountType,
    ContingencyType,
    LiquiditySide,
    OmsType,
    OrderSide,
    OrderStatus,
)
from nautilus_trader.model.identifiers import (
    AccountId,
    ClientId,
    ClientOrderId,
    InstrumentId,
    TradeId,
    VenueOrderId,
)
from nautilus_trader.model.objects import AccountBalance, Currency, MarginBalance, Money
from nautilus_trader.model.orders import Order

from nautilus_futu.common import (
    futu_security_to_instrument_id,
    instrument_id_to_futu_security,
    log_futu_notify,
)
from nautilus_futu.config import FutuExecClientConfig
from nautilus_futu.connection import FutuConnectionManager
from nautilus_futu.constants import (
    FUTU_ACC_TYPE_CASH,
    FUTU_ACC_TYPE_MARGIN,
    FUTU_CURRENCY_TO_STR,
    FUTU_FILL_STATUS_CANCELLED,
    FUTU_MODIFY_ORDER_OP_CANCEL,
    FUTU_MODIFY_ORDER_OP_NORMAL,
    FUTU_ORDER_STATUS_ACTIVE,
    FUTU_PROTO_NOTIFY,
    FUTU_PROTO_TRD_FILL,
    FUTU_PROTO_TRD_ORDER,
    FUTU_TRD_MARKET_CN,
    FUTU_TRD_MARKET_HKCC,
    FUTU_TRD_MARKET_TO_CURRENCY,
    FUTU_TRD_MARKET_TO_TZ,
    FUTU_VENUE,
    VENUE_TO_FUTU_TRD_MARKET,
    VENUE_TO_FUTU_TRD_SEC_MARKET,
)
from nautilus_futu.parsing.instruments import parse_futu_instrument
from nautilus_futu.parsing.market_data import make_price, make_qty, seconds_to_ns
from nautilus_futu.parsing.orders import (
    build_futu_order_params,
    client_order_id_from_remark,
    futu_order_status_to_nautilus,
    futu_trd_side_to_nautilus,
    parse_futu_fill_to_report,
    parse_futu_order_to_report,
    parse_futu_position_to_report,
    qot_market_to_currency,
    sec_market_to_qot_market,
)

_EXEC_PUSH_PROTOS = [FUTU_PROTO_TRD_ORDER, FUTU_PROTO_TRD_FILL]

# Debounce window for account refreshes triggered by order/fill pushes
_ACCOUNT_REFRESH_DEBOUNCE_SECS = 1.0

# Remember this many recent fill IDs to drop duplicate fill pushes
_SEEN_FILLS_MAX = 10_000

# Remember this many recently accepted orders so OrderAccepted is emitted once
# even while earlier events are still queued in the execution engine
_ACCEPTED_MAX = 10_000

# Outcomes of a place_order attempt
_PLACED = "placed"
_REJECTED = "rejected"
_UNKNOWN = "unknown"  # the request may have reached OpenD (timeout, lost link)

# Error texts of failures that happen after the request was sent: OpenD may
# have accepted the order, so it must not be reported as rejected.
_AMBIGUOUS_ERRORS = ("timed out", "disconnected", "receive error", "decode error", "decryption error")
# Error texts that prove the order was not placed
_DEFINITIVE_ERRORS = ("not connected", "server error")

# After an unclear placement, look the order up in OpenD's order list after
# these delays (seconds); it counts as never placed once it is missing from
# that many successful lookups.
_RESOLVE_DELAYS = (1.0, 2.0, 4.0, 8.0, 15.0, 30.0, 60.0)
_RESOLVE_NOT_FOUND_LIMIT = 3

# Fill pushes for orders not identified yet (their order push or place_order
# reply has not arrived) are kept for replay, up to this many orders
_UNMATCHED_FILLS_MAX = 1_000

# A cancel refused this soon after an earlier cancel of the same order went
# through is a duplicate (e.g. cancel-all plus the OCO manager): no rejection
_DUPLICATE_CANCEL_WINDOW_NS = 30 * 1_000_000_000


def is_ambiguous_order_error(error: BaseException) -> bool:
    """Whether a ``place_order`` failure leaves the order's fate unknown."""
    text = str(error).lower()
    if any(marker in text for marker in _DEFINITIVE_ERRORS):
        return False  # nothing was sent, or OpenD answered with a refusal
    return isinstance(error, ConnectionError | TimeoutError) or any(marker in text for marker in _AMBIGUOUS_ERRORS)

# Backwards-compatible aliases
_TRD_MARKET_CURRENCY = FUTU_TRD_MARKET_TO_CURRENCY

_FUTU_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


# ---------------------------------------------------------------------------
# History query window (module-level so it is unit-testable without a client)
# ---------------------------------------------------------------------------


def history_query_range(
    start: datetime | None,
    end: datetime | None,
    now_ns: int,
    trd_market: int,
) -> tuple[str, str] | None:
    """Bounds for a history order/fill query covering ``[start, end]``.

    Today's orders and fills come from the (cheaper) today-lists, so history is
    only needed when ``start`` reaches before the current trading day in the
    market's local time.  Returns ``None`` otherwise, or the
    ``(begin_time, end_time)`` strings in market local time that OpenD expects.
    """
    if start is None:
        return None
    tz = ZoneInfo(FUTU_TRD_MARKET_TO_TZ.get(trd_market, "Asia/Hong_Kong"))
    now_local = datetime.fromtimestamp(now_ns / 1_000_000_000, tz)
    start_local = _as_utc(start).astimezone(tz)
    day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    if start_local >= day_start:
        return None
    end_local = _as_utc(end).astimezone(tz) if end is not None else now_local
    return start_local.strftime(_FUTU_TIME_FORMAT), end_local.strftime(_FUTU_TIME_FORMAT)


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Funds parsing (module-level so it is unit-testable without a client)
# ---------------------------------------------------------------------------


def parse_funds_to_balance(funds: dict, currency: Currency) -> AccountBalance:
    """Parse a Futu ``get_funds`` response into a single-currency ``AccountBalance``.

    ``total`` is the *cash* balance (not ``total_assets``, which includes the
    market value of positions and would let the risk engine over-buy),
    ``locked`` is ``frozen_cash`` (reserved by open orders) and
    ``free = total - locked``.
    """
    cash = float(funds.get("cash") or 0.0)
    frozen = float(funds.get("frozen_cash") or 0.0)
    free = cash - frozen
    return AccountBalance(
        total=Money(cash, currency),
        locked=Money(frozen, currency),
        free=Money(free, currency),
    )


def parse_funds_to_balances(funds: dict, default_currency: Currency) -> list[AccountBalance]:
    """Parse ``get_funds`` into per-currency balances.

    Unified/futures accounts report a ``cash_info_list`` with one entry per
    currency; plain accounts only carry the aggregate ``cash``/``frozen_cash``
    in the account currency.
    """
    balances: list[AccountBalance] = []
    seen: set[str] = set()
    for info in funds.get("cash_info_list") or []:
        code = FUTU_CURRENCY_TO_STR.get(info.get("currency"))
        if code is None or code in seen:
            continue
        cash = float(info.get("cash") or 0.0)
        available = info.get("available_balance")
        if available is None:
            available = cash
        available = float(available)
        locked = max(0.0, cash - available) if available <= cash else 0.0
        currency = Currency.from_str(code)
        balances.append(
            AccountBalance(
                total=Money(cash, currency),
                locked=Money(locked, currency),
                free=Money(cash - locked, currency),
            )
        )
        seen.add(code)

    if not balances:
        code = FUTU_CURRENCY_TO_STR.get(int(funds.get("currency") or 0)) or default_currency.code
        balances.append(parse_funds_to_balance(funds, Currency.from_str(code)))
    return balances


def parse_funds_to_margins(funds: dict, currency: Currency) -> list[MarginBalance]:
    """Margin requirements for margin accounts (empty when OpenD reports none)."""
    initial = funds.get("initial_margin")
    maintenance = funds.get("maintenance_margin")
    if initial is None and maintenance is None:
        return []
    return [
        MarginBalance(
            initial=Money(float(initial or 0.0), currency),
            maintenance=Money(float(maintenance or 0.0), currency),
        )
    ]


class FutuLiveExecutionClient(LiveExecutionClient):
    """Provides an execution client for Futu OpenD.

    Parameters
    ----------
    loop : asyncio.AbstractEventLoop
        The event loop for the client.
    client : Any
        The Futu Rust client instance.
    msgbus : MessageBus
        The message bus for the client.
    cache : Cache
        The cache for the client.
    clock : LiveClock
        The clock for the client.
    instrument_provider : InstrumentProvider
        The instrument provider.
    config : FutuExecClientConfig
        The execution client configuration.
    connection : FutuConnectionManager, optional
        Shared connection manager (created from ``config`` when omitted).
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        client: Any,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
        instrument_provider: InstrumentProvider,
        config: FutuExecClientConfig,
        connect_lock: asyncio.Lock | None = None,
        connection: FutuConnectionManager | None = None,
    ) -> None:
        account_type = AccountType.MARGIN if str(config.account_type).upper() == "MARGIN" else AccountType.CASH
        super().__init__(
            loop=loop,
            client_id=ClientId("FUTU"),
            venue=FUTU_VENUE,
            oms_type=OmsType.NETTING,
            instrument_provider=instrument_provider,
            account_type=account_type,
            base_currency=None,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            config=config,
        )
        self._client = client
        self._config = config
        self._conn = connection or FutuConnectionManager(
            client=client,
            host=config.host,
            port=config.port,
            client_id=config.client_id,
            client_ver=config.client_ver,
            rsa_key_path=config.rsa_key_path,
            request_timeout=config.request_timeout,
        )
        self._connect_lock = connect_lock or asyncio.Lock()  # backwards compat
        self._acc_id = config.acc_id
        self._trd_env = config.trd_env
        self._trd_market = config.trd_market
        self._trd_market_auth_list: list[int] = [config.trd_market]

        self._push_task: asyncio.Task | None = None
        self._account_refresh_task: asyncio.Task | None = None
        self._push_channel_id: int | None = None
        self._restored_generation: int = -1
        self._use_async_push = hasattr(client, "poll_push_async")
        self._refresh_scheduled = False
        self._seen_fill_ids: OrderedDict[str, None] = OrderedDict()
        # Orders whose placement has not completed (queued list legs or a
        # place_order request in flight), orders whose place_order outcome is
        # unknown (timeout), and cancel/modify requests that arrived before
        # their venue order id was known (modifies merged field by field).
        self._unplaced: set[ClientOrderId] = set()
        self._uncertain: set[ClientOrderId] = set()
        self._deferred_cancels: set[ClientOrderId] = set()
        self._deferred_modifies: dict[ClientOrderId, dict[str, Any]] = {}
        # Values an unclearly placed order was sent with (a modify applied
        # before placement), reported once OpenD reveals the order
        self._placed_values: dict[ClientOrderId, dict[str, Any]] = {}
        self._accepted_ids: OrderedDict[ClientOrderId, None] = OrderedDict()
        # Accepted locally only to leave PENDING_UPDATE/PENDING_CANCEL after a
        # refused modify/cancel, before the venue acknowledged the order
        self._provisional_accepts: set[ClientOrderId] = set()
        self._cancel_sent: OrderedDict[ClientOrderId, int] = OrderedDict()
        self._unmatched_fills: OrderedDict[str, list[dict]] = OrderedDict()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def account_id_str(self) -> AccountId:
        return AccountId(f"FUTU-{self._acc_id}")

    def _trd_market_for(self, instrument_id: InstrumentId) -> int:
        """Trading market to route an instrument's orders through."""
        market = VENUE_TO_FUTU_TRD_MARKET.get(instrument_id.venue, self._trd_market)
        if market in self._trd_market_auth_list:
            return market
        if market == FUTU_TRD_MARKET_CN and FUTU_TRD_MARKET_HKCC in self._trd_market_auth_list:
            return FUTU_TRD_MARKET_HKCC  # A-shares via Stock Connect
        return self._trd_market

    def _instrument_for(self, instrument_id: InstrumentId):
        return self._cache.instrument(instrument_id)

    def _ts_or_now(self, seconds: float | None) -> int:
        return seconds_to_ns(seconds, self._clock.timestamp_ns())

    def _ensure_accepted(
        self,
        order: Order,
        venue_order_id: VenueOrderId,
        ts_event: int,
        provisional: bool = False,
    ) -> None:
        """Emit OrderAccepted once for an order the venue acknowledged.

        Also covers orders the strategy moved to PENDING_UPDATE/PENDING_CANCEL
        before the acknowledgement arrived (both may transition to ACCEPTED);
        otherwise OrderUpdated/OrderCancelRejected would try to return them to
        SUBMITTED, which NautilusTrader's order state machine does not allow.
        """
        client_order_id = order.client_order_id
        if client_order_id in self._accepted_ids or order.venue_order_id is not None:
            return
        if order.status not in (
            OrderStatus.INITIALIZED,
            OrderStatus.SUBMITTED,
            OrderStatus.PENDING_UPDATE,
            OrderStatus.PENDING_CANCEL,
        ):
            return
        self._mark_accepted(client_order_id)
        if provisional:
            self._provisional_accepts.add(client_order_id)
        self.generate_order_accepted(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=client_order_id,
            venue_order_id=venue_order_id,
            ts_event=ts_event,
        )

    def _mark_accepted(self, client_order_id: ClientOrderId) -> None:
        self._accepted_ids[client_order_id] = None
        while len(self._accepted_ids) > _ACCEPTED_MAX:
            self._accepted_ids.popitem(last=False)

    def _never_accepted(self, order: Order) -> bool:
        return order.venue_order_id is None and order.client_order_id not in self._accepted_ids

    def _index_venue_id(self, client_order_id: ClientOrderId, venue_order_id: VenueOrderId) -> None:
        """Index venue id -> client id and replay fill pushes that arrived before it was known."""
        if self._cache.client_order_id(venue_order_id) is None:
            try:
                self._cache.add_venue_order_id(client_order_id, venue_order_id)
            except Exception as e:
                self._log.debug(f"add_venue_order_id({client_order_id}, {venue_order_id}): {e}")
        for data in self._unmatched_fills.pop(venue_order_id.value, None) or []:
            self._log.info(f"Replaying fill push for {client_order_id} ({venue_order_id}) received before its order")
            self._handle_push_fill(data)

    def _buffer_unmatched_fill(self, order_id: Any, data: dict) -> None:
        pending = self._unmatched_fills.setdefault(str(order_id), [])
        pending.append(data)
        while len(self._unmatched_fills) > _UNMATCHED_FILLS_MAX:
            self._unmatched_fills.popitem(last=False)

    def _remember_fill(self, fill_id: str) -> bool:
        """Return False if the fill was already processed."""
        if fill_id in self._seen_fill_ids:
            return False
        self._seen_fill_ids[fill_id] = None
        while len(self._seen_fill_ids) > _SEEN_FILLS_MAX:
            self._seen_fill_ids.popitem(last=False)
        return True

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def _connect(self) -> None:
        """Connect to Futu OpenD for trading."""
        self._log.info("Connecting execution client to Futu OpenD...")
        try:
            created = await self._conn.acquire()
            self._log.info("Connected to Futu OpenD" if created else "Reusing existing Futu OpenD connection")

            if self._config.set_specific_venue:
                # Portfolio resolves accounts by instrument venue (HKEX/NYSE/...);
                # point every venue at the single FUTU account.
                self._cache.set_specific_venue(FUTU_VENUE)

            await self._discover_account()
            self._set_account_id(self.account_id_str)

            await self._unlock_if_configured()

            # Register push consumers BEFORE asking OpenD to push so nothing is lost.
            # Gateway notifications (1003) are reported by whichever client opened
            # the connection, so they are logged exactly once.
            if self._push_channel_id is None:
                protos = _EXEC_PUSH_PROTOS + ([FUTU_PROTO_NOTIFY] if created else [])
                self._push_channel_id = await asyncio.to_thread(self._client.start_push, protos)
            await asyncio.to_thread(self._client.sub_acc_push, [self._acc_id])
            self._restored_generation = self._conn.generation
            self._log.info(f"Subscribed to trade push for acc_id={self._acc_id}")

            await self._update_account_state(initial=True)

            self._push_task = self.create_task(self._run_push_loop())
            if self._config.account_refresh_interval > 0:
                self._account_refresh_task = self.create_task(self._run_account_refresh_loop())
            self._log.info(f"Execution push loop started (channel_id={self._push_channel_id})")
        except Exception as e:
            self._log.error(f"Failed to connect execution client: {e}")
            raise

    async def _discover_account(self) -> None:
        accounts = await asyncio.to_thread(
            self._client.get_acc_list,
            None,  # trd_category
            True,  # need_general_sec_account
        )

        if self._acc_id == 0:
            for acc in accounts:
                if acc["trd_env"] == self._trd_env and (acc.get("acc_status") or 0) == 0:
                    if self._trd_market in acc.get("trd_market_auth_list", []):
                        self._acc_id = acc["acc_id"]
                        self._log.info(f"Auto-selected account: {self._acc_id}")
                        break
            if self._acc_id == 0 and accounts:
                self._acc_id = accounts[0]["acc_id"]
                self._log.warning(
                    f"No matching account for trd_env={self._trd_env} market={self._trd_market}, "
                    f"falling back to first account: {self._acc_id}",
                )
            elif self._acc_id == 0:
                self._log.error("No accounts found from Futu OpenD, trading will not work")

        for acc in accounts:
            if acc["acc_id"] == self._acc_id:
                self._trd_market_auth_list = list(acc.get("trd_market_auth_list") or [self._trd_market])
                futu_acc_type = acc.get("acc_type")
                if futu_acc_type == FUTU_ACC_TYPE_MARGIN and self.account_type != AccountType.MARGIN:
                    self._log.warning("Futu reports a MARGIN account but config.account_type is CASH")
                elif futu_acc_type == FUTU_ACC_TYPE_CASH and self.account_type != AccountType.CASH:
                    self._log.warning("Futu reports a CASH account but config.account_type is MARGIN")
                break
        else:
            self._trd_market_auth_list = [self._trd_market]
        self._log.info(f"Authorized markets: {self._trd_market_auth_list}")

    async def _unlock_if_configured(self) -> None:
        if not self._config.unlock_pwd_md5:
            return
        await asyncio.to_thread(
            self._client.unlock_trade,
            True,
            self._config.unlock_pwd_md5,
            self._config.security_firm,
        )
        self._log.info("Trade unlocked")

    async def _disconnect(self) -> None:
        """Disconnect from Futu OpenD."""
        self._log.info("Disconnecting execution client...")
        for attr in ("_push_task", "_account_refresh_task"):
            task = getattr(self, attr)
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
                setattr(self, attr, None)
        try:
            await self._conn.release()
        except Exception as e:
            self._log.error(f"Error disconnecting execution client: {e}")

    async def _poll_push(self) -> dict | None:
        if self._use_async_push:
            return await self._client.poll_push_async(self._push_channel_id)
        return await asyncio.to_thread(self._client.poll_push, self._push_channel_id, 100)

    async def _run_push_loop(self) -> None:
        """Background loop receiving trade push messages."""
        self._log.debug("Execution push loop running")
        try:
            while True:
                try:
                    if self._conn.generation != self._restored_generation:
                        await self._restore_session()
                    msg = await self._poll_push()
                except asyncio.CancelledError:
                    raise
                except ConnectionError as e:
                    self._log.warning(f"Futu OpenD connection lost: {e}")
                    await self._reconnect()
                    continue
                except Exception as e:
                    self._log.error(f"Exec push poll error: {e}")
                    await asyncio.sleep(0.5)
                    continue

                if msg is None:
                    continue
                proto_id = msg["proto_id"]
                data = msg["data"]
                try:
                    if proto_id == FUTU_PROTO_TRD_ORDER:
                        self._handle_push_order(data)
                    elif proto_id == FUTU_PROTO_TRD_FILL:
                        self._handle_push_fill(data)
                    elif proto_id == FUTU_PROTO_NOTIFY:
                        log_futu_notify(self._log, data)
                except Exception as e:
                    self._log.error(f"Error handling exec push proto_id={proto_id}: {e}")
        except asyncio.CancelledError:
            self._log.debug("Execution push loop cancelled")

    async def _reconnect(self) -> None:
        if not self._config.reconnect:
            self._log.error("Reconnect disabled; execution client will stay offline")
            await asyncio.sleep(self._config.reconnect_interval)
            return
        self._log.warning(f"Reconnecting in {self._config.reconnect_interval}s...")
        await asyncio.sleep(self._config.reconnect_interval)
        try:
            await self._conn.ensure_connected()
            self._log.info("Execution client reconnected to Futu OpenD")
        except Exception as e:
            self._log.error(f"Execution reconnection failed: {e}")

    async def _restore_session(self) -> None:
        """Re-unlock, re-subscribe pushes and refresh balances after a reconnect."""
        generation = self._conn.generation
        self._log.info(f"Restoring trading session (connection generation {generation})")
        try:
            await self._unlock_if_configured()
            await asyncio.to_thread(self._client.sub_acc_push, [self._acc_id])
        except Exception as e:
            self._log.error(f"Failed to restore trading session: {e}")
        self._restored_generation = generation
        await self._update_account_state()

    # ------------------------------------------------------------------
    # Account state
    # ------------------------------------------------------------------

    async def _update_account_state(self, initial: bool = False) -> None:
        """Query Futu account funds and generate AccountState.

        A failed query on a *refresh* keeps the last published state (publishing
        zeros would make the risk engine deny every order).  On the initial
        connect a zero state is still published so the account gets registered.
        """
        result = await self._get_account_balances()
        if result is None:
            if not initial:
                self._log.warning("Account refresh failed; keeping last known balances")
                return
            currency = Currency.from_str(FUTU_TRD_MARKET_TO_CURRENCY.get(self._trd_market, "USD"))
            zero = Money(0, currency)
            self._log.error("Initial funds query failed; registering account with zero balance")
            result = ([AccountBalance(total=zero, locked=zero, free=zero)], [])
        balances, margins = result
        if not balances:
            self._log.warning("No account balances obtained")
            return

        self.generate_account_state(
            balances=balances,
            margins=margins,
            reported=True,
            ts_event=self._clock.timestamp_ns(),
        )
        for b in balances:
            self._log.info(f"Account balance: {b.currency} total={b.total} free={b.free} locked={b.locked}")

    async def _get_account_balance(self) -> list[AccountBalance]:
        """Backwards-compatible wrapper returning balances only (empty on failure)."""
        result = await self._get_account_balances()
        return result[0] if result is not None else []

    async def _get_account_balances(self) -> tuple[list[AccountBalance], list[MarginBalance]] | None:
        """Query funds; ``None`` when OpenD could not be queried."""
        currency = Currency.from_str(FUTU_TRD_MARKET_TO_CURRENCY.get(self._trd_market, "USD"))
        try:
            funds = await asyncio.to_thread(
                self._client.get_funds,
                self._trd_env,
                self._acc_id,
                self._trd_market,
                None,
            )
        except Exception as e:
            self._log.warning(f"Failed to get funds: {e}")
            return None

        balances = parse_funds_to_balances(funds, currency)
        margins: list[MarginBalance] = []
        if self.account_type == AccountType.MARGIN:
            margin_currency = balances[0].currency if balances else currency
            margins = parse_funds_to_margins(funds, margin_currency)
        return balances, margins

    def _schedule_account_refresh(self) -> None:
        """Refresh balances shortly after order/fill activity (debounced)."""
        if self._refresh_scheduled:
            return
        self._refresh_scheduled = True

        async def _refresh() -> None:
            try:
                await asyncio.sleep(_ACCOUNT_REFRESH_DEBOUNCE_SECS)
                await self._update_account_state()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self._log.warning(f"Account refresh failed: {e}")
            finally:
                self._refresh_scheduled = False

        self.create_task(_refresh())

    async def _run_account_refresh_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._config.account_refresh_interval)
                try:
                    await self._update_account_state()
                except Exception as e:
                    self._log.warning(f"Periodic account refresh failed: {e}")
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Push handlers
    # ------------------------------------------------------------------

    def _resolve_order(self, order_id: Any, remark: str | None) -> Order | None:
        """Find the cached Nautilus order for a Futu order id (via cache index or remark)."""
        venue_order_id = VenueOrderId(str(order_id))
        client_order_id = self._cache.client_order_id(venue_order_id)
        if client_order_id is None:
            client_order_id = client_order_id_from_remark(remark)
            if client_order_id is None:
                return None
            if self._cache.order(client_order_id) is None:
                return None
            self._index_venue_id(client_order_id, venue_order_id)
        return self._cache.order(client_order_id)

    def _handle_push_order(self, data: dict) -> None:
        """Handle order update push (proto 2208)."""
        try:
            if data.get("trd_env") != self._trd_env or data.get("acc_id") != self._acc_id:
                return

            order_data = data.get("order")
            if order_data is None:
                self._log.warning("Push order missing 'order' key")
                return
            order_status_int = order_data.get("order_status")
            if order_status_int is None:
                self._log.warning("Push order missing 'order_status'")
                return
            order_id = order_data.get("order_id")
            if order_id is None:
                self._log.warning("Push order missing 'order_id'")
                return

            order = self._resolve_order(order_id, order_data.get("remark"))
            if order is None:
                self._log.debug(f"Order push for unknown/external order_id={order_id} ignored")
                return

            venue_order_id = VenueOrderId(str(order_id))
            nt_status = futu_order_status_to_nautilus(order_status_int)
            instrument_id = order.instrument_id
            instrument = self._instrument_for(instrument_id)
            ts_event = self._ts_or_now(order_data.get("update_timestamp"))
            reason = order_data.get("last_err_msg") or f"Futu order status {order_status_int}"

            self._on_venue_id_learned(order, venue_order_id, order_status_int, via_report=False)
            order = self._cache.order(order.client_order_id) or order
            provisional = order.client_order_id in self._provisional_accepts
            if nt_status in (OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED):
                self._provisional_accepts.discard(order.client_order_id)  # the venue acknowledged it

            if nt_status == OrderStatus.ACCEPTED:
                self._on_venue_accepted(order, order_data, venue_order_id, instrument, ts_event)
            elif nt_status in (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED):
                # Fills arrive via 2218; make sure the order is ACCEPTED first
                self._ensure_accepted(order, venue_order_id, ts_event)
            elif nt_status == OrderStatus.REJECTED:
                self._provisional_accepts.discard(order.client_order_id)
                if order.status in (OrderStatus.INITIALIZED, OrderStatus.SUBMITTED) or (
                    not order.is_closed and (self._never_accepted(order) or provisional)
                ):
                    self.generate_order_rejected(
                        strategy_id=order.strategy_id,
                        instrument_id=instrument_id,
                        client_order_id=order.client_order_id,
                        reason=str(reason),
                        ts_event=ts_event,
                    )
                elif not order.is_closed:
                    # Venue failed an already-working order: treat as cancel
                    self._log.warning(f"Order {order.client_order_id} failed at venue after acceptance: {reason}")
                    self.generate_order_canceled(
                        strategy_id=order.strategy_id,
                        instrument_id=instrument_id,
                        client_order_id=order.client_order_id,
                        venue_order_id=venue_order_id,
                        ts_event=ts_event,
                    )
            elif nt_status == OrderStatus.CANCELED:
                if not order.is_closed:
                    self.generate_order_canceled(
                        strategy_id=order.strategy_id,
                        instrument_id=instrument_id,
                        client_order_id=order.client_order_id,
                        venue_order_id=venue_order_id,
                        ts_event=ts_event,
                    )
            # SUBMITTED / PENDING_CANCEL / INITIALIZED: transient, nothing to emit

            self._schedule_account_refresh()
        except Exception as e:
            self._log.error(f"Unexpected error in _handle_push_order: {e}")

    def _on_venue_id_learned(
        self,
        order: Order,
        venue_order_id: VenueOrderId,
        futu_status: int | None,
        via_report: bool,
    ) -> None:
        """An order push or status report revealed an order whose placement was unclear.

        Applies the requests queued while its venue id was unknown.  On the
        report path (in-flight check, the resolver) the execution engine emits
        OrderAccepted itself when it reconciles the report, so the follow-up
        work runs as a task after that.  An order OpenD is still working
        although NautilusTrader already closed it (the in-flight check gave up)
        is canceled at the venue.
        """
        client_order_id = order.client_order_id
        self._index_venue_id(client_order_id, venue_order_id)
        if client_order_id not in self._uncertain:
            return
        self._uncertain.discard(client_order_id)
        placed = self._placed_values.pop(client_order_id, None)
        self._log.info(f"Order {client_order_id} identified at OpenD as {venue_order_id} after an unclear placement")
        if futu_status not in FUTU_ORDER_STATUS_ACTIVE:
            self._deferred_cancels.discard(client_order_id)
            self._deferred_modifies.pop(client_order_id, None)
            return
        if order.is_closed:
            self._deferred_cancels.discard(client_order_id)
            self._deferred_modifies.pop(client_order_id, None)
            self._log.error(
                f"Order {client_order_id} is working at OpenD as {venue_order_id} but was closed locally "
                f"({order.status_string()}); canceling it at the venue",
            )
            self.create_task(self._send_cancel(order, venue_order_id, report_failure=False))
            return
        if via_report:
            self._mark_accepted(client_order_id)
            self.create_task(self._resume_after_unclear_placement(client_order_id, venue_order_id, placed))
            return
        self._ensure_accepted(order, venue_order_id, self._clock.timestamp_ns())
        self._emit_placed_values(order, venue_order_id, placed)
        self.create_task(self._apply_deferred(order, venue_order_id, base=placed))

    async def _resume_after_unclear_placement(
        self,
        client_order_id: ClientOrderId,
        venue_order_id: VenueOrderId,
        placed: dict[str, Any] | None,
    ) -> None:
        order = self._cache.order(client_order_id)
        if order is None:
            return
        self._emit_placed_values(order, venue_order_id, placed)
        await self._apply_deferred(order, venue_order_id, base=placed)

    def _emit_placed_values(self, order: Order, venue_order_id: VenueOrderId, placed: dict[str, Any] | None) -> None:
        """The order went out with a modify applied before placement: report those values."""
        if placed is None or order.is_closed:
            return
        self.generate_order_updated(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            venue_order_id=venue_order_id,
            quantity=placed["quantity"],
            price=placed["price"],
            trigger_price=placed["trigger_price"],
            ts_event=self._clock.timestamp_ns(),
        )

    def _on_venue_accepted(self, order: Order, order_data: dict, venue_order_id: VenueOrderId, instrument, ts_event: int) -> None:
        """A SUBMITTED status from Futu: initial acceptance or post-modify acknowledgement."""
        if self._never_accepted(order) or order.status in (OrderStatus.INITIALIZED, OrderStatus.SUBMITTED):
            self._ensure_accepted(order, venue_order_id, ts_event)
            return

        if order.status == OrderStatus.PENDING_UPDATE:
            # Our own modify is in flight: `_modify_order` emits OrderUpdated
            # (or OrderModifyRejected) from the request result, so the venue's
            # acknowledgement push must not emit a second OrderUpdated.
            return

        new_qty = make_qty(order_data.get("qty"), instrument)
        new_price = make_price(order_data["price"], instrument) if order_data.get("price") else None
        new_trigger = make_price(order_data["aux_price"], instrument) if order_data.get("aux_price") else None
        current_price = order.price if order.has_price else None
        current_trigger = order.trigger_price if order.has_trigger_price else None
        changed = (
            new_qty != order.quantity
            or (new_price is not None and current_price is not None and new_price != current_price)
            or (new_trigger is not None and current_trigger is not None and new_trigger != current_trigger)
        )
        if changed and not order.is_closed:
            self.generate_order_updated(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                venue_order_id=venue_order_id,
                quantity=new_qty,
                price=new_price if new_price is not None else current_price,
                trigger_price=new_trigger if new_trigger is not None else current_trigger,
                ts_event=ts_event,
            )

    def _handle_push_fill(self, data: dict) -> None:
        """Handle fill update push (proto 2218)."""
        try:
            if data.get("trd_env") != self._trd_env or data.get("acc_id") != self._acc_id:
                return

            fill_data = data.get("fill")
            if fill_data is None:
                self._log.warning("Push fill missing 'fill' key")
                return
            order_id = fill_data.get("order_id")
            if order_id is None:
                return
            if fill_data.get("status") == FUTU_FILL_STATUS_CANCELLED:
                self._log.warning(f"Fill {fill_data.get('fill_id')} for order {order_id} was cancelled by the venue")
                return

            order = self._resolve_order(order_id, None)
            if order is None:
                # Possibly our order whose order push / place_order reply has not
                # arrived yet: keep it for replay once the venue id is known.
                self._log.debug(f"Fill push for unknown order_id={order_id} kept for replay")
                self._buffer_unmatched_fill(order_id, data)
                return

            fill_id = str(fill_data.get("fill_id") or fill_data.get("fill_id_ex") or "")
            if not fill_id or not self._remember_fill(fill_id):
                return

            venue_order_id = VenueOrderId(str(order_id))
            instrument_id = order.instrument_id
            instrument = self._instrument_for(instrument_id)
            ts_event = self._ts_or_now(fill_data.get("create_timestamp"))
            if instrument is not None:
                currency = instrument.quote_currency
            else:
                currency = qot_market_to_currency(sec_market_to_qot_market(fill_data.get("sec_market")))

            self._ensure_accepted(order, venue_order_id, ts_event)

            self.generate_order_filled(
                strategy_id=order.strategy_id,
                instrument_id=instrument_id,
                client_order_id=order.client_order_id,
                venue_order_id=venue_order_id,
                venue_position_id=None,
                trade_id=TradeId(fill_id),
                order_side=futu_trd_side_to_nautilus(fill_data.get("trd_side", 0)),
                order_type=order.order_type,
                last_qty=make_qty(fill_data.get("qty", 0), instrument),
                last_px=make_price(fill_data.get("price", 0), instrument),
                quote_currency=currency,
                commission=Money(0, currency),
                liquidity_side=LiquiditySide.NO_LIQUIDITY_SIDE,
                ts_event=ts_event,
            )
            self._schedule_account_refresh()
        except Exception as e:
            self._log.error(f"Unexpected error in _handle_push_fill: {e}")

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def _submit_order(self, command: Any) -> None:
        """Submit a new order."""
        await self._place_order(command.order)

    async def _submit_order_list(self, command: Any) -> None:
        """Submit the orders of an order list one by one.

        Futu has no native order lists or contingent orders.  OTO/bracket
        lists are rejected: placing child orders before the parent fills could
        e.g. sell short, so they must be held by the OrderEmulator instead
        (give the child orders an ``emulation_trigger``).

        Independent orders and OCO/OUO groups are placed individually.  Every
        leg is validated and marked SUBMITTED before the first one is placed,
        so the strategy's ``manage_contingent_orders`` sees all legs while
        they are being placed; its cancels/modifies for legs not yet placed
        are applied before (or right after) placing them.  When an OCO/OUO leg
        is rejected or canceled before placement, the not yet placed legs
        linked to it are canceled instead of placed.
        """
        orders: list[Order] = list(command.order_list.orders)
        if any(o.contingency_type == ContingencyType.OTO or o.parent_order_id is not None for o in orders):
            reason = (
                "Futu does not support OTO/bracket orders; set an emulation_trigger on the "
                "child orders so the OrderEmulator releases them when the parent fills"
            )
            self._log.error(f"Cannot submit {command.order_list.id}: {reason}")
            for order in orders:
                self._reject_locally(order, reason)
            return

        params: dict[ClientOrderId, dict[str, Any]] = {}
        for order in orders:
            try:
                params[order.client_order_id] = build_futu_order_params(order, self._config.fill_outside_rth)
            except ValueError as e:
                reason = f"{order.client_order_id}: {e}"
                self._log.error(f"Cannot submit {command.order_list.id}: {reason}")
                for o in orders:
                    self._reject_locally(o, reason)
                return

        if any(o.contingency_type in (ContingencyType.OCO, ContingencyType.OUO) for o in orders):
            self._log.info(
                f"{command.order_list.id}: OCO/OUO legs are placed one by one; "
                "contingencies are enforced by the strategy's `manage_contingent_orders`",
            )

        ts_now = self._clock.timestamp_ns()
        for order in orders:
            self._unplaced.add(order.client_order_id)
            self.generate_order_submitted(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                ts_event=ts_now,
            )

        by_id = {o.client_order_id: o for o in orders}
        doomed: dict[ClientOrderId, ClientOrderId] = {}  # unplaced leg -> closed leg it is linked to

        def close_linked(leg: Order) -> None:
            """OCO/OUO: a closed leg cancels its linked legs (transitively, as the manager would)."""
            stack = [leg]
            while stack:
                closed = stack.pop()
                if closed.contingency_type not in (ContingencyType.OCO, ContingencyType.OUO):
                    continue
                for linked_id in closed.linked_order_ids or []:
                    if linked_id in by_id and linked_id != leg.client_order_id and linked_id not in doomed:
                        doomed[linked_id] = leg.client_order_id
                        stack.append(by_id[linked_id])

        for order in orders:
            client_order_id = order.client_order_id
            current = self._cache.order(client_order_id) or order
            if current.is_closed:
                # e.g. resolved by the in-flight check while earlier legs were placed
                self._log.info(f"Order {client_order_id} closed ({current.status_string()}) before it was placed")
                self._forget_unplaced(client_order_id)
                close_linked(order)
                continue
            if client_order_id in doomed or client_order_id in self._deferred_cancels:
                self._forget_unplaced(client_order_id)
                if client_order_id in doomed:
                    self._log.warning(f"Canceling {client_order_id}: linked leg {doomed[client_order_id]} closed before it was placed")
                else:
                    self._log.info(f"Order {client_order_id} canceled before it was placed")
                self.generate_order_canceled(
                    strategy_id=order.strategy_id,
                    instrument_id=order.instrument_id,
                    client_order_id=client_order_id,
                    venue_order_id=None,
                    ts_event=self._clock.timestamp_ns(),
                )
                close_linked(order)
                continue
            outcome = await self._place_order(order, params[client_order_id], submitted=True)
            if outcome == _REJECTED:
                close_linked(order)

    def _forget_unplaced(self, client_order_id: ClientOrderId) -> None:
        self._unplaced.discard(client_order_id)
        self._uncertain.discard(client_order_id)
        self._deferred_cancels.discard(client_order_id)
        self._deferred_modifies.pop(client_order_id, None)
        self._placed_values.pop(client_order_id, None)

    def _reject_locally(self, order: Order, reason: str) -> None:
        """Reject an order that was never sent to OpenD."""
        ts_now = self._clock.timestamp_ns()
        self.generate_order_submitted(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            ts_event=ts_now,
        )
        self.generate_order_rejected(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            reason=reason,
            ts_event=ts_now,
        )

    @staticmethod
    def _modified_params(order: Order, params: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
        """``place_order`` parameters with a modify applied that arrived before placement."""
        params = dict(params)
        if fields.get("quantity") is not None:
            params["qty"] = float(fields["quantity"])
        if fields.get("price") is not None and params.get("price") is not None:
            params["price"] = float(fields["price"])
        if fields.get("trigger_price") is not None and params.get("aux_price") is not None:
            params["aux_price"] = float(fields["trigger_price"])
        return params

    @staticmethod
    def _placed_fields(order: Order, fields: dict[str, Any]) -> dict[str, Any]:
        """Full quantity/price/trigger values of an order placed with ``fields`` applied."""
        return {
            "quantity": fields.get("quantity") or order.quantity,
            "price": fields["price"] if fields.get("price") is not None else (order.price if order.has_price else None),
            "trigger_price": fields["trigger_price"] if fields.get("trigger_price") is not None else (
                order.trigger_price if order.has_trigger_price else None
            ),
        }

    async def _place_order(
        self,
        order: Order,
        params: dict[str, Any] | None = None,
        submitted: bool = False,
    ) -> str:
        """Place one order on OpenD; returns ``"placed"``, ``"rejected"`` or ``"unknown"``.

        Emits OrderSubmitted (unless ``submitted``), then OrderRejected when
        OpenD refuses the order.  A failure after the request was sent
        (timeout, lost link) leaves the order SUBMITTED: its pushes (matched by
        ``remark``) or the in-flight order check resolve it later.  A modify
        received before placement is placed directly; cancels/modifies that
        arrive while the request is in flight are applied afterwards.
        """
        instrument_id = order.instrument_id
        client_order_id = order.client_order_id
        market, code = instrument_id_to_futu_security(instrument_id)
        sec_market = VENUE_TO_FUTU_TRD_SEC_MARKET.get(instrument_id.venue)
        trd_market = self._trd_market_for(instrument_id)

        if not submitted:
            self.generate_order_submitted(
                strategy_id=order.strategy_id,
                instrument_id=instrument_id,
                client_order_id=client_order_id,
                ts_event=self._clock.timestamp_ns(),
            )

        def reject(reason: str) -> str:
            self._forget_unplaced(client_order_id)
            self.generate_order_rejected(
                strategy_id=order.strategy_id,
                instrument_id=instrument_id,
                client_order_id=client_order_id,
                reason=reason,
                ts_event=self._clock.timestamp_ns(),
            )
            return _REJECTED

        if params is None:
            try:
                params = build_futu_order_params(order, self._config.fill_outside_rth)
            except ValueError as e:
                self._log.error(f"Cannot submit {client_order_id}: {e}")
                return reject(str(e))

        premodify = self._deferred_modifies.pop(client_order_id, None)
        placed: dict[str, Any] | None = None
        if premodify is not None:
            params = self._modified_params(order, params, premodify)
            placed = self._placed_fields(order, premodify)

        self._unplaced.add(client_order_id)
        try:
            result = await asyncio.to_thread(
                self._client.place_order,
                self._trd_env,
                self._acc_id,
                trd_market,
                params["trd_side"],
                params["order_type"],
                code,
                params["qty"],
                params["price"],
                sec_market,
                params["remark"],
                params["time_in_force"],
                params["fill_outside_rth"],
                params["aux_price"],
                params["trail_type"],
                params["trail_value"],
                params["trail_spread"],
            )
        except Exception as e:
            if not is_ambiguous_order_error(e):
                self._log.error(f"Failed to submit order {client_order_id}: {e}")
                return reject(str(e))
            known = self._cache.venue_order_id(client_order_id)
            if known is None:
                self._log.warning(
                    f"Placement of {client_order_id} unclear ({e}); leaving it SUBMITTED and looking it up "
                    "at OpenD (order pushes and the in-flight check can also resolve it)",
                )
                self._unplaced.discard(client_order_id)
                self._uncertain.add(client_order_id)
                if placed is not None:
                    self._placed_values[client_order_id] = placed
                self.create_task(self._resolve_unclear_placement(order))
                return _UNKNOWN
            # An order push already identified the order while the request was in flight
            self._log.warning(f"place_order for {client_order_id} failed ({e}) but OpenD already reported it as {known}")
            result = {"order_id": known.value}

        order_id = (result or {}).get("order_id")
        if order_id is None:
            self._log.error(f"place_order returned no order_id for {client_order_id}: {result}")
            return reject("Futu returned no order_id")

        venue_order_id = VenueOrderId(str(order_id))
        # Index venue id -> client id so pushes (which may already have arrived
        # and been matched through `remark`) resolve the order.  ACCEPTED is
        # generated from the order push, the single source of truth.
        self._unplaced.discard(client_order_id)
        self._index_venue_id(client_order_id, venue_order_id)
        self._log.info(f"Order submitted: {client_order_id} -> {venue_order_id}")

        current = self._cache.order(client_order_id) or order
        if placed is not None:
            # The order went out with the modified values: resolve the pending update.
            self._ensure_accepted(current, venue_order_id, self._clock.timestamp_ns())
            self._emit_placed_values(current, venue_order_id, placed)
        await self._apply_deferred(current, venue_order_id, base=placed)
        return _PLACED

    async def _resolve_unclear_placement(self, order: Order) -> None:
        """Look an unclearly placed order up at OpenD until its fate is known.

        Found: the order is reported to the execution engine like the in-flight
        check does, and queued requests are applied.  Missing from several
        successful lookups: the request never reached OpenD, so it is rejected.
        """
        client_order_id = order.client_order_id
        trd_market = self._trd_market_for(order.instrument_id)
        not_found = 0
        for delay in _RESOLVE_DELAYS:
            await asyncio.sleep(delay)
            if client_order_id not in self._uncertain:
                return  # resolved by a push or a report
            try:
                order_dicts = await asyncio.to_thread(
                    self._client.get_order_list, self._trd_env, self._acc_id, trd_market,
                )
            except Exception as e:
                self._log.debug(f"Lookup of {client_order_id} failed: {e}")
                continue
            if client_order_id not in self._uncertain:
                return
            match = next(
                (o for o in order_dicts or [] if client_order_id_from_remark(o.get("remark")) == client_order_id),
                None,
            )
            if match is None:
                not_found += 1
                if not_found >= _RESOLVE_NOT_FOUND_LIMIT:
                    break
                continue
            current = self._cache.order(client_order_id) or order
            report = parse_futu_order_to_report(
                match, self.account_id_str, self._report_instrument(match), self._clock.timestamp_ns(),
            )
            self._on_venue_id_learned(current, VenueOrderId(str(match["order_id"])), match.get("order_status"), via_report=True)
            if not current.is_closed:
                self._send_order_status_report(report)
            return

        if client_order_id not in self._uncertain:
            return
        self._forget_unplaced(client_order_id)
        current = self._cache.order(client_order_id) or order
        if current.is_closed:
            return
        if not_found >= _RESOLVE_NOT_FOUND_LIMIT:
            self._log.warning(f"Order {client_order_id} not found at OpenD after an unclear placement; rejecting it")
            self.generate_order_rejected(
                strategy_id=current.strategy_id,
                instrument_id=current.instrument_id,
                client_order_id=client_order_id,
                reason="not found at OpenD after an unclear placement",
                ts_event=self._clock.timestamp_ns(),
            )
        else:
            self._log.error(
                f"Could not look up {client_order_id} at OpenD; its state is left to the in-flight check "
                "and reconciliation",
            )

    async def _apply_deferred(
        self,
        order: Order,
        venue_order_id: VenueOrderId,
        base: dict[str, Any] | None = None,
    ) -> None:
        """Apply cancel/modify requests that arrived before the venue order id was known.

        ``base`` holds the values the order was actually placed with when they
        differ from the cached order (a modify applied before placement).
        """
        client_order_id = order.client_order_id
        deferred_cancel = client_order_id in self._deferred_cancels
        deferred_modify = self._deferred_modifies.pop(client_order_id, None)
        self._deferred_cancels.discard(client_order_id)
        order = self._cache.order(client_order_id) or order
        if deferred_cancel:
            self._log.info(f"Applying cancel requested before {client_order_id} was placed")
            await self._cancel_cached_order(order, venue_order_id)
        elif deferred_modify is not None:
            self._log.info(f"Applying modify requested before {client_order_id} was placed")
            await self._send_modify(order, venue_order_id, deferred_modify, base=base)

    def _merge_deferred_modify(self, client_order_id: ClientOrderId, fields: dict[str, Any]) -> None:
        """Merge a modify into the pending one (the latest value of each field wins)."""
        pending = self._deferred_modifies.setdefault(client_order_id, {})
        for key, value in fields.items():
            if value is not None:
                pending[key] = value

    def _venue_order_id_for(self, order: Order, venue_order_id: VenueOrderId | None = None) -> VenueOrderId | None:
        """The venue order id from the command, the order, or the cache index set on placement."""
        return venue_order_id or order.venue_order_id or self._cache.venue_order_id(order.client_order_id)

    def _awaiting_venue_id(self, order: Order) -> bool:
        """Placement not finished (queued/in flight) or outcome not yet known."""
        return order.client_order_id in self._unplaced or order.client_order_id in self._uncertain

    async def _modify_order(self, command: Any) -> None:
        """Modify an existing order."""
        order: Order | None = self._cache.order(command.client_order_id)
        if order is None:
            self._log.error(f"Cannot modify order: {command.client_order_id} not found in cache")
            return
        if order.is_closed:
            self._log.warning(f"Cannot modify order {order.client_order_id}: already closed ({order.status_string()})")
            return
        fields = {"quantity": command.quantity, "price": command.price, "trigger_price": command.trigger_price}
        venue_order_id = self._venue_order_id_for(order, command.venue_order_id)
        if venue_order_id is None and self._awaiting_venue_id(order):
            self._log.info(f"Deferring modify of {order.client_order_id} until it is placed")
            self._merge_deferred_modify(order.client_order_id, fields)
            return
        if venue_order_id is None:
            self._log.error(f"Cannot modify order {order.client_order_id} without venue_order_id")
            self.generate_order_modify_rejected(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                venue_order_id=None,
                reason="no venue_order_id",
                ts_event=self._clock.timestamp_ns(),
            )
            return
        await self._send_modify(order, venue_order_id, fields)

    async def _send_modify(
        self,
        order: Order,
        venue_order_id: VenueOrderId,
        fields: dict[str, Any],
        base: dict[str, Any] | None = None,
    ) -> None:
        """Send a modify; fields it leaves out keep ``base`` (values placed) or the cached order's."""
        current = base or self._placed_fields(order, {})
        quantity = fields.get("quantity") or current["quantity"]
        price = fields["price"] if fields.get("price") is not None else current["price"]
        trigger_price = fields["trigger_price"] if fields.get("trigger_price") is not None else current["trigger_price"]

        # OrderPendingUpdate is applied by the strategy before the command is sent.
        try:
            await asyncio.to_thread(
                self._client.modify_order,
                self._trd_env,
                self._acc_id,
                self._trd_market_for(order.instrument_id),
                int(venue_order_id.value),
                FUTU_MODIFY_ORDER_OP_NORMAL,
                float(quantity),
                float(price) if price is not None else None,
                float(trigger_price) if trigger_price is not None else None,
            )
        except Exception as e:
            self._log.error(f"Failed to modify order {order.client_order_id}: {e}")
            # The order exists at the venue: accept it first so the rejection can
            # return it from PENDING_UPDATE to ACCEPTED.
            self._ensure_accepted(order, venue_order_id, self._clock.timestamp_ns(), provisional=True)
            self.generate_order_modify_rejected(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                venue_order_id=venue_order_id,
                reason=str(e),
                ts_event=self._clock.timestamp_ns(),
            )
            return

        ts_now = self._clock.timestamp_ns()
        self._ensure_accepted(order, venue_order_id, ts_now)
        self.generate_order_updated(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            venue_order_id=venue_order_id,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            ts_event=ts_now,
        )
        self._log.info(f"Order modified: {order.client_order_id} ({venue_order_id})")

    async def _cancel_order(self, command: Any) -> None:
        """Cancel an existing order."""
        order: Order | None = self._cache.order(command.client_order_id)
        if order is None:
            self._log.error(f"Cannot cancel order: {command.client_order_id} not found in cache")
            return
        await self._cancel_cached_order(order, command.venue_order_id)

    async def _cancel_cached_order(self, order: Order, venue_order_id: VenueOrderId | None) -> None:
        if order.is_closed:
            self._log.debug(f"Cancel of {order.client_order_id} skipped: already closed ({order.status_string()})")
            return
        venue_order_id = self._venue_order_id_for(order, venue_order_id)
        if venue_order_id is None and self._awaiting_venue_id(order):
            self._log.info(f"Deferring cancel of {order.client_order_id} until it is placed")
            self._deferred_cancels.add(order.client_order_id)
            return
        if venue_order_id is None:
            self._log.error(f"Cannot cancel order {order.client_order_id} without venue_order_id")
            self.generate_order_cancel_rejected(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                venue_order_id=None,
                reason="no venue_order_id",
                ts_event=self._clock.timestamp_ns(),
            )
            return

        await self._send_cancel(order, venue_order_id)

    async def _send_cancel(self, order: Order, venue_order_id: VenueOrderId, report_failure: bool = True) -> None:
        """Send a cancel to OpenD (OrderPendingCancel is applied by the strategy beforehand)."""
        client_order_id = order.client_order_id
        try:
            await asyncio.to_thread(
                self._client.modify_order,
                self._trd_env,
                self._acc_id,
                self._trd_market_for(order.instrument_id),
                int(venue_order_id.value),
                FUTU_MODIFY_ORDER_OP_CANCEL,
                None,
                None,
            )
        except Exception as e:
            sent_at = self._cancel_sent.get(client_order_id)
            if sent_at is not None and self._clock.timestamp_ns() - sent_at < _DUPLICATE_CANCEL_WINDOW_NS:
                self._log.info(f"Repeated cancel of {client_order_id} refused ({e}); an earlier cancel is in progress")
                return
            self._log.error(f"Failed to cancel order {client_order_id}: {e}")
            if not report_failure:
                return
            # The order exists at the venue: accept it first so the rejection can
            # return it from PENDING_CANCEL to ACCEPTED.
            self._ensure_accepted(order, venue_order_id, self._clock.timestamp_ns(), provisional=True)
            self.generate_order_cancel_rejected(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=client_order_id,
                venue_order_id=venue_order_id,
                reason=str(e),
                ts_event=self._clock.timestamp_ns(),
            )
            return
        self._cancel_sent[client_order_id] = self._clock.timestamp_ns()
        while len(self._cancel_sent) > _ACCEPTED_MAX:
            self._cancel_sent.popitem(last=False)
        self._log.info(f"Cancel requested: {client_order_id} ({venue_order_id})")

    async def _cancel_all_orders(self, command: Any) -> None:
        """Cancel the strategy's open and in-flight orders for the command's instrument (and side).

        In-flight (SUBMITTED) orders are included: NautilusTrader's
        ``cancel_all_orders``/``market_exit`` rely on the client for them.
        Orders still being placed are canceled before or right after placement.
        """
        side = getattr(command, "order_side", OrderSide.NO_ORDER_SIDE)
        query = {"instrument_id": command.instrument_id, "strategy_id": command.strategy_id, "side": side}
        orders: dict[ClientOrderId, Order] = {o.client_order_id: o for o in self._cache.orders_open(**query)}
        for order in self._cache.orders_inflight(**query):
            orders.setdefault(order.client_order_id, order)
        cancelled = 0
        for order in orders.values():
            if order.is_closed:
                continue
            await self._cancel_cached_order(order, order.venue_order_id)
            cancelled += 1
        self._log.info(f"Cancel-all: requested cancel for {cancelled} orders on {command.instrument_id}")

    async def _batch_cancel_orders(self, command: Any) -> None:
        for cancel in command.cancels:
            await self._cancel_order(cancel)

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    def _markets_for(self, instrument_id: InstrumentId | None) -> list[int]:
        if instrument_id is None:
            return list(self._trd_market_auth_list)
        return [self._trd_market_for(instrument_id)]

    async def _fetch_orders(
        self,
        markets: list[int],
        start: datetime | None = None,
        end: datetime | None = None,
        codes: list[str] | None = None,
        include_today: bool = True,
    ) -> list[dict]:
        """Today's orders, plus history orders when ``start`` reaches before today.

        Entries from the today-list win over history entries for the same order
        (they carry the latest status).  ``include_today=False`` queries the
        history only.
        """
        orders: list[dict] = []
        seen: set[str] = set()

        def add(order_dicts) -> None:
            for order_dict in order_dicts or []:
                key = str(order_dict.get("order_id"))
                if key not in seen:
                    seen.add(key)
                    orders.append(order_dict)

        for market in markets:
            if include_today:
                try:
                    add(await asyncio.to_thread(self._client.get_order_list, self._trd_env, self._acc_id, market))
                except Exception as e:
                    self._log.warning(f"Failed to query market {market} orders: {e}")
            window = history_query_range(start, end, self._clock.timestamp_ns(), market)
            if window is None:
                continue
            try:
                add(
                    await asyncio.to_thread(
                        self._client.get_history_order_list,
                        self._trd_env, self._acc_id, market, None, window[0], window[1], codes,
                    )
                )
            except Exception as e:
                self._log.warning(f"Failed to query market {market} history orders {window}: {e}")
        return orders

    async def _fetch_fills(
        self,
        markets: list[int],
        start: datetime | None = None,
        end: datetime | None = None,
        codes: list[str] | None = None,
    ) -> list[dict]:
        """Today's fills, plus history fills when ``start`` reaches before today.

        Fills the venue cancelled (``status == 1``) are dropped, as on the push
        path, so reconciliation never applies them.
        """
        fills: list[dict] = []
        seen: set[str] = set()

        def add(fill_dicts) -> None:
            for fill_dict in fill_dicts or []:
                if fill_dict.get("status") == FUTU_FILL_STATUS_CANCELLED:
                    self._log.debug(f"Skipping venue-cancelled fill {fill_dict.get('fill_id')}")
                    continue
                key = str(fill_dict.get("fill_id"))
                if key not in seen:
                    seen.add(key)
                    fills.append(fill_dict)

        for market in markets:
            try:
                add(await asyncio.to_thread(self._client.get_order_fill_list, self._trd_env, self._acc_id, market))
            except Exception as e:
                self._log.warning(f"Failed to query market {market} fills: {e}")
            window = history_query_range(start, end, self._clock.timestamp_ns(), market)
            if window is None:
                continue
            try:
                add(
                    await asyncio.to_thread(
                        self._client.get_history_order_fill_list,
                        self._trd_env, self._acc_id, market, window[0], window[1], codes,
                    )
                )
            except Exception as e:
                # OpenD does not serve history fills for every environment
                # (e.g. paper trading); today's fills are still reported.
                self._log.warning(f"Failed to query market {market} history fills {window}: {e}")
        return fills

    @staticmethod
    def _matches_instrument(item: dict, instrument_id: InstrumentId | None) -> bool:
        """Whether an order/fill dict belongs to ``instrument_id`` (NYSE/NASDAQ agnostic)."""
        if instrument_id is None:
            return True
        market, code = instrument_id_to_futu_security(instrument_id)
        if item.get("code") != code:
            return False
        sec_market = item.get("sec_market")
        return sec_market is None or sec_market_to_qot_market(sec_market) == market

    @staticmethod
    def _codes_for(instrument_id: InstrumentId | None) -> list[str] | None:
        return [instrument_id.symbol.value] if instrument_id is not None else None

    def _report_instrument(self, order_dict: dict):
        market = sec_market_to_qot_market(order_dict.get("sec_market"))
        instrument_id = futu_security_to_instrument_id(market, order_dict.get("code", ""))
        return self._instrument_for(instrument_id)

    async def generate_order_status_report(self, command) -> OrderStatusReport | None:
        """Generate an order status report for a specific order.

        Searches today's orders first and falls back to the order history only
        when the cached order was created before the current trading day.
        """
        client_order_id = command.client_order_id
        venue_order_id = command.venue_order_id
        if venue_order_id is None and client_order_id is not None:
            venue_order_id = self._cache.venue_order_id(client_order_id)

        def find(order_dicts: list[dict]) -> dict | None:
            for order_dict in order_dicts:
                if venue_order_id is not None and str(order_dict.get("order_id")) == venue_order_id.value:
                    return order_dict
                if client_order_id is not None and client_order_id_from_remark(order_dict.get("remark")) == client_order_id:
                    return order_dict
            return None

        markets = self._markets_for(command.instrument_id)
        found = find(await self._fetch_orders(markets))
        cached = self._cache.order(client_order_id) if client_order_id is not None else None
        if found is None and cached is not None:
            created = unix_nanos_to_dt(cached.ts_init)
            now_ns = self._clock.timestamp_ns()
            if any(history_query_range(created, None, now_ns, market) is not None for market in markets):
                # Created before today: search the history, starting a day early
                # so no market-local day boundary can hide the order.
                found = find(
                    await self._fetch_orders(
                        markets,
                        start=created - timedelta(days=1),
                        codes=self._codes_for(command.instrument_id),
                        include_today=False,
                    )
                )
        if found is None:
            return None
        self._note_reported_order(found)
        return parse_futu_order_to_report(
            found, self.account_id_str, self._report_instrument(found), self._clock.timestamp_ns(),
        )

    def _note_reported_order(self, order_dict: dict) -> None:
        """A status report reveals an unclearly placed order (in-flight check, reconciliation)."""
        client_order_id = client_order_id_from_remark(order_dict.get("remark"))
        if client_order_id is None or client_order_id not in self._uncertain:
            return
        order = self._cache.order(client_order_id)
        if order is not None and order_dict.get("order_id") is not None:
            self._on_venue_id_learned(
                order, VenueOrderId(str(order_dict["order_id"])), order_dict.get("order_status"), via_report=True,
            )

    async def generate_order_status_reports(self, command) -> list[OrderStatusReport]:
        """Generate order status reports across the authorized markets.

        ``command.start`` before today pulls closed orders from the order
        history as well (reconciliation lookback); ``open_only`` only needs
        today's list, which always contains every working order.
        """
        open_only = bool(getattr(command, "open_only", False))
        instrument_id = command.instrument_id
        start = None if open_only else getattr(command, "start", None)
        orders = await self._fetch_orders(
            self._markets_for(instrument_id),
            start=start,
            end=getattr(command, "end", None),
            codes=self._codes_for(instrument_id),
        )
        ts_init = self._clock.timestamp_ns()
        reports: list[OrderStatusReport] = []
        for order_dict in orders:
            if open_only and order_dict.get("order_status") not in FUTU_ORDER_STATUS_ACTIVE:
                continue
            if not self._matches_instrument(order_dict, instrument_id):
                continue
            self._note_reported_order(order_dict)
            try:
                reports.append(
                    parse_futu_order_to_report(
                        order_dict, self.account_id_str, self._report_instrument(order_dict), ts_init,
                    )
                )
            except Exception as e:
                self._log.warning(f"Failed to parse order {order_dict.get('order_id')}: {e}")
        self._log.info(f"Generated {len(reports)} order status reports")
        return reports

    async def generate_fill_reports(self, command) -> list[FillReport]:
        """Generate fill reports across the authorized markets.

        ``command.start`` before today pulls fills from the fill history as
        well, so fills that happened while the node was offline reconcile.
        """
        venue_order_id = command.venue_order_id
        instrument_id = command.instrument_id
        fills = await self._fetch_fills(
            self._markets_for(instrument_id),
            start=getattr(command, "start", None),
            end=getattr(command, "end", None),
            codes=self._codes_for(instrument_id),
        )
        ts_init = self._clock.timestamp_ns()
        reports: list[FillReport] = []
        for fill_dict in fills:
            try:
                if venue_order_id is not None and str(fill_dict.get("order_id")) != venue_order_id.value:
                    continue
                if not self._matches_instrument(fill_dict, instrument_id):
                    continue
                order_vid = VenueOrderId(str(fill_dict.get("order_id") or 0))
                reports.append(
                    parse_futu_fill_to_report(
                        fill_dict,
                        self.account_id_str,
                        self._report_instrument(fill_dict),
                        client_order_id=self._cache.client_order_id(order_vid),
                        ts_init=ts_init,
                    )
                )
            except Exception as e:
                self._log.warning(f"Failed to parse fill {fill_dict.get('fill_id')}: {e}")

        self._log.info(f"Generated {len(reports)} fill reports")
        return reports

    async def generate_position_status_reports(self, command) -> list[PositionStatusReport]:
        """Generate position status reports across the authorized markets."""
        ts_init = self._clock.timestamp_ns()
        reports: list[PositionStatusReport] = []
        seen: set[str] = set()

        for market in self._markets_for(command.instrument_id):
            try:
                positions = await asyncio.to_thread(
                    self._client.get_position_list, self._trd_env, self._acc_id, market,
                )
            except Exception as e:
                self._log.warning(f"Failed to query market {market} positions: {e}")
                continue
            for pos_dict in positions:
                try:
                    instrument = await self._ensure_instrument(pos_dict)
                    report = parse_futu_position_to_report(pos_dict, self.account_id_str, instrument, ts_init)
                    if command.instrument_id is not None and report.instrument_id != command.instrument_id:
                        continue
                    key = str(report.instrument_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    reports.append(report)
                except Exception as e:
                    self._log.warning(f"Failed to parse position {pos_dict.get('code')}: {e}")

        self._log.info(f"Generated {len(reports)} position reports")
        return reports

    async def _ensure_instrument(self, pos_dict: dict):
        """Load a position's instrument into the cache when missing (needed for reconciliation)."""
        qot_market = sec_market_to_qot_market(pos_dict.get("sec_market"))
        code = pos_dict["code"]
        instrument_id = futu_security_to_instrument_id(qot_market, code)
        instrument = self._instrument_for(instrument_id)
        if instrument is not None:
            return instrument
        try:
            static_info = await asyncio.to_thread(self._client.get_static_info, [(qot_market, code)])
            for info in static_info or []:
                inst = parse_futu_instrument(info, self._clock.timestamp_ns())
                if inst is not None:
                    self._cache.add_instrument(inst)
                    return inst
        except Exception as e:
            self._log.warning(f"Auto-load instrument failed for {instrument_id}: {e}")
        return None
