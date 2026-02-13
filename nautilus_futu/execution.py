"""Futu live execution client for NautilusTrader."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.clock import LiveClock
from nautilus_trader.common.logging import Logger
from nautilus_trader.execution.reports import (
    FillReport,
    OrderStatusReport,
    PositionStatusReport,
)
from nautilus_trader.live.execution_client import LiveExecutionClient
from nautilus_trader.model.enums import (
    AccountType,
    OmsType,
    OrderSide,
    OrderType,
    TimeInForce,
)
from nautilus_trader.model.identifiers import (
    AccountId,
    ClientId,
    ClientOrderId,
    InstrumentId,
    VenueOrderId,
)
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.orders import Order

from nautilus_futu.common import instrument_id_to_futu_security
from nautilus_futu.config import FutuExecClientConfig
from nautilus_futu.constants import FUTU_VENUE
from nautilus_futu.parsing.orders import (
    nautilus_order_side_to_futu,
    nautilus_order_type_to_futu,
)


class FutuLiveExecutionClient(LiveExecutionClient):
    """Provides an execution client for Futu OpenD.

    Parameters
    ----------
    loop : asyncio.AbstractEventLoop
        The event loop for the client.
    client : Any
        The Futu Rust client instance.
    cache : Cache
        The cache for the client.
    clock : LiveClock
        The clock for the client.
    logger : Logger
        The logger for the client.
    config : FutuExecClientConfig
        The execution client configuration.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        client: Any,
        cache: Cache,
        clock: LiveClock,
        logger: Logger,
        config: FutuExecClientConfig,
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=ClientId("FUTU"),
            venue=FUTU_VENUE,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            base_currency=None,
            cache=cache,
            clock=clock,
            logger=logger,
            config=config,
        )
        self._client = client
        self._config = config
        self._acc_id = config.acc_id
        self._trd_env = config.trd_env
        self._trd_market = config.trd_market

    async def _connect(self) -> None:
        """Connect to Futu OpenD for trading."""
        self._log.info("Connecting execution client to Futu OpenD...")
        try:
            await asyncio.to_thread(
                self._client.connect,
                self._config.host,
                self._config.port,
                self._config.client_id,
                self._config.client_ver,
            )

            # Get account list if acc_id not specified
            if self._acc_id == 0:
                accounts = await asyncio.to_thread(self._client.get_acc_list)
                if accounts:
                    self._acc_id = accounts[0]["acc_id"]
                    self._log.info(f"Using account ID: {self._acc_id}")

            # Unlock trade if password provided and in real environment
            if self._config.unlock_pwd_md5 and self._trd_env == 1:
                await asyncio.to_thread(
                    self._client.unlock_trade,
                    True,
                    self._config.unlock_pwd_md5,
                )
                self._log.info("Trade unlocked")

            self._log.info("Execution client connected to Futu OpenD")
        except Exception as e:
            self._log.error(f"Failed to connect execution client: {e}")
            raise

    async def _disconnect(self) -> None:
        """Disconnect from Futu OpenD."""
        self._log.info("Disconnecting execution client...")
        try:
            await asyncio.to_thread(self._client.disconnect)
        except Exception as e:
            self._log.error(f"Error disconnecting execution client: {e}")

    async def _submit_order(self, command: Any) -> None:
        """Submit a new order."""
        order: Order = command.order
        instrument_id = order.instrument_id
        market, code = instrument_id_to_futu_security(instrument_id)

        trd_side = nautilus_order_side_to_futu(order.side)
        order_type = nautilus_order_type_to_futu(order.order_type)

        price = float(order.price) if hasattr(order, "price") and order.price is not None else None
        qty = float(order.quantity)

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
            )

            if result and "order_id" in result:
                venue_order_id = VenueOrderId(str(result["order_id"]))
                self._log.info(
                    f"Order submitted: {order.client_order_id} -> {venue_order_id}"
                )
        except Exception as e:
            self._log.error(f"Failed to submit order: {e}")

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
        """Generate an order status report."""
        return None  # TODO: Implement

    async def generate_fill_reports(
        self,
        instrument_id: InstrumentId | None = None,
        venue_order_id: VenueOrderId | None = None,
        start: Any = None,
        end: Any = None,
    ) -> list[FillReport]:
        """Generate fill reports."""
        return []  # TODO: Implement

    async def generate_position_status_reports(
        self,
        instrument_id: InstrumentId | None = None,
        start: Any = None,
        end: Any = None,
    ) -> list[PositionStatusReport]:
        """Generate position status reports."""
        return []  # TODO: Implement
