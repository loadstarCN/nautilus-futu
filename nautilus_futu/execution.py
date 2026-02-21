"""Futu live execution client for NautilusTrader."""

from __future__ import annotations

import asyncio
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
from nautilus_trader.model.objects import AccountBalance, Currency, Money, Price, Quantity
from nautilus_trader.model.orders import Order

from nautilus_futu.common import (
    futu_security_to_instrument_id,
    instrument_id_to_futu_security,
)
from nautilus_futu.config import FutuExecClientConfig
from nautilus_futu.constants import (
    FUTU_ORDER_STATUS_FILLED_PART,
    FUTU_ORDER_STATUS_SUBMITTED,
    FUTU_ORDER_STATUS_SUBMITTING,
    FUTU_ORDER_STATUS_WAITING_SUBMIT,
    FUTU_PROTO_TRD_FILL,
    FUTU_PROTO_TRD_ORDER,
    FUTU_TRD_MARKET_CN,
    FUTU_TRD_MARKET_HK,
    FUTU_TRD_MARKET_HKCC,
    FUTU_TRD_MARKET_US,
    FUTU_VENUE,
    VENUE_TO_FUTU_TRD_SEC_MARKET,
)
from nautilus_futu.parsing.orders import (
    futu_order_status_to_nautilus,
    futu_order_type_to_nautilus,
    futu_trd_side_to_nautilus,
    nautilus_order_side_to_futu,
    nautilus_order_type_to_futu,
    parse_futu_fill_to_report,
    parse_futu_order_to_report,
    parse_futu_position_to_report,
    qot_market_to_currency,
    sec_market_to_qot_market,
)


# trd_market -> currency mapping
_TRD_MARKET_CURRENCY: dict[int, str] = {
    FUTU_TRD_MARKET_HK: "HKD",
    FUTU_TRD_MARKET_US: "USD",
    FUTU_TRD_MARKET_CN: "CNY",
    FUTU_TRD_MARKET_HKCC: "HKD",
}

# Futu proto Currency enum: HKD=1, USD=2, CNH=3
_TRD_MARKET_FUTU_CURRENCY: dict[int, int] = {
    FUTU_TRD_MARKET_HK: 1,
    FUTU_TRD_MARKET_US: 2,
    FUTU_TRD_MARKET_CN: 3,
    FUTU_TRD_MARKET_HKCC: 1,
}


def parse_funds_to_balance(funds: dict, currency: Currency) -> AccountBalance:
    """Parse a Futu ``get_funds`` response dict into an ``AccountBalance``.

    Uses ``frozen_cash`` (冻结资金) for locked and computes free = total - frozen.
    The proto field ``available_funds`` is optional and only populated for futures
    accounts, so it is intentionally not used here.

    Args:
        funds: Dict returned by ``PyFutuClient.get_funds()``.
        currency: The ``Currency`` to denominate the balance in.

    Returns:
        An ``AccountBalance`` with correct total/free/locked values.
    """
    total_val = funds.get("total_assets") or 0.0
    frozen_val = funds.get("frozen_cash") or 0.0
    free_val = total_val - frozen_val

    total = Money(total_val, currency)
    locked = Money(frozen_val, currency)
    free = Money(free_val, currency)
    return AccountBalance(total=total, locked=locked, free=free)


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
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=ClientId("FUTU"),
            venue=FUTU_VENUE,
            oms_type=OmsType.NETTING,
            instrument_provider=instrument_provider,
            account_type=AccountType.CASH,
            base_currency=None,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
        )
        self._client = client
        self._config = config
        self._connect_lock = connect_lock or asyncio.Lock()
        self._acc_id = config.acc_id
        self._trd_env = config.trd_env
        self._trd_market = config.trd_market
        self._push_task: asyncio.Task | None = None

    async def _connect(self) -> None:
        """Connect to Futu OpenD for trading."""
        self._log.info("Connecting execution client to Futu OpenD...")
        try:
            async with self._connect_lock:
                # Skip connect if already connected (shared client)
                if not self._client.is_connected():
                    await asyncio.to_thread(
                        self._client.connect,
                        self._config.host,
                        self._config.port,
                        self._config.client_id,
                        self._config.client_ver,
                    )
                    self._log.info("Connected to Futu OpenD")
                else:
                    self._log.info("Reusing existing Futu OpenD connection")

            # Get account list (need_general_sec_account=True to include
            # the securities sub-account of unified margin accounts)
            accounts = await asyncio.to_thread(
                self._client.get_acc_list,
                None,  # trd_category
                True,  # need_general_sec_account
            )

            # Auto-discover acc_id if not specified
            if self._acc_id == 0:
                for acc in accounts:
                    if acc["trd_env"] == self._trd_env and acc.get("acc_status") == 0:
                        if self._trd_market in acc.get("trd_market_auth_list", []):
                            self._acc_id = acc["acc_id"]
                            self._log.info(f"Auto-selected account: {self._acc_id}")
                            break
                if self._acc_id == 0 and accounts:
                    self._acc_id = accounts[0]["acc_id"]
                    self._log.info(f"Fallback account: {self._acc_id}")

            # Save authorized market list for multi-market reconciliation
            for acc in accounts:
                if acc["acc_id"] == self._acc_id:
                    self._trd_market_auth_list = acc.get(
                        "trd_market_auth_list", [self._trd_market],
                    )
                    break
            else:
                self._trd_market_auth_list = [self._trd_market]
            self._log.info(f"Authorized markets: {self._trd_market_auth_list}")

            # Set the framework-level account_id for reconciliation
            self._set_account_id(AccountId(f"FUTU-{self._acc_id}"))

            # Generate initial account state so the account appears in cache
            await self._update_account_state()

            # Register venue-account aliases for each authorized market
            # so Portfolio.account_for_venue(Venue("HKEX")) can find the account
            await self._register_venue_account_aliases()

            # Unlock trade if password provided
            if self._config.unlock_pwd_md5:
                await asyncio.to_thread(
                    self._client.unlock_trade,
                    True,
                    self._config.unlock_pwd_md5,
                )
                self._log.info("Trade unlocked")

            # Subscribe to trade push notifications
            await asyncio.to_thread(
                self._client.sub_acc_push,
                [self._acc_id],
            )
            self._log.info(f"Subscribed to trade push for acc_id={self._acc_id}")

            await asyncio.to_thread(
                self._client.start_push,
                [FUTU_PROTO_TRD_ORDER, FUTU_PROTO_TRD_FILL],
            )
            self._push_task = self.create_task(self._run_push_loop())
            self._log.info("Execution push loop started")

            self._log.info("Execution client connected to Futu OpenD")
        except Exception as e:
            self._log.error(f"Failed to connect execution client: {e}")
            raise

    async def _update_account_state(self) -> None:
        """Query Futu account funds and generate AccountState."""
        balances = await self._get_account_balance()

        if not balances:
            self._log.warning("No account balances obtained")
            return

        self.generate_account_state(
            balances=balances,
            margins=[],
            reported=True,
            ts_event=self._clock.timestamp_ns(),
        )
        for b in balances:
            self._log.info(
                f"Account balance: {b.currency} total={b.total} free={b.free} locked={b.locked}"
            )

    async def _get_account_balance(self) -> list[AccountBalance]:
        """Get account balance using the market's base currency.

        Uses ``frozen_cash`` (冻结资金) for the locked amount and computes
        free = total - frozen.  The proto field ``available_funds`` is optional
        and only populated for futures accounts, so we never rely on it.

        For unified (multi-currency) accounts the previous implementation
        looped over all supported currencies, but ``get_funds(currency=X)``
        merely converts the **same** account total into currency X — it does
        NOT return per-currency holdings.  We now query once in the market's
        base currency to avoid duplicated rows.
        """
        currency_str = _TRD_MARKET_CURRENCY.get(self._trd_market, "USD")
        currency = Currency.from_str(currency_str)
        futu_currency = _TRD_MARKET_FUTU_CURRENCY.get(self._trd_market)

        try:
            funds = await asyncio.to_thread(
                self._client.get_funds,
                self._trd_env,
                self._acc_id,
                self._trd_market,
                futu_currency,
            )
            balance = parse_funds_to_balance(funds, currency)
        except Exception as e:
            self._log.warning(f"Failed to get funds, using zero balance: {e}")
            zero = Money(0, currency)
            balance = AccountBalance(total=zero, locked=zero, free=zero)

        return [balance]

    async def _register_venue_account_aliases(self) -> None:
        """Register account aliases for each authorized market venue.

        This allows ``Portfolio.account_for_venue(Venue("HKEX"))`` (or NYSE,
        SSE, etc.) to find the Futu account, preventing PnL init timeouts.
        """
        import time

        from nautilus_trader.accounting.accounts.cash import CashAccount
        from nautilus_trader.core.uuid import UUID4
        from nautilus_trader.model.events.account import AccountState

        from nautilus_futu.constants import FUTU_TRD_MARKET_TO_VENUE

        for trd_market in self._trd_market_auth_list:
            venue = FUTU_TRD_MARKET_TO_VENUE.get(trd_market)
            if venue is None:
                continue
            venue_str = str(venue)
            if venue_str == "FUTU":
                continue

            alias_id = AccountId(f"{venue_str}-{self._acc_id}")
            if self._cache.account(alias_id) is not None:
                continue

            try:
                usd = Currency.from_str("USD")
                zero = Money(0, usd)
                event = AccountState(
                    account_id=alias_id,
                    account_type=AccountType.CASH,
                    base_currency=None,
                    reported=False,
                    balances=[AccountBalance(total=zero, locked=zero, free=zero)],
                    margins=[],
                    info={"alias_of": f"FUTU-{self._acc_id}"},
                    event_id=UUID4(),
                    ts_event=time.time_ns(),
                    ts_init=time.time_ns(),
                )
                account = CashAccount(event)
                self._cache.add_account(account)
                self._log.info(f"Registered venue-account alias: {venue_str} -> {alias_id}")
            except Exception as e:
                self._log.warning(f"Failed to register venue-account alias ({venue_str}): {e}")

    async def _disconnect(self) -> None:
        """Disconnect from Futu OpenD."""
        self._log.info("Disconnecting execution client...")
        if self._push_task is not None:
            self._push_task.cancel()
            try:
                await self._push_task
            except asyncio.CancelledError:
                pass
            self._push_task = None
        try:
            await asyncio.to_thread(self._client.disconnect)
        except Exception as e:
            self._log.error(f"Error disconnecting execution client: {e}")

    async def _run_push_loop(self) -> None:
        """Background loop polling for trade push messages."""
        self._log.debug("Execution push loop running")
        consecutive_errors = 0
        try:
            while True:
                try:
                    msg = await asyncio.to_thread(self._client.poll_push, 100)
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    self._log.warning(
                        f"Exec push poll error ({consecutive_errors}): {e}"
                    )
                    if consecutive_errors >= 5 and self._config.reconnect:
                        await self._reconnect()
                        consecutive_errors = 0
                    else:
                        await asyncio.sleep(0.5)
                    continue

                if msg is None:
                    await asyncio.sleep(0)
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
        """Disconnect and reconnect to Futu OpenD."""
        self._log.warning(
            f"Reconnecting in {self._config.reconnect_interval}s..."
        )
        try:
            await asyncio.to_thread(self._client.disconnect)
        except Exception as e:
            self._log.warning(f"Error during disconnect before reconnect: {e}")
        await asyncio.sleep(self._config.reconnect_interval)
        try:
            await asyncio.to_thread(
                self._client.connect,
                self._config.host,
                self._config.port,
                self._config.client_id,
                self._config.client_ver,
            )
            # Re-subscribe trade push
            await asyncio.to_thread(
                self._client.sub_acc_push,
                [self._acc_id],
            )
            await asyncio.to_thread(
                self._client.start_push,
                [FUTU_PROTO_TRD_ORDER, FUTU_PROTO_TRD_FILL],
            )
            self._log.info("Execution client reconnected to Futu OpenD")
        except Exception as e:
            self._log.error(f"Execution reconnection failed: {e}")

    def _handle_push_order(self, data: dict) -> None:
        """Handle order update push (proto 2208)."""
        order_data = data["order"]
        order_status_int = order_data["order_status"]
        nt_status = futu_order_status_to_nautilus(order_status_int)
        venue_order_id = VenueOrderId(str(order_data["order_id"]))

        # Try to find the matching client order in cache
        order = self._cache.order(venue_order_id=venue_order_id)
        if order is None:
            self._log.debug(f"No cached order for venue_order_id={venue_order_id}")
            return

        client_order_id = order.client_order_id
        account_id = AccountId(f"FUTU-{self._acc_id}")
        sec_market = order_data.get("sec_market")
        market = sec_market_to_qot_market(sec_market)
        instrument_id = futu_security_to_instrument_id(market, order_data["code"])
        ts_event = int((order_data.get("update_timestamp") or 0) * 1e9)

        if nt_status == OrderStatus.ACCEPTED:
            self.generate_order_accepted(
                strategy_id=order.strategy_id,
                instrument_id=instrument_id,
                client_order_id=client_order_id,
                venue_order_id=venue_order_id,
                ts_event=ts_event,
            )
        elif nt_status == OrderStatus.CANCELED:
            self.generate_order_canceled(
                strategy_id=order.strategy_id,
                instrument_id=instrument_id,
                client_order_id=client_order_id,
                venue_order_id=venue_order_id,
                ts_event=ts_event,
            )
        elif nt_status == OrderStatus.REJECTED:
            reason = order_data.get("remark") or "Unknown"
            self.generate_order_rejected(
                strategy_id=order.strategy_id,
                instrument_id=instrument_id,
                client_order_id=client_order_id,
                reason=str(reason),
                ts_event=ts_event,
            )
        elif nt_status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            # Fill events are handled by _handle_push_fill (proto 2218) which
            # has the actual per-fill qty/price.  The order update only carries
            # cumulative fill_qty/fill_avg_price, so we skip fill generation
            # here to avoid duplicates and incorrect incremental values.
            pass

    def _handle_push_fill(self, data: dict) -> None:
        """Handle fill update push (proto 2218)."""
        fill_data = data["fill"]
        order_id = fill_data.get("order_id")
        if order_id is None:
            return

        venue_order_id = VenueOrderId(str(order_id))
        order = self._cache.order(venue_order_id=venue_order_id)
        if order is None:
            self._log.debug(f"No cached order for fill venue_order_id={venue_order_id}")
            return

        client_order_id = order.client_order_id
        sec_market = fill_data.get("sec_market")
        market = sec_market_to_qot_market(sec_market)
        instrument_id = futu_security_to_instrument_id(market, fill_data["code"])
        ts_event = int((fill_data.get("create_timestamp") or 0) * 1e9)
        currency = qot_market_to_currency(market)

        self.generate_order_filled(
            strategy_id=order.strategy_id,
            instrument_id=instrument_id,
            client_order_id=client_order_id,
            venue_order_id=venue_order_id,
            venue_position_id=None,
            trade_id=TradeId(str(fill_data["fill_id"])),
            order_side=futu_trd_side_to_nautilus(fill_data["trd_side"]),
            order_type=order.order_type,
            last_qty=Quantity.from_str(str(fill_data["qty"])),
            last_px=Price.from_str(str(fill_data["price"])),
            quote_currency=currency,
            commission=Money(0, currency),
            liquidity_side=LiquiditySide.NO_LIQUIDITY_SIDE,
            ts_event=ts_event,
        )

    async def _submit_order(self, command: Any) -> None:
        """Submit a new order."""
        order: Order = command.order
        instrument_id = order.instrument_id
        market, code = instrument_id_to_futu_security(instrument_id)

        trd_side = nautilus_order_side_to_futu(order.side)
        order_type = nautilus_order_type_to_futu(order.order_type)

        price = float(order.price) if hasattr(order, "price") and order.price is not None else None
        qty = float(order.quantity)
        sec_market = VENUE_TO_FUTU_TRD_SEC_MARKET.get(instrument_id.venue)

        try:
            self.generate_order_submitted(
                strategy_id=order.strategy_id,
                instrument_id=instrument_id,
                client_order_id=order.client_order_id,
                ts_event=self._clock.timestamp_ns(),
            )

            result = await asyncio.to_thread(
                self._client.place_order,
                self._trd_env,
                self._acc_id,
                self._trd_market,
                trd_side,
                order_type,
                code,
                qty,
                price,
                sec_market,
            )

            if result and "order_id" in result:
                venue_order_id = VenueOrderId(str(result["order_id"]))
                self.generate_order_accepted(
                    strategy_id=order.strategy_id,
                    instrument_id=instrument_id,
                    client_order_id=order.client_order_id,
                    venue_order_id=venue_order_id,
                    ts_event=self._clock.timestamp_ns(),
                )
                self._log.info(
                    f"Order submitted: {order.client_order_id} -> {venue_order_id}"
                )
        except Exception as e:
            self._log.error(f"Failed to submit order: {e}")
            self.generate_order_rejected(
                strategy_id=order.strategy_id,
                instrument_id=instrument_id,
                client_order_id=order.client_order_id,
                reason=str(e),
                ts_event=self._clock.timestamp_ns(),
            )

    async def _modify_order(self, command: Any) -> None:
        """Modify an existing order."""
        order = command.order
        venue_order_id = order.venue_order_id

        if venue_order_id is None:
            self._log.error("Cannot modify order without venue_order_id")
            return

        price = float(command.price) if command.price is not None else None
        qty = float(command.quantity) if command.quantity is not None else None

        try:
            await asyncio.to_thread(
                self._client.modify_order,
                self._trd_env,
                self._acc_id,
                self._trd_market,
                int(venue_order_id.value),
                1,  # ModifyOrderOp_Normal
                qty,
                price,
            )
            self._log.info(f"Order modified: {venue_order_id}")
        except Exception as e:
            self._log.error(f"Failed to modify order: {e}")

    async def _cancel_order(self, command: Any) -> None:
        """Cancel an existing order."""
        order = command.order
        venue_order_id = order.venue_order_id

        if venue_order_id is None:
            self._log.error("Cannot cancel order without venue_order_id")
            return

        try:
            await asyncio.to_thread(
                self._client.modify_order,
                self._trd_env,
                self._acc_id,
                self._trd_market,
                int(venue_order_id.value),
                2,  # ModifyOrderOp_Cancel
                None,
                None,
            )
            self._log.info(f"Order cancelled: {venue_order_id}")
        except Exception as e:
            self._log.error(f"Failed to cancel order: {e}")

    async def generate_order_status_report(
        self,
        command,
    ) -> OrderStatusReport | None:
        """Generate an order status report for a specific order."""
        instrument_id = command.instrument_id
        client_order_id = command.client_order_id
        venue_order_id = command.venue_order_id
        try:
            orders = await asyncio.to_thread(
                self._client.get_order_list,
                self._trd_env,
                self._acc_id,
                self._trd_market,
            )
        except Exception as e:
            self._log.error(f"Failed to get order list: {e}")
            return None

        account_id = AccountId(f"FUTU-{self._acc_id}")

        for order_dict in orders:
            if venue_order_id is not None:
                if str(order_dict["order_id"]) == venue_order_id.value:
                    return parse_futu_order_to_report(order_dict, account_id)
            # If no venue_order_id match found by remark/client_order_id,
            # we cannot match by client_order_id since Futu doesn't store it directly

        return None

    async def generate_order_status_reports(
        self,
        command,
    ) -> list[OrderStatusReport]:
        """Generate order status reports across all authorized markets."""
        instrument_id = command.instrument_id
        markets = getattr(self, "_trd_market_auth_list", [self._trd_market])
        account_id = AccountId(f"FUTU-{self._acc_id}")
        reports = []
        seen_ids: set[str] = set()

        for market in markets:
            try:
                orders = await asyncio.to_thread(
                    self._client.get_order_list,
                    self._trd_env,
                    self._acc_id,
                    market,
                )
                for order_dict in orders:
                    try:
                        order_id_str = str(order_dict.get("order_id"))
                        if order_id_str in seen_ids:
                            continue
                        seen_ids.add(order_id_str)
                        report = parse_futu_order_to_report(order_dict, account_id)
                        reports.append(report)
                    except Exception as e:
                        self._log.warning(f"Failed to parse order {order_dict.get('order_id')}: {e}")
            except Exception as e:
                self._log.warning(f"Failed to query market {market} orders: {e}")

        self._log.info(f"Generated {len(reports)} order status reports (multi-market)")
        return reports

    async def generate_fill_reports(
        self,
        command,
    ) -> list[FillReport]:
        """Generate fill reports across all authorized markets."""
        instrument_id = command.instrument_id
        venue_order_id = command.venue_order_id
        markets = getattr(self, "_trd_market_auth_list", [self._trd_market])
        account_id = AccountId(f"FUTU-{self._acc_id}")
        reports = []
        seen_ids: set[str] = set()

        for market in markets:
            try:
                fills = await asyncio.to_thread(
                    self._client.get_order_fill_list,
                    self._trd_env,
                    self._acc_id,
                    market,
                )
                for fill_dict in fills:
                    try:
                        if venue_order_id is not None:
                            fill_order_id = fill_dict.get("order_id")
                            if fill_order_id is not None and str(fill_order_id) != venue_order_id.value:
                                continue
                        fill_id_str = str(fill_dict.get("fill_id"))
                        if fill_id_str in seen_ids:
                            continue
                        seen_ids.add(fill_id_str)
                        report = parse_futu_fill_to_report(fill_dict, account_id)
                        reports.append(report)
                    except Exception as e:
                        self._log.warning(f"Failed to parse fill {fill_dict.get('fill_id')}: {e}")
            except Exception as e:
                self._log.warning(f"Failed to query market {market} fills: {e}")

        self._log.info(f"Generated {len(reports)} fill reports (multi-market)")
        return reports

    async def generate_position_status_reports(
        self,
        command,
    ) -> list[PositionStatusReport]:
        """Generate position status reports across all authorized markets."""
        instrument_id = command.instrument_id
        from nautilus_futu.parsing.instruments import parse_futu_instrument

        markets = getattr(self, "_trd_market_auth_list", [self._trd_market])
        account_id = AccountId(f"FUTU-{self._acc_id}")
        reports = []
        seen_ids: set[str] = set()

        for market in markets:
            try:
                positions = await asyncio.to_thread(
                    self._client.get_position_list,
                    self._trd_env,
                    self._acc_id,
                    market,
                )
                for pos_dict in positions:
                    try:
                        report = parse_futu_position_to_report(pos_dict, account_id)
                        inst_id_str = str(report.instrument_id)
                        if inst_id_str in seen_ids:
                            continue
                        seen_ids.add(inst_id_str)
                        reports.append(report)

                        # Auto-load missing instrument into cache for reconciliation
                        if self._cache.instrument(report.instrument_id) is None:
                            code = pos_dict["code"]
                            sec_market = pos_dict.get("sec_market")
                            qot_market = sec_market_to_qot_market(sec_market)
                            try:
                                static_info = await asyncio.to_thread(
                                    self._client.get_static_info, [(qot_market, code)],
                                )
                                if static_info:
                                    for info in static_info:
                                        inst = parse_futu_instrument(info)
                                        if inst is not None:
                                            self._cache.add_instrument(inst)
                            except Exception as e:
                                self._log.warning(f"Auto-load instrument failed: {e}")
                    except Exception as e:
                        self._log.warning(f"Failed to parse position {pos_dict.get('code')}: {e}")
            except Exception as e:
                self._log.warning(f"Failed to query market {market} positions: {e}")

        self._log.info(f"Generated {len(reports)} position reports (multi-market)")
        return reports

    async def _cancel_all_orders(self, command: Any) -> None:
        """Cancel all active orders."""
        try:
            orders = await asyncio.to_thread(
                self._client.get_order_list,
                self._trd_env,
                self._acc_id,
                self._trd_market,
            )
        except Exception as e:
            self._log.error(f"Failed to get order list for cancel all: {e}")
            return

        active_statuses = {
            FUTU_ORDER_STATUS_WAITING_SUBMIT,
            FUTU_ORDER_STATUS_SUBMITTING,
            FUTU_ORDER_STATUS_SUBMITTED,
            FUTU_ORDER_STATUS_FILLED_PART,
        }
        cancelled = 0
        for order_dict in orders:
            if order_dict["order_status"] in active_statuses:
                try:
                    await asyncio.to_thread(
                        self._client.modify_order,
                        self._trd_env,
                        self._acc_id,
                        self._trd_market,
                        order_dict["order_id"],
                        2,  # ModifyOrderOp_Cancel
                        None,
                        None,
                    )
                    cancelled += 1
                except Exception as e:
                    self._log.warning(
                        f"Failed to cancel order {order_dict['order_id']}: {e}"
                    )

        self._log.info(f"Cancelled {cancelled} orders")
