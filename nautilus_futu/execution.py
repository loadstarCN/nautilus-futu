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
from nautilus_trader.model.objects import Currency, Money, Price, Quantity
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

            # Get account list if acc_id not specified
            if self._acc_id == 0:
                accounts = await asyncio.to_thread(self._client.get_acc_list)
                if accounts:
                    self._acc_id = accounts[0]["acc_id"]
                    self._log.info(f"Using account ID: {self._acc_id}")

            # Set the framework-level account_id for reconciliation
            self._set_account_id(AccountId(f"FUTU-{self._acc_id}"))

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
            fill_qty = order_data.get("fill_qty") or 0.0
            fill_avg_price = order_data.get("fill_avg_price") or 0.0
            if fill_qty > 0 and fill_avg_price > 0:
                # Determine the last fill qty from order data
                currency = qot_market_to_currency(market)
                self.generate_order_filled(
                    strategy_id=order.strategy_id,
                    instrument_id=instrument_id,
                    client_order_id=client_order_id,
                    venue_order_id=venue_order_id,
                    venue_position_id=None,
                    trade_id=TradeId(f"{order_data['order_id']}-{ts_event}"),
                    order_side=futu_trd_side_to_nautilus(order_data["trd_side"]),
                    order_type=futu_order_type_to_nautilus(order_data["order_type"]),
                    last_qty=Quantity.from_str(str(fill_qty)),
                    last_px=Price.from_str(str(fill_avg_price)),
                    quote_currency=currency,
                    commission=Money(0, currency),
                    liquidity_side=LiquiditySide.NO_LIQUIDITY_SIDE,
                    ts_event=ts_event,
                )

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
        instrument_id: InstrumentId,
        client_order_id: ClientOrderId | None = None,
        venue_order_id: VenueOrderId | None = None,
    ) -> OrderStatusReport | None:
        """Generate an order status report for a specific order."""
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
        instrument_id: InstrumentId | None = None,
        start: Any = None,
        end: Any = None,
    ) -> list[OrderStatusReport]:
        """Generate order status reports for all active orders."""
        try:
            orders = await asyncio.to_thread(
                self._client.get_order_list,
                self._trd_env,
                self._acc_id,
                self._trd_market,
            )
        except Exception as e:
            self._log.error(f"Failed to get order list: {e}")
            return []

        account_id = AccountId(f"FUTU-{self._acc_id}")
        reports = []
        for order_dict in orders:
            try:
                report = parse_futu_order_to_report(order_dict, account_id)
                reports.append(report)
            except Exception as e:
                self._log.warning(f"Failed to parse order {order_dict.get('order_id')}: {e}")

        self._log.info(f"Generated {len(reports)} order status reports")
        return reports

    async def generate_fill_reports(
        self,
        instrument_id: InstrumentId | None = None,
        venue_order_id: VenueOrderId | None = None,
        start: Any = None,
        end: Any = None,
    ) -> list[FillReport]:
        """Generate fill reports."""
        try:
            fills = await asyncio.to_thread(
                self._client.get_order_fill_list,
                self._trd_env,
                self._acc_id,
                self._trd_market,
            )
        except Exception as e:
            self._log.error(f"Failed to get fill list: {e}")
            return []

        account_id = AccountId(f"FUTU-{self._acc_id}")
        reports = []
        for fill_dict in fills:
            try:
                # Filter by venue_order_id if specified
                if venue_order_id is not None:
                    fill_order_id = fill_dict.get("order_id")
                    if fill_order_id is not None and str(fill_order_id) != venue_order_id.value:
                        continue
                report = parse_futu_fill_to_report(fill_dict, account_id)
                reports.append(report)
            except Exception as e:
                self._log.warning(f"Failed to parse fill {fill_dict.get('fill_id')}: {e}")

        self._log.info(f"Generated {len(reports)} fill reports")
        return reports

    async def generate_position_status_reports(
        self,
        instrument_id: InstrumentId | None = None,
        start: Any = None,
        end: Any = None,
    ) -> list[PositionStatusReport]:
        """Generate position status reports."""
        try:
            positions = await asyncio.to_thread(
                self._client.get_position_list,
                self._trd_env,
                self._acc_id,
                self._trd_market,
            )
        except Exception as e:
            self._log.error(f"Failed to get position list: {e}")
            return []

        account_id = AccountId(f"FUTU-{self._acc_id}")
        reports = []
        for pos_dict in positions:
            try:
                report = parse_futu_position_to_report(pos_dict, account_id)
                reports.append(report)
            except Exception as e:
                self._log.warning(f"Failed to parse position {pos_dict.get('code')}: {e}")

        self._log.info(f"Generated {len(reports)} position status reports")
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
