"""Futu live execution client for NautilusTrader."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.execution.reports import (
    FillReport,
    OrderStatusReport,
    PositionStatusReport,
)
from nautilus_trader.live.execution_client import LiveExecutionClient
from nautilus_trader.model.enums import (
    AccountType,
    LiquiditySide,
    OmsType,
    OrderSide,
    OrderStatus,
)
from nautilus_trader.model.identifiers import (
    AccountId,
    ClientId,
    InstrumentId,
    TradeId,
    VenueOrderId,
)
from nautilus_trader.model.objects import AccountBalance, Currency, MarginBalance, Money
from nautilus_trader.model.orders import Order

from nautilus_futu.common import (
    futu_security_to_instrument_id,
    instrument_id_to_futu_security,
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
    FUTU_PROTO_TRD_FILL,
    FUTU_PROTO_TRD_ORDER,
    FUTU_TRD_MARKET_CN,
    FUTU_TRD_MARKET_HKCC,
    FUTU_TRD_MARKET_TO_CURRENCY,
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

# Backwards-compatible aliases
_TRD_MARKET_CURRENCY = FUTU_TRD_MARKET_TO_CURRENCY


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

            # Register push consumers BEFORE asking OpenD to push so nothing is lost
            if self._push_channel_id is None:
                self._push_channel_id = await asyncio.to_thread(self._client.start_push, _EXEC_PUSH_PROTOS)
            await asyncio.to_thread(self._client.sub_acc_push, [self._acc_id])
            self._restored_generation = self._conn.generation
            self._log.info(f"Subscribed to trade push for acc_id={self._acc_id}")

            await self._update_account_state()

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
                if acc["trd_env"] == self._trd_env and acc.get("acc_status", 0) == 0:
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

    async def _update_account_state(self) -> None:
        """Query Futu account funds and generate AccountState."""
        balances, margins = await self._get_account_balances()
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
        """Backwards-compatible wrapper returning balances only."""
        balances, _ = await self._get_account_balances()
        return balances

    async def _get_account_balances(self) -> tuple[list[AccountBalance], list[MarginBalance]]:
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
            self._log.warning(f"Failed to get funds, using zero balance: {e}")
            zero = Money(0, currency)
            return [AccountBalance(total=zero, locked=zero, free=zero)], []

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
            try:
                self._cache.add_venue_order_id(client_order_id, venue_order_id)
            except Exception as e:
                self._log.debug(f"add_venue_order_id({client_order_id}, {venue_order_id}): {e}")
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
            reason = order_data.get("last_err_msg") or order_data.get("remark") or f"Futu status {order_status_int}"

            if nt_status == OrderStatus.ACCEPTED:
                self._on_venue_accepted(order, order_data, venue_order_id, instrument, ts_event)
            elif nt_status in (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED):
                # Fills arrive via 2218; make sure the order is ACCEPTED first
                if order.status in (OrderStatus.INITIALIZED, OrderStatus.SUBMITTED):
                    self.generate_order_accepted(
                        strategy_id=order.strategy_id,
                        instrument_id=instrument_id,
                        client_order_id=order.client_order_id,
                        venue_order_id=venue_order_id,
                        ts_event=ts_event,
                    )
            elif nt_status == OrderStatus.REJECTED:
                if order.status in (OrderStatus.INITIALIZED, OrderStatus.SUBMITTED):
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

    def _on_venue_accepted(self, order: Order, order_data: dict, venue_order_id: VenueOrderId, instrument, ts_event: int) -> None:
        """A SUBMITTED status from Futu: initial acceptance or post-modify acknowledgement."""
        if order.status in (OrderStatus.INITIALIZED, OrderStatus.SUBMITTED):
            self.generate_order_accepted(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                venue_order_id=venue_order_id,
                ts_event=ts_event,
            )
            return

        new_qty = make_qty(order_data.get("qty"), instrument)
        new_price = make_price(order_data["price"], instrument) if order_data.get("price") else None
        new_trigger = make_price(order_data["aux_price"], instrument) if order_data.get("aux_price") else None
        current_price = order.price if order.has_price else None
        current_trigger = order.trigger_price if order.has_trigger_price else None
        changed = (
            order.status == OrderStatus.PENDING_UPDATE
            or new_qty != order.quantity
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
                self._log.debug(f"Fill push for unknown/external order_id={order_id} ignored")
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

            if order.status in (OrderStatus.INITIALIZED, OrderStatus.SUBMITTED):
                self.generate_order_accepted(
                    strategy_id=order.strategy_id,
                    instrument_id=instrument_id,
                    client_order_id=order.client_order_id,
                    venue_order_id=venue_order_id,
                    ts_event=ts_event,
                )

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
        order: Order = command.order
        instrument_id = order.instrument_id
        market, code = instrument_id_to_futu_security(instrument_id)
        sec_market = VENUE_TO_FUTU_TRD_SEC_MARKET.get(instrument_id.venue)
        trd_market = self._trd_market_for(instrument_id)

        self.generate_order_submitted(
            strategy_id=order.strategy_id,
            instrument_id=instrument_id,
            client_order_id=order.client_order_id,
            ts_event=self._clock.timestamp_ns(),
        )

        try:
            params = build_futu_order_params(order, self._config.fill_outside_rth)
        except ValueError as e:
            self._log.error(f"Cannot submit {order.client_order_id}: {e}")
            self.generate_order_rejected(
                strategy_id=order.strategy_id,
                instrument_id=instrument_id,
                client_order_id=order.client_order_id,
                reason=str(e),
                ts_event=self._clock.timestamp_ns(),
            )
            return

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
            self._log.error(f"Failed to submit order {order.client_order_id}: {e}")
            self.generate_order_rejected(
                strategy_id=order.strategy_id,
                instrument_id=instrument_id,
                client_order_id=order.client_order_id,
                reason=str(e),
                ts_event=self._clock.timestamp_ns(),
            )
            return

        order_id = (result or {}).get("order_id")
        if order_id is None:
            self._log.error(f"place_order returned no order_id for {order.client_order_id}: {result}")
            self.generate_order_rejected(
                strategy_id=order.strategy_id,
                instrument_id=instrument_id,
                client_order_id=order.client_order_id,
                reason="Futu returned no order_id",
                ts_event=self._clock.timestamp_ns(),
            )
            return

        venue_order_id = VenueOrderId(str(order_id))
        # Index venue id -> client id so pushes (which may already have arrived
        # and been matched through `remark`) resolve the order.  ACCEPTED is
        # generated from the order push, the single source of truth.
        if self._cache.client_order_id(venue_order_id) is None:
            try:
                self._cache.add_venue_order_id(order.client_order_id, venue_order_id)
            except Exception as e:
                self._log.debug(f"add_venue_order_id after submit: {e}")
        self._log.info(f"Order submitted: {order.client_order_id} -> {venue_order_id}")

    async def _modify_order(self, command: Any) -> None:
        """Modify an existing order."""
        order: Order | None = self._cache.order(command.client_order_id)
        if order is None:
            self._log.error(f"Cannot modify order: {command.client_order_id} not found in cache")
            return
        venue_order_id = command.venue_order_id or order.venue_order_id
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

        quantity = command.quantity or order.quantity
        price = command.price if command.price is not None else (order.price if order.has_price else None)
        trigger_price = command.trigger_price if command.trigger_price is not None else (
            order.trigger_price if order.has_trigger_price else None
        )

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
            self.generate_order_modify_rejected(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                venue_order_id=venue_order_id,
                reason=str(e),
                ts_event=self._clock.timestamp_ns(),
            )
            return

        self.generate_order_updated(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            venue_order_id=venue_order_id,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            ts_event=self._clock.timestamp_ns(),
        )
        self._log.info(f"Order modified: {order.client_order_id} ({venue_order_id})")

    async def _cancel_order(self, command: Any) -> None:
        """Cancel an existing order."""
        order: Order | None = self._cache.order(command.client_order_id)
        if order is None:
            self._log.error(f"Cannot cancel order: {command.client_order_id} not found in cache")
            return
        await self._cancel_cached_order(order, command.venue_order_id or order.venue_order_id)

    async def _cancel_cached_order(self, order: Order, venue_order_id: VenueOrderId | None) -> None:
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

        # OrderPendingCancel is applied by the strategy before the command is sent.
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
            self._log.info(f"Cancel requested: {order.client_order_id} ({venue_order_id})")
        except Exception as e:
            self._log.error(f"Failed to cancel order {order.client_order_id}: {e}")
            self.generate_order_cancel_rejected(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                venue_order_id=venue_order_id,
                reason=str(e),
                ts_event=self._clock.timestamp_ns(),
            )

    async def _cancel_all_orders(self, command: Any) -> None:
        """Cancel the strategy's open orders for the command's instrument (and side)."""
        side = getattr(command, "order_side", OrderSide.NO_ORDER_SIDE)
        open_orders = self._cache.orders_open(
            instrument_id=command.instrument_id,
            strategy_id=command.strategy_id,
            side=side,
        )
        cancelled = 0
        for order in open_orders:
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

    async def _fetch_orders(self, markets: list[int]) -> list[dict]:
        orders: list[dict] = []
        seen: set[str] = set()
        for market in markets:
            try:
                for order_dict in await asyncio.to_thread(
                    self._client.get_order_list, self._trd_env, self._acc_id, market,
                ):
                    key = str(order_dict.get("order_id"))
                    if key not in seen:
                        seen.add(key)
                        orders.append(order_dict)
            except Exception as e:
                self._log.warning(f"Failed to query market {market} orders: {e}")
        return orders

    def _report_instrument(self, order_dict: dict):
        market = sec_market_to_qot_market(order_dict.get("sec_market"))
        instrument_id = futu_security_to_instrument_id(market, order_dict.get("code", ""))
        return self._instrument_for(instrument_id)

    async def generate_order_status_report(self, command) -> OrderStatusReport | None:
        """Generate an order status report for a specific order."""
        client_order_id = command.client_order_id
        venue_order_id = command.venue_order_id
        if venue_order_id is None and client_order_id is not None:
            venue_order_id = self._cache.venue_order_id(client_order_id)

        orders = await self._fetch_orders(self._markets_for(command.instrument_id))
        ts_init = self._clock.timestamp_ns()
        for order_dict in orders:
            matches_venue = venue_order_id is not None and str(order_dict.get("order_id")) == venue_order_id.value
            matches_client = (
                client_order_id is not None
                and client_order_id_from_remark(order_dict.get("remark")) == client_order_id
            )
            if matches_venue or matches_client:
                return parse_futu_order_to_report(
                    order_dict, self.account_id_str, self._report_instrument(order_dict), ts_init,
                )
        return None

    async def generate_order_status_reports(self, command) -> list[OrderStatusReport]:
        """Generate order status reports across the authorized markets."""
        open_only = bool(getattr(command, "open_only", False))
        orders = await self._fetch_orders(self._markets_for(command.instrument_id))
        ts_init = self._clock.timestamp_ns()
        reports: list[OrderStatusReport] = []
        for order_dict in orders:
            if open_only and order_dict.get("order_status") not in FUTU_ORDER_STATUS_ACTIVE:
                continue
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
        """Generate fill reports across the authorized markets."""
        venue_order_id = command.venue_order_id
        ts_init = self._clock.timestamp_ns()
        reports: list[FillReport] = []
        seen: set[str] = set()

        for market in self._markets_for(command.instrument_id):
            try:
                fills = await asyncio.to_thread(
                    self._client.get_order_fill_list, self._trd_env, self._acc_id, market,
                )
            except Exception as e:
                self._log.warning(f"Failed to query market {market} fills: {e}")
                continue
            for fill_dict in fills:
                try:
                    if venue_order_id is not None and str(fill_dict.get("order_id")) != venue_order_id.value:
                        continue
                    fill_id = str(fill_dict.get("fill_id"))
                    if fill_id in seen:
                        continue
                    seen.add(fill_id)
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
