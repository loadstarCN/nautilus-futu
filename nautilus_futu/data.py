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

from nautilus_futu.common import (
    futu_security_to_instrument_id,
    instrument_id_to_futu_security,
)
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
        self._push_task: asyncio.Task | None = None

    async def _connect(self) -> None:
        """Connect to Futu OpenD."""
        self._log.info("Connecting to Futu OpenD...")
        try:
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

            # Register push handlers and start push loop
            # 3005=BasicQot, 3011=Ticker, 3013=OrderBook, 3007=KL
            await asyncio.to_thread(
                self._client.start_push,
                [3005, 3011, 3013, 3007],
            )
            self._push_task = self.create_task(self._run_push_loop())
            self._log.info("Push loop started")
        except Exception as e:
            self._log.error(f"Failed to connect to Futu OpenD: {e}")
            raise

    async def _disconnect(self) -> None:
        """Disconnect from Futu OpenD."""
        self._log.info("Disconnecting from Futu OpenD...")
        if self._push_task is not None:
            self._push_task.cancel()
            self._push_task = None
        try:
            await asyncio.to_thread(self._client.disconnect)
            self._log.info("Disconnected from Futu OpenD")
        except Exception as e:
            self._log.error(f"Error disconnecting: {e}")

    async def _run_push_loop(self) -> None:
        """Background loop that polls for push messages and dispatches them."""
        self._log.debug("Push loop running")
        consecutive_errors = 0
        try:
            while True:
                try:
                    msg = await asyncio.to_thread(self._client.poll_push, 100)
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    self._log.warning(
                        f"Push poll error ({consecutive_errors}): {e}"
                    )
                    if consecutive_errors >= 5 and self._config.reconnect:
                        await self._reconnect()
                        consecutive_errors = 0
                    else:
                        await asyncio.sleep(0.5)
                    continue

                if msg is None:
                    await asyncio.sleep(0)  # yield to event loop
                    continue

                proto_id = msg["proto_id"]
                data = msg["data"]

                try:
                    if proto_id == 3005:
                        self._handle_push_basic_qot(data)
                    elif proto_id == 3011:
                        self._handle_push_ticker(data)
                    elif proto_id == 3013:
                        self._handle_push_order_book(data)
                    elif proto_id == 3007:
                        self._handle_push_kl(data)
                except Exception as e:
                    self._log.error(f"Error handling push proto_id={proto_id}: {e}")
        except asyncio.CancelledError:
            self._log.debug("Push loop cancelled")

    async def _reconnect(self) -> None:
        """Disconnect and reconnect to Futu OpenD."""
        self._log.warning(
            f"Reconnecting in {self._config.reconnect_interval}s..."
        )
        try:
            await asyncio.to_thread(self._client.disconnect)
        except Exception:
            pass
        await asyncio.sleep(self._config.reconnect_interval)
        try:
            await asyncio.to_thread(
                self._client.connect,
                self._config.host,
                self._config.port,
                self._config.client_id,
                self._config.client_ver,
            )
            await asyncio.to_thread(
                self._client.start_push,
                [3005, 3011, 3013, 3007],
            )
            self._log.info("Reconnected to Futu OpenD")
        except Exception as e:
            self._log.error(f"Reconnection failed: {e}")

    def _handle_push_basic_qot(self, data_list: list) -> None:
        """Handle basic quote push (proto 3005)."""
        from nautilus_futu.parsing.market_data import parse_futu_quote_tick

        ts_init = self._clock.timestamp_ns()
        for data in data_list:
            market = data["market"]
            code = data["code"]
            instrument_id = futu_security_to_instrument_id(market, code)
            if instrument_id in self._subscribed_quote_ticks:
                tick = parse_futu_quote_tick(data, instrument_id, ts_init)
                self._handle_data(tick)

    def _handle_push_ticker(self, data: dict) -> None:
        """Handle ticker push (proto 3011)."""
        from nautilus_futu.parsing.market_data import parse_futu_trade_tick

        market = data["market"]
        code = data["code"]
        instrument_id = futu_security_to_instrument_id(market, code)
        if instrument_id not in self._subscribed_trade_ticks:
            return

        ts_init = self._clock.timestamp_ns()
        for ticker in data.get("tickers", []):
            tick = parse_futu_trade_tick(ticker, instrument_id, ts_init)
            self._handle_data(tick)

    def _handle_push_order_book(self, data: dict) -> None:
        """Handle order book push (proto 3013)."""
        from nautilus_futu.parsing.market_data import parse_push_order_book

        market = data["market"]
        code = data["code"]
        instrument_id = futu_security_to_instrument_id(market, code)

        ts_init = self._clock.timestamp_ns()
        deltas = parse_push_order_book(data, instrument_id, ts_init)
        self._handle_data(deltas)

    def _handle_push_kl(self, data: dict) -> None:
        """Handle K-line push (proto 3007)."""
        from nautilus_futu.parsing.market_data import (
            futu_kl_type_to_bar_spec,
            parse_futu_bars,
        )

        market = data["market"]
        code = data["code"]
        kl_type = data["kl_type"]
        instrument_id = futu_security_to_instrument_id(market, code)

        bar_spec = futu_kl_type_to_bar_spec(kl_type)
        if bar_spec is None:
            self._log.warning(f"Unknown KL type {kl_type} in push")
            return

        bar_type = BarType(instrument_id, bar_spec)
        if bar_type not in self._subscribed_bars:
            return

        bars = parse_futu_bars(data.get("kl_list", []), bar_type)
        for bar in bars:
            self._handle_data(bar)

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

    async def _unsubscribe_order_book_deltas(self, instrument_id: InstrumentId) -> None:
        """Unsubscribe from order book updates."""
        market, code = instrument_id_to_futu_security(instrument_id)
        try:
            await asyncio.to_thread(
                self._client.subscribe,
                [(market, code)],
                [FUTU_SUB_TYPE_ORDER_BOOK],
                False,
            )
        except Exception as e:
            self._log.error(f"Failed to unsubscribe order book: {e}")

    async def _unsubscribe_bars(self, bar_type: BarType) -> None:
        """Unsubscribe from bar updates."""
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
                    False,
                )
                self._subscribed_bars.discard(bar_type)
            except Exception as e:
                self._log.error(f"Failed to unsubscribe bars for {bar_type}: {e}")

    async def _request_instrument(
        self, instrument_id: InstrumentId, correlation_id: Any, params: dict | None = None,
    ) -> None:
        """Request a single instrument definition."""
        from nautilus_futu.parsing.instruments import parse_futu_instrument

        market, code = instrument_id_to_futu_security(instrument_id)
        try:
            static_info_list = await asyncio.to_thread(
                self._client.get_static_info, [(market, code)]
            )
            if static_info_list:
                instrument = parse_futu_instrument(static_info_list[0])
                if instrument is not None:
                    self._handle_instrument(instrument, correlation_id)
        except Exception as e:
            self._log.error(f"Failed to request instrument {instrument_id}: {e}")

    async def _request_quote_ticks(
        self,
        instrument_id: InstrumentId,
        limit: int,
        correlation_id: Any,
        start: Any = None,
        end: Any = None,
        params: dict | None = None,
    ) -> None:
        """Request quote ticks (basic quote snapshot)."""
        from nautilus_futu.parsing.market_data import parse_futu_quote_tick

        market, code = instrument_id_to_futu_security(instrument_id)
        try:
            result = await asyncio.to_thread(
                self._client.get_basic_qot, [(market, code)]
            )
            ts_init = self._clock.timestamp_ns()
            ticks = []
            for data in result:
                tick = parse_futu_quote_tick(data, instrument_id, ts_init)
                ticks.append(tick)
            self._handle_quote_ticks(instrument_id, ticks, correlation_id)
        except Exception as e:
            self._log.error(f"Failed to request quote ticks for {instrument_id}: {e}")

    async def _request_trade_ticks(
        self,
        instrument_id: InstrumentId,
        limit: int,
        correlation_id: Any,
        start: Any = None,
        end: Any = None,
        params: dict | None = None,
    ) -> None:
        """Request trade ticks (ticker data)."""
        from nautilus_futu.parsing.market_data import parse_futu_trade_tick

        market, code = instrument_id_to_futu_security(instrument_id)
        max_ret = limit if limit and limit > 0 else 100
        try:
            result = await asyncio.to_thread(
                self._client.get_ticker, market, code, max_ret
            )
            ts_init = self._clock.timestamp_ns()
            ticks = []
            for ticker in result:
                tick = parse_futu_trade_tick(ticker, instrument_id, ts_init)
                ticks.append(tick)
            self._handle_trade_ticks(instrument_id, ticks, correlation_id)
        except Exception as e:
            self._log.error(f"Failed to request trade ticks for {instrument_id}: {e}")

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
                self._config.rehab_type,
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
