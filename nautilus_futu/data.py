"""Futu live data client for NautilusTrader."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.core.datetime import unix_nanos_to_dt
from nautilus_trader.data.messages import RequestBars
from nautilus_trader.live.data_client import LiveMarketDataClient
from nautilus_trader.model.data import Bar, BarType, DataType, OrderBookDeltas
from nautilus_trader.model.enums import BarAggregation, BookType
from nautilus_trader.model.identifiers import ClientId, InstrumentId, Venue

from nautilus_futu.common import (
    futu_security_to_instrument_id,
    instrument_id_to_futu_security,
    log_futu_notify,
)
from nautilus_futu.config import FutuDataClientConfig
from nautilus_futu.connection import FutuConnectionManager
from nautilus_futu.constants import (
    FUTU_KL_TYPE_TO_SUB_TYPE,
    FUTU_PROTO_BASIC_QOT,
    FUTU_PROTO_KL,
    FUTU_PROTO_NOTIFY,
    FUTU_PROTO_ORDER_BOOK,
    FUTU_PROTO_TICKER,
    FUTU_QOT_MARKET_TO_TZ,
    FUTU_SUB_TYPE_BASIC,
    FUTU_SUB_TYPE_ORDER_BOOK,
    FUTU_SUB_TYPE_TICKER,
    FUTU_VENUE,
)
from nautilus_futu.parsing.instruments import parse_futu_instrument
from nautilus_futu.parsing.market_data import (
    bar_spec_duration_ns,
    bar_spec_to_futu_kl_type,
    parse_futu_bar,
    parse_futu_bars,
    parse_futu_quote_tick,
    parse_futu_trade_tick,
    parse_order_book_to_quote_tick,
    parse_push_order_book,
)
from nautilus_futu.providers import FutuInstrumentProvider

# Push protocols this client consumes
_DATA_PUSH_PROTOS = [FUTU_PROTO_ORDER_BOOK, FUTU_PROTO_TICKER, FUTU_PROTO_KL, FUTU_PROTO_BASIC_QOT, FUTU_PROTO_NOTIFY]

# Grace period after a bar's nominal close before it is flushed as complete
_BAR_FLUSH_GRACE_NS = 2 * 1_000_000_000

# Default history lookback when a bar request has no `start`
_DEFAULT_LOOKBACK = {
    BarAggregation.MINUTE: timedelta(days=30),
    BarAggregation.HOUR: timedelta(days=90),
    BarAggregation.DAY: timedelta(days=730),
    BarAggregation.WEEK: timedelta(days=3650),
    BarAggregation.MONTH: timedelta(days=7300),
}


class FutuLiveDataClient(LiveMarketDataClient):
    """Provides a data client for Futu OpenD.

    Quote ticks are derived from the level-1 of the order book stream
    (``SubType_OrderBook``), trade ticks from the ticker stream and bars from
    the K-line streams.  A single order book subscription is shared between
    quote-tick and order-book consumers.

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
        instrument_provider: FutuInstrumentProvider,
        config: FutuDataClientConfig,
        connect_lock: asyncio.Lock | None = None,
        connection: FutuConnectionManager | None = None,
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=ClientId("FUTU"),
            venue=FUTU_VENUE,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=instrument_provider,
            config=config,
        )
        self._client = client
        self._instrument_provider = instrument_provider
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

        self._subscribed_quote_ticks: set[InstrumentId] = set()
        # Instruments whose quote ticks come from BasicQot because the order
        # book stream is not available (no depth quota, e.g. HK BMP accounts)
        self._quote_fallback_basic: set[InstrumentId] = set()
        self._subscribed_trade_ticks: set[InstrumentId] = set()
        self._subscribed_order_books: dict[InstrumentId, int] = {}  # instrument -> depth
        self._subscribed_bars: dict[tuple[InstrumentId, int], BarType] = {}  # (instrument, kl_type)
        self._partial_bars: dict[BarType, Bar] = {}
        self._last_emitted_bar_ts: dict[BarType, int] = {}
        self._book_sequence: dict[InstrumentId, int] = {}

        self._push_task: asyncio.Task | None = None
        self._bar_flush_task: asyncio.Task | None = None
        self._push_channel_id: int | None = None
        self._restored_generation: int = -1
        self._use_async_push = hasattr(client, "poll_push_async")

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def _connect(self) -> None:
        """Connect to Futu OpenD."""
        self._log.info("Connecting to Futu OpenD...")
        try:
            created = await self._conn.acquire()
            self._log.info("Connected to Futu OpenD" if created else "Reusing existing Futu OpenD connection")

            if self._push_channel_id is None:
                self._push_channel_id = await asyncio.to_thread(self._client.start_push, _DATA_PUSH_PROTOS)
            self._restored_generation = self._conn.generation

            await self._instrument_provider.initialize()

            self._push_task = self.create_task(self._run_push_loop())
            self._bar_flush_task = self.create_task(self._run_bar_flush_loop())
            self._log.info(f"Push loop started (channel_id={self._push_channel_id})")
        except Exception as e:
            self._log.error(f"Failed to connect to Futu OpenD: {e}")
            raise

    async def _disconnect(self) -> None:
        """Disconnect from Futu OpenD."""
        self._log.info("Disconnecting from Futu OpenD...")
        for attr in ("_push_task", "_bar_flush_task"):
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
            self._log.info("Released Futu OpenD connection")
        except Exception as e:
            self._log.error(f"Error disconnecting: {e}")

    async def _poll_push(self) -> dict | None:
        if self._use_async_push:
            return await self._client.poll_push_async(self._push_channel_id)
        return await asyncio.to_thread(self._client.poll_push, self._push_channel_id, 100)

    async def _run_push_loop(self) -> None:
        """Background loop that receives push messages and dispatches them."""
        self._log.debug("Push loop running")
        try:
            while True:
                try:
                    if self._conn.generation != self._restored_generation:
                        await self._restore_subscriptions()
                    msg = await self._poll_push()
                except asyncio.CancelledError:
                    raise
                except ConnectionError as e:
                    self._log.warning(f"Futu OpenD connection lost: {e}")
                    await self._reconnect()
                    continue
                except Exception as e:
                    self._log.error(f"Push poll error: {e}")
                    await asyncio.sleep(0.5)
                    continue

                if msg is None:
                    continue
                self._dispatch_push(msg)
        except asyncio.CancelledError:
            self._log.debug("Push loop cancelled")

    def _dispatch_push(self, msg: dict) -> None:
        proto_id = msg["proto_id"]
        data = msg["data"]
        try:
            if proto_id == FUTU_PROTO_ORDER_BOOK:
                self._handle_push_order_book(data)
            elif proto_id == FUTU_PROTO_TICKER:
                self._handle_push_ticker(data)
            elif proto_id == FUTU_PROTO_KL:
                self._handle_push_kl(data)
            elif proto_id == FUTU_PROTO_BASIC_QOT:
                self._handle_push_basic_qot(data)
            elif proto_id == FUTU_PROTO_NOTIFY:
                self._handle_push_notify(data)
        except Exception as e:
            self._log.error(f"Error handling push proto_id={proto_id}: {e}")

    async def _reconnect(self) -> None:
        """Wait, then re-establish the shared connection (subscriptions are restored by the loop)."""
        if not self._config.reconnect:
            self._log.error("Reconnect disabled; data client will stay offline")
            await asyncio.sleep(self._config.reconnect_interval)
            return
        self._log.warning(f"Reconnecting in {self._config.reconnect_interval}s...")
        await asyncio.sleep(self._config.reconnect_interval)
        try:
            await self._conn.ensure_connected()
            self._log.info("Reconnected to Futu OpenD")
        except Exception as e:
            self._log.error(f"Reconnection failed: {e}")

    async def _restore_subscriptions(self) -> None:
        """Re-subscribe every stream after a (possibly external) reconnect."""
        generation = self._conn.generation
        self._log.info(f"Restoring subscriptions (connection generation {generation})")
        books = (set(self._subscribed_quote_ticks) - self._quote_fallback_basic) | set(self._subscribed_order_books)
        total = 0
        for instrument_id in books:
            if await self._futu_subscribe(instrument_id, FUTU_SUB_TYPE_ORDER_BOOK, True):
                total += 1
        for instrument_id in list(self._quote_fallback_basic):
            if await self._futu_subscribe(instrument_id, FUTU_SUB_TYPE_BASIC, True):
                total += 1
        for instrument_id in list(self._subscribed_trade_ticks):
            if await self._futu_subscribe(instrument_id, FUTU_SUB_TYPE_TICKER, True):
                total += 1
        for (instrument_id, kl_type), _bar_type in list(self._subscribed_bars.items()):
            sub_type = FUTU_KL_TYPE_TO_SUB_TYPE.get(kl_type)
            if sub_type is not None and await self._futu_subscribe(instrument_id, sub_type, True):
                total += 1
        self._partial_bars.clear()
        self._restored_generation = generation
        if total:
            self._log.info(f"Restored {total} subscriptions after reconnection")

    # ------------------------------------------------------------------
    # Push handlers
    # ------------------------------------------------------------------

    def _instrument_for(self, instrument_id: InstrumentId):
        return self._cache.instrument(instrument_id)

    def _handle_push_basic_qot(self, data_list: list) -> None:
        """Basic quote push (3005): quote-tick fallback for instruments without an order book stream."""
        if not self._quote_fallback_basic:
            return
        ts_init = self._clock.timestamp_ns()
        for data in data_list:
            instrument_id = futu_security_to_instrument_id(data["market"], data["code"])
            if instrument_id not in self._quote_fallback_basic or instrument_id not in self._subscribed_quote_ticks:
                continue
            tick = parse_futu_quote_tick(data, instrument_id, ts_init, self._instrument_for(instrument_id))
            self._handle_data(tick)

    def _handle_push_ticker(self, data: dict) -> None:
        """Handle ticker push (proto 3011)."""
        instrument_id = futu_security_to_instrument_id(data["market"], data["code"])
        if instrument_id not in self._subscribed_trade_ticks:
            return
        instrument = self._instrument_for(instrument_id)
        ts_init = self._clock.timestamp_ns()
        for ticker in data.get("tickers", []):
            tick = parse_futu_trade_tick(ticker, instrument_id, ts_init, instrument)
            if tick is not None:
                self._handle_data(tick)

    def _handle_push_order_book(self, data: dict) -> None:
        """Handle order book push (proto 3013): L2 deltas and/or level-1 quote tick."""
        instrument_id = futu_security_to_instrument_id(data["market"], data["code"])
        instrument = self._instrument_for(instrument_id)
        ts_init = self._clock.timestamp_ns()

        if instrument_id in self._subscribed_quote_ticks and instrument_id not in self._quote_fallback_basic:
            tick = parse_order_book_to_quote_tick(data, instrument_id, ts_init, instrument)
            if tick is not None:
                self._handle_data(tick)

        depth = self._subscribed_order_books.get(instrument_id)
        if depth is not None:
            sequence = self._book_sequence.get(instrument_id, 0) + 1
            self._book_sequence[instrument_id] = sequence
            deltas = parse_push_order_book(
                data, instrument_id, ts_init, instrument, depth=depth, sequence=sequence,
            )
            self._handle_data(deltas)

    def _handle_push_kl(self, data: dict) -> None:
        """Handle K-line push (proto 3007).

        OpenD pushes the *current* bar on every update.  A bar is emitted as
        complete when a newer bar arrives (or the flush loop sees its window
        has closed); intermediate updates are emitted with ``is_revision``
        when ``handle_revised_bars`` is enabled.
        """
        instrument_id = futu_security_to_instrument_id(data["market"], data["code"])
        kl_type = data["kl_type"]
        bar_type = self._subscribed_bars.get((instrument_id, kl_type))
        if bar_type is None:
            return

        instrument = self._instrument_for(instrument_id)
        ts_init = self._clock.timestamp_ns()
        for kl in data.get("kl_list", []):
            bar = parse_futu_bar(kl, bar_type, instrument, ts_init=ts_init)
            if bar is None:
                continue
            self._on_bar_update(bar_type, bar, kl, instrument, ts_init)

    def _on_bar_update(self, bar_type: BarType, bar: Bar, kl: dict, instrument, ts_init: int) -> None:
        last_emitted = self._last_emitted_bar_ts.get(bar_type, -1)
        if bar.ts_event <= last_emitted:
            return  # late update for a bar already emitted as complete

        partial = self._partial_bars.get(bar_type)
        if partial is not None and bar.ts_event > partial.ts_event:
            self._emit_complete_bar(bar_type, partial)
        self._partial_bars[bar_type] = bar

        if self._config.handle_revised_bars:
            revision = parse_futu_bar(kl, bar_type, instrument, ts_init=ts_init, is_revision=True)
            if revision is not None:
                self._handle_data(revision)

    def _emit_complete_bar(self, bar_type: BarType, bar: Bar) -> None:
        self._last_emitted_bar_ts[bar_type] = bar.ts_event
        self._handle_data(bar)

    async def _run_bar_flush_loop(self) -> None:
        """Emit partial bars whose window has closed even if no newer bar arrived."""
        try:
            while True:
                await asyncio.sleep(1.0)
                now_ns = self._clock.timestamp_ns()
                for bar_type, bar in list(self._partial_bars.items()):
                    duration = bar_spec_duration_ns(bar_type.spec)
                    if duration and now_ns >= bar.ts_event + duration + _BAR_FLUSH_GRACE_NS:
                        self._partial_bars.pop(bar_type, None)
                        self._emit_complete_bar(bar_type, bar)
        except asyncio.CancelledError:
            pass

    def _handle_push_notify(self, data: dict) -> None:
        """Log OpenD gateway notifications (proto 1003)."""
        log_futu_notify(self._log, data)

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    async def _futu_subscribe(self, instrument_id: InstrumentId, sub_type: int, is_sub: bool) -> bool:
        market, code = instrument_id_to_futu_security(instrument_id)
        try:
            await asyncio.to_thread(self._client.subscribe, [(market, code)], [sub_type], is_sub)
            return True
        except Exception as e:
            action = "subscribe" if is_sub else "unsubscribe"
            self._log.error(f"Failed to {action} sub_type={sub_type} for {instrument_id}: {e}")
            return False

    def _book_needed(self, instrument_id: InstrumentId) -> bool:
        wants_book_quotes = (
            instrument_id in self._subscribed_quote_ticks and instrument_id not in self._quote_fallback_basic
        )
        return wants_book_quotes or instrument_id in self._subscribed_order_books

    async def _subscribe_quote_ticks(self, command) -> None:
        """Subscribe to quote tick updates (level-1 of the order book stream).

        When the order book stream cannot be subscribed (no depth quota for
        the market), fall back to BasicQot and synthesise bid/ask from the
        last price and spread, with a warning.
        """
        instrument_id = getattr(command, "instrument_id", command)
        if self._book_needed(instrument_id) or await self._futu_subscribe(instrument_id, FUTU_SUB_TYPE_ORDER_BOOK, True):
            self._quote_fallback_basic.discard(instrument_id)
            self._subscribed_quote_ticks.add(instrument_id)
            self._log.info(f"Subscribed to quote ticks for {instrument_id}")
            return
        if await self._futu_subscribe(instrument_id, FUTU_SUB_TYPE_BASIC, True):
            self._quote_fallback_basic.add(instrument_id)
            self._subscribed_quote_ticks.add(instrument_id)
            self._log.warning(
                f"Order book stream unavailable for {instrument_id}; quote ticks are synthesised "
                "from BasicQot (last price and spread), sizes are day volume",
            )

    async def _subscribe_trade_ticks(self, command) -> None:
        """Subscribe to trade tick updates."""
        instrument_id = getattr(command, "instrument_id", command)
        if await self._futu_subscribe(instrument_id, FUTU_SUB_TYPE_TICKER, True):
            self._subscribed_trade_ticks.add(instrument_id)
            self._log.info(f"Subscribed to trade ticks for {instrument_id}")

    async def _subscribe_order_book(self, command) -> None:
        instrument_id = getattr(command, "instrument_id", command)
        book_type = getattr(command, "book_type", BookType.L2_MBP)
        if book_type == BookType.L3_MBO:
            self._log.error(f"Futu provides L2 (price level) books only; cannot subscribe L3_MBO for {instrument_id}")
            return
        depth = int(getattr(command, "depth", 0) or 0) or self._config.order_book_depth
        already = self._book_needed(instrument_id)
        if already or await self._futu_subscribe(instrument_id, FUTU_SUB_TYPE_ORDER_BOOK, True):
            self._subscribed_order_books[instrument_id] = depth
            self._log.info(f"Subscribed to order book for {instrument_id} (depth={depth})")

    async def _subscribe_order_book_deltas(self, command) -> None:
        """Subscribe to order book updates."""
        await self._subscribe_order_book(command)

    async def _subscribe_order_book_snapshots(self, command) -> None:
        """Subscribe to order book snapshots (served from the same delta stream)."""
        await self._subscribe_order_book(command)

    async def _subscribe_bars(self, command) -> None:
        """Subscribe to bar updates."""
        bar_type = getattr(command, "bar_type", command)
        instrument_id = bar_type.instrument_id
        kl_type = bar_spec_to_futu_kl_type(bar_type.spec)
        sub_type = FUTU_KL_TYPE_TO_SUB_TYPE.get(kl_type) if kl_type is not None else None
        if kl_type is None or sub_type is None:
            self._log.warning(f"Unsupported bar type: {bar_type.spec}")
            return
        if await self._futu_subscribe(instrument_id, sub_type, True):
            self._subscribed_bars[(instrument_id, kl_type)] = bar_type
            self._log.info(f"Subscribed to bars for {bar_type}")

    async def _unsubscribe_quote_ticks(self, command) -> None:
        """Unsubscribe from quote tick updates."""
        instrument_id = getattr(command, "instrument_id", command)
        self._subscribed_quote_ticks.discard(instrument_id)
        if instrument_id in self._quote_fallback_basic:
            self._quote_fallback_basic.discard(instrument_id)
            await self._futu_subscribe(instrument_id, FUTU_SUB_TYPE_BASIC, False)
            return
        if not self._book_needed(instrument_id):
            await self._futu_subscribe(instrument_id, FUTU_SUB_TYPE_ORDER_BOOK, False)

    async def _unsubscribe_trade_ticks(self, command) -> None:
        """Unsubscribe from trade tick updates."""
        instrument_id = getattr(command, "instrument_id", command)
        self._subscribed_trade_ticks.discard(instrument_id)
        await self._futu_subscribe(instrument_id, FUTU_SUB_TYPE_TICKER, False)

    async def _unsubscribe_order_book(self, command) -> None:
        instrument_id = getattr(command, "instrument_id", command)
        self._subscribed_order_books.pop(instrument_id, None)
        self._book_sequence.pop(instrument_id, None)
        if not self._book_needed(instrument_id):
            await self._futu_subscribe(instrument_id, FUTU_SUB_TYPE_ORDER_BOOK, False)

    async def _unsubscribe_order_book_deltas(self, command) -> None:
        """Unsubscribe from order book updates."""
        await self._unsubscribe_order_book(command)

    async def _unsubscribe_order_book_snapshots(self, command) -> None:
        """Unsubscribe from order book snapshots."""
        await self._unsubscribe_order_book(command)

    async def _unsubscribe_bars(self, command) -> None:
        """Unsubscribe from bar updates."""
        bar_type = getattr(command, "bar_type", command)
        instrument_id = bar_type.instrument_id
        kl_type = bar_spec_to_futu_kl_type(bar_type.spec)
        sub_type = FUTU_KL_TYPE_TO_SUB_TYPE.get(kl_type) if kl_type is not None else None
        if kl_type is None or sub_type is None:
            return
        self._subscribed_bars.pop((instrument_id, kl_type), None)
        self._partial_bars.pop(bar_type, None)
        await self._futu_subscribe(instrument_id, sub_type, False)

    # ------------------------------------------------------------------
    # Requests
    # ------------------------------------------------------------------

    async def _request_instrument(self, request) -> None:
        """Request a single instrument definition."""
        instrument_id = request.instrument_id
        market, code = instrument_id_to_futu_security(instrument_id)
        try:
            static_info_list = await asyncio.to_thread(self._client.get_static_info, [(market, code)])
            if not static_info_list:
                self._log.warning(f"No static info returned for {instrument_id}")
                return
            instrument = parse_futu_instrument(static_info_list[0], self._clock.timestamp_ns())
            if instrument is None:
                self._log.warning(f"Failed to parse instrument for {instrument_id}")
                return
            self._handle_instrument(instrument, request.id, request.start, request.end, request.params)
        except Exception as e:
            self._log.error(f"Failed to request instrument {instrument_id}: {e}")

    async def _request_instruments(self, request) -> None:
        """Request every instrument of a venue (enumerated through the provider)."""
        venue: Venue = request.venue
        try:
            await self._instrument_provider.load_all_async({"venues": [venue]})
            instruments = [i for i in self._instrument_provider.list_all() if i.id.venue == venue]
            self._handle_instruments(venue, instruments, request.id, request.start, request.end, request.params)
        except Exception as e:
            self._log.error(f"Failed to request instruments for {venue}: {e}")

    async def _request_quote_ticks(self, request) -> None:
        """Request the current quote (security snapshot with real bid/ask)."""
        instrument_id = request.instrument_id
        market, code = instrument_id_to_futu_security(instrument_id)
        try:
            result = await asyncio.to_thread(self._client.get_security_snapshot, [(market, code)])
            ts_init = self._clock.timestamp_ns()
            instrument = self._instrument_for(instrument_id)
            ticks = [parse_futu_quote_tick(data, instrument_id, ts_init, instrument) for data in result]
            self._handle_quote_ticks(instrument_id, ticks, request.id, request.start, request.end, request.params)
        except Exception as e:
            self._log.error(f"Failed to request quote ticks for {instrument_id}: {e}")

    async def _request_trade_ticks(self, request) -> None:
        """Request recent trade ticks (requires an active ticker subscription on OpenD)."""
        instrument_id = request.instrument_id
        limit = request.limit
        market, code = instrument_id_to_futu_security(instrument_id)
        max_ret = limit if limit and limit > 0 else 100
        try:
            result = await asyncio.to_thread(self._client.get_ticker, market, code, max_ret)
            ts_init = self._clock.timestamp_ns()
            instrument = self._instrument_for(instrument_id)
            parsed = (parse_futu_trade_tick(t, instrument_id, ts_init, instrument) for t in result)
            ticks = [t for t in parsed if t is not None]
            self._handle_trade_ticks(instrument_id, ticks, request.id, request.start, request.end, request.params)
        except Exception as e:
            self._log.error(f"Failed to request trade ticks for {instrument_id}: {e}")

    async def _request_bars(self, request: RequestBars) -> None:
        """Request historical bars (paginated on the Rust side)."""
        bar_type = request.bar_type
        instrument_id = bar_type.instrument_id
        market, code = instrument_id_to_futu_security(instrument_id)
        kl_type = bar_spec_to_futu_kl_type(bar_type.spec)
        if kl_type is None:
            self._log.warning(f"Unsupported bar type for request: {bar_type.spec}")
            return

        params = request.params or {}
        rehab_type = int(params.get("rehab_type", self._config.rehab_type))
        limit = request.limit if request.limit and request.limit > 0 else None

        end = request.end or unix_nanos_to_dt(self._clock.timestamp_ns())
        start = request.start or (end - _DEFAULT_LOOKBACK.get(bar_type.spec.aggregation, timedelta(days=30)))
        intraday = bar_type.spec.aggregation in (BarAggregation.MINUTE, BarAggregation.HOUR)
        begin_str = _format_futu_time(start, market, intraday)
        end_str = _format_futu_time(end, market, intraday)

        try:
            result = await asyncio.to_thread(
                self._client.get_history_kl,
                market, code, rehab_type, kl_type, begin_str, end_str, limit,
            )
            instrument = self._instrument_for(instrument_id)
            bars = parse_futu_bars(result, bar_type, instrument)
            self._log.info(f"Received {len(bars)} bars from Futu for {bar_type} [{begin_str} .. {end_str}]")
            self._handle_bars(bar_type, bars, request.id, request.start, request.end, request.params)
        except Exception as e:
            self._log.error(f"Failed to request bars for {bar_type}: {e}")

    async def _request_order_book_snapshot(self, request) -> None:
        """Request a one-off order book snapshot (Qot_GetOrderBook)."""
        instrument_id = request.instrument_id
        market, code = instrument_id_to_futu_security(instrument_id)
        depth = int(getattr(request, "limit", 0) or 0) or self._config.order_book_depth
        try:
            data = await asyncio.to_thread(self._client.get_order_book, market, code, depth)
            ts_init = self._clock.timestamp_ns()
            instrument = self._instrument_for(instrument_id)
            deltas = parse_push_order_book(data, instrument_id, ts_init, instrument, depth=depth)
            data_type = DataType(OrderBookDeltas, metadata={"instrument_id": instrument_id})
            self._handle_data_response(data_type, deltas, request.id, request.start, request.end, request.params)
        except Exception as e:
            self._log.error(f"Failed to request order book snapshot for {instrument_id}: {e}")


def _format_futu_time(dt: datetime, market: int, intraday: bool) -> str:
    """Format a datetime for OpenD history requests in the market's local time."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    tz_name = FUTU_QOT_MARKET_TO_TZ.get(market)
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            dt = dt.astimezone(ZoneInfo(tz_name))
        except Exception:
            dt = dt.astimezone(UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%d %H:%M:%S") if intraday else dt.strftime("%Y-%m-%d")
