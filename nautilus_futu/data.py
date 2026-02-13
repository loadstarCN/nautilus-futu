"""Futu live data client for NautilusTrader."""

from __future__ import annotations

import asyncio
from typing import Any

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.data.messages import RequestBars
from nautilus_trader.live.data_client import LiveMarketDataClient
from nautilus_trader.model.data import Bar, BarType, QuoteTick, TradeTick
from nautilus_trader.model.identifiers import ClientId, InstrumentId, Venue

from nautilus_futu.common import instrument_id_to_futu_security
from nautilus_futu.config import FutuDataClientConfig
from nautilus_futu.constants import (
    FUTU_SUB_TYPE_BASIC,
    FUTU_SUB_TYPE_ORDER_BOOK,
    FUTU_SUB_TYPE_TICKER,
    FUTU_VENUE,
)
from nautilus_futu.providers import FutuInstrumentProvider


class FutuLiveDataClient(LiveMarketDataClient):
    """Provides a data client for Futu OpenD.

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
    instrument_provider : FutuInstrumentProvider
        The instrument provider.
    config : FutuDataClientConfig
        The data client configuration.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        client: Any,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
        instrument_provider: FutuInstrumentProvider,
        config: FutuDataClientConfig,
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=ClientId("FUTU"),
            venue=FUTU_VENUE,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=instrument_provider,
        )
        self._client = client
        self._instrument_provider = instrument_provider
        self._config = config
        self._subscribed_quote_ticks: set[InstrumentId] = set()
        self._subscribed_trade_ticks: set[InstrumentId] = set()
        self._subscribed_bars: set[BarType] = set()

    async def _connect(self) -> None:
        """Connect to Futu OpenD."""
        self._log.info("Connecting to Futu OpenD...")
        try:
            await asyncio.to_thread(
                self._client.connect,
                self._config.host,
                self._config.port,
                self._config.client_id,
                self._config.client_ver,
            )
            self._log.info("Connected to Futu OpenD")
        except Exception as e:
            self._log.error(f"Failed to connect to Futu OpenD: {e}")
            raise

    async def _disconnect(self) -> None:
        """Disconnect from Futu OpenD."""
        self._log.info("Disconnecting from Futu OpenD...")
        try:
            await asyncio.to_thread(self._client.disconnect)
            self._log.info("Disconnected from Futu OpenD")
        except Exception as e:
            self._log.error(f"Error disconnecting: {e}")

    async def _subscribe_quote_ticks(self, instrument_id: InstrumentId) -> None:
        """Subscribe to quote tick updates."""
        market, code = instrument_id_to_futu_security(instrument_id)
        try:
            await asyncio.to_thread(
                self._client.subscribe,
                [(market, code)],
                [FUTU_SUB_TYPE_BASIC],
                True,
            )
            self._subscribed_quote_ticks.add(instrument_id)
            self._log.info(f"Subscribed to quote ticks for {instrument_id}")
        except Exception as e:
            self._log.error(f"Failed to subscribe quote ticks for {instrument_id}: {e}")

    async def _subscribe_trade_ticks(self, instrument_id: InstrumentId) -> None:
        """Subscribe to trade tick updates."""
        market, code = instrument_id_to_futu_security(instrument_id)
        try:
            await asyncio.to_thread(
                self._client.subscribe,
                [(market, code)],
                [FUTU_SUB_TYPE_TICKER],
                True,
            )
            self._subscribed_trade_ticks.add(instrument_id)
            self._log.info(f"Subscribed to trade ticks for {instrument_id}")
        except Exception as e:
            self._log.error(f"Failed to subscribe trade ticks for {instrument_id}: {e}")

    async def _subscribe_order_book_deltas(self, instrument_id: InstrumentId) -> None:
        """Subscribe to order book updates."""
        market, code = instrument_id_to_futu_security(instrument_id)
        try:
            await asyncio.to_thread(
                self._client.subscribe,
                [(market, code)],
                [FUTU_SUB_TYPE_ORDER_BOOK],
                True,
            )
            self._log.info(f"Subscribed to order book for {instrument_id}")
        except Exception as e:
            self._log.error(f"Failed to subscribe order book for {instrument_id}: {e}")

    async def _subscribe_bars(self, bar_type: BarType) -> None:
        """Subscribe to bar updates."""
        from nautilus_futu.parsing.market_data import bar_spec_to_futu_sub_type

        instrument_id = bar_type.instrument_id
        market, code = instrument_id_to_futu_security(instrument_id)
        sub_type = bar_spec_to_futu_sub_type(bar_type.spec)

        if sub_type is not None:
            try:
                await asyncio.to_thread(
                    self._client.subscribe,
                    [(market, code)],
                    [sub_type],
                    True,
                )
                self._subscribed_bars.add(bar_type)
                self._log.info(f"Subscribed to bars for {bar_type}")
            except Exception as e:
                self._log.error(f"Failed to subscribe bars for {bar_type}: {e}")
        else:
            self._log.warning(f"Unsupported bar type: {bar_type.spec}")

    async def _unsubscribe_quote_ticks(self, instrument_id: InstrumentId) -> None:
        """Unsubscribe from quote tick updates."""
        market, code = instrument_id_to_futu_security(instrument_id)
        try:
            await asyncio.to_thread(
                self._client.subscribe,
                [(market, code)],
                [FUTU_SUB_TYPE_BASIC],
                False,
            )
            self._subscribed_quote_ticks.discard(instrument_id)
        except Exception as e:
            self._log.error(f"Failed to unsubscribe: {e}")

    async def _unsubscribe_trade_ticks(self, instrument_id: InstrumentId) -> None:
        """Unsubscribe from trade tick updates."""
        market, code = instrument_id_to_futu_security(instrument_id)
        try:
            await asyncio.to_thread(
                self._client.subscribe,
                [(market, code)],
                [FUTU_SUB_TYPE_TICKER],
                False,
            )
            self._subscribed_trade_ticks.discard(instrument_id)
        except Exception as e:
            self._log.error(f"Failed to unsubscribe: {e}")

    async def _request_bars(self, request: RequestBars) -> None:
        """Request historical bars."""
        from nautilus_futu.parsing.market_data import bar_spec_to_futu_kl_type, parse_futu_bars

        bar_type = request.bar_type
        instrument_id = bar_type.instrument_id
        market, code = instrument_id_to_futu_security(instrument_id)
        kl_type = bar_spec_to_futu_kl_type(bar_type.spec)

        if kl_type is None:
            self._log.warning(f"Unsupported bar type for request: {bar_type.spec}")
            return

        start = request.start
        end = request.end
        limit = request.limit or 100

        # Futu expects "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS" format
        begin_str = start.strftime("%Y-%m-%d") if start else ""
        end_str = end.strftime("%Y-%m-%d") if end else ""

        try:
            result = await asyncio.to_thread(
                self._client.get_history_kl,
                market,
                code,
                1,  # rehab_type: 1 = forward adjustment (前复权)
                kl_type,
                begin_str,
                end_str,
                limit,
            )

            bars = parse_futu_bars(result, bar_type)
            self._log.info(f"Received {len(bars)} bars from Futu for {bar_type}")

            self._handle_bars(
                bar_type,
                bars,
                request.id,
                start,
                end,
                request.params,
            )
        except Exception as e:
            self._log.error(f"Failed to request bars: {e}")
