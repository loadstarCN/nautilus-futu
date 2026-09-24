"""Tests for FutuLiveDataClient push handling with a real client instance."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.model.data import (
    Bar,
    BarSpecification,
    BarType,
    OrderBookDeltas,
    OrderBookDepth10,
    QuoteTick,
    TradeTick,
)
from nautilus_trader.model.enums import AggregationSource, BarAggregation, BookAction, BookType, PriceType, RecordFlag
from nautilus_trader.model.identifiers import TraderId

from nautilus_futu.config import FutuDataClientConfig
from nautilus_futu.constants import (
    FUTU_KL_TYPE_1MIN,
    FUTU_KL_TYPE_60MIN,
    FUTU_SUB_TYPE_BASIC,
    FUTU_SUB_TYPE_KL_1MIN,
    FUTU_SUB_TYPE_ORDER_BOOK,
    FUTU_SUB_TYPE_TICKER,
)
from nautilus_futu.data import FutuLiveDataClient, _format_futu_time
from nautilus_futu.parsing.instruments import parse_futu_instrument
from nautilus_futu.providers import FutuInstrumentProvider

HK = parse_futu_instrument({"market": 1, "code": "00700", "lot_size": 100, "sec_type": 3})
IID = HK.id


class Harness:
    def __init__(self, **config_kwargs):
        self.loop = asyncio.new_event_loop()
        self.clock = LiveClock()
        self.msgbus = MessageBus(trader_id=TraderId("T-1"), clock=self.clock)
        self.cache = Cache()
        self.cache.add_instrument(HK)
        self.rust = MagicMock()
        self.data: list = []
        self.client = FutuLiveDataClient(
            loop=self.loop,
            client=self.rust,
            msgbus=self.msgbus,
            cache=self.cache,
            clock=self.clock,
            instrument_provider=FutuInstrumentProvider(self.rust),
            config=FutuDataClientConfig(**config_kwargs),
        )
        self.client._handle_data = self.data.append  # capture instead of publishing

    def run(self, coro):
        return self.loop.run_until_complete(coro)


@pytest.fixture
def h():
    harness = Harness()
    yield harness
    harness.loop.close()


def book_push(bid=345.2, ask=345.4, bid_vol=1000, ask_vol=500, ts=1718400000.0, levels=1):
    bids = [{"price": round(bid - i * 0.2, 3), "volume": bid_vol, "order_count": 3} for i in range(levels)]
    asks = [{"price": round(ask + i * 0.2, 3), "volume": ask_vol, "order_count": 2} for i in range(levels)]
    return {"market": 1, "code": "00700", "bids": bids, "asks": asks,
            "svr_recv_time_bid_timestamp": ts, "svr_recv_time_ask_timestamp": ts}


def kl_push(ts, close, kl_type=FUTU_KL_TYPE_1MIN, volume=10):
    return {
        "market": 1, "code": "00700", "kl_type": kl_type, "rehab_type": 1,
        "kl_list": [{"open_price": 345.0, "high_price": 346.0, "low_price": 344.0, "close_price": close,
                     "volume": volume, "timestamp": ts, "is_blank": False}],
    }


class TestSubscriptions:
    def test_quote_ticks_subscribe_order_book_stream(self, h):
        h.run(h.client._subscribe_quote_ticks(IID))
        h.rust.subscribe.assert_called_once_with([(1, "00700")], [FUTU_SUB_TYPE_ORDER_BOOK], True)
        assert IID in h.client._subscribed_quote_ticks

    def test_book_and_quotes_share_one_subscription(self, h):
        cmd = MagicMock(instrument_id=IID, book_type=BookType.L2_MBP, depth=5)
        h.run(h.client._subscribe_order_book_deltas(cmd))
        h.run(h.client._subscribe_quote_ticks(IID))
        assert h.rust.subscribe.call_count == 1
        # unsubscribing one consumer keeps the Futu subscription alive
        h.run(h.client._unsubscribe_quote_ticks(IID))
        assert h.rust.subscribe.call_count == 1
        h.run(h.client._unsubscribe_order_book_deltas(cmd))
        assert h.rust.subscribe.call_count == 2
        assert h.rust.subscribe.call_args.args[2] is False

    def test_quote_ticks_fall_back_to_basic_qot_when_book_unavailable(self, h):
        calls = []

        def subscribe(securities, sub_types, is_sub):
            calls.append((sub_types[0], is_sub))
            if sub_types[0] == FUTU_SUB_TYPE_ORDER_BOOK:
                raise RuntimeError("Subscribe failed: no order book permission")

        h.rust.subscribe.side_effect = subscribe
        h.run(h.client._subscribe_quote_ticks(IID))
        assert calls == [(FUTU_SUB_TYPE_ORDER_BOOK, True), (FUTU_SUB_TYPE_BASIC, True)]
        assert IID in h.client._subscribed_quote_ticks
        assert IID in h.client._quote_fallback_basic

        # BasicQot pushes now produce synthesised quote ticks for this instrument
        h.client._handle_push_basic_qot([
            {"market": 1, "code": "00700", "cur_price": 345.2, "price_spread": 0.2, "volume": 10, "update_timestamp": 1718400000.0},
        ])
        assert len(h.data) == 1
        assert isinstance(h.data[0], QuoteTick)
        assert str(h.data[0].bid_price) == "345.200"
        assert str(h.data[0].ask_price) == "345.400"

        # order book pushes are ignored for it and unsubscribe releases BasicQot
        h.client._handle_push_order_book(book_push())
        assert len(h.data) == 1
        h.run(h.client._unsubscribe_quote_ticks(IID))
        assert calls[-1] == (FUTU_SUB_TYPE_BASIC, False)
        assert IID not in h.client._quote_fallback_basic

    def test_basic_qot_push_ignored_without_fallback(self, h):
        h.client._subscribed_quote_ticks.add(IID)
        h.client._handle_push_basic_qot([{"market": 1, "code": "00700", "cur_price": 1.0, "price_spread": 0.1, "volume": 1}])
        assert h.data == []

    def test_l3_book_rejected(self, h):
        cmd = MagicMock(instrument_id=IID, book_type=BookType.L3_MBO, depth=0)
        h.run(h.client._subscribe_order_book_deltas(cmd))
        assert not h.rust.subscribe.called

    def test_trade_ticks(self, h):
        h.run(h.client._subscribe_trade_ticks(IID))
        h.rust.subscribe.assert_called_once_with([(1, "00700")], [FUTU_SUB_TYPE_TICKER], True)

    def test_bars_keyed_by_kl_type(self, h):
        bar_type = BarType(IID, BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST), AggregationSource.EXTERNAL)
        h.run(h.client._subscribe_bars(bar_type))
        h.rust.subscribe.assert_called_once_with([(1, "00700")], [FUTU_SUB_TYPE_KL_1MIN], True)
        assert h.client._subscribed_bars[(IID, FUTU_KL_TYPE_1MIN)] == bar_type

    def test_subscribe_failure_not_recorded(self, h):
        h.rust.subscribe.side_effect = RuntimeError("quota exceeded")
        h.run(h.client._subscribe_trade_ticks(IID))
        assert IID not in h.client._subscribed_trade_ticks

    def test_restore_subscriptions_resubscribes_everything(self, h):
        bar_type = BarType(IID, BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST), AggregationSource.EXTERNAL)
        h.run(h.client._subscribe_quote_ticks(IID))
        h.run(h.client._subscribe_trade_ticks(IID))
        h.run(h.client._subscribe_bars(bar_type))
        h.rust.subscribe.reset_mock()
        h.rust.connection_generation.return_value = 3

        h.run(h.client._restore_subscriptions())

        sub_types = sorted(c.args[1][0] for c in h.rust.subscribe.call_args_list)
        assert sub_types == sorted([FUTU_SUB_TYPE_ORDER_BOOK, FUTU_SUB_TYPE_TICKER, FUTU_SUB_TYPE_KL_1MIN])
        assert h.client._restored_generation == 3


class TestOrderBookPush:
    def test_quote_tick_from_level_one(self, h):
        h.client._subscribed_quote_ticks.add(IID)
        h.client._handle_push_order_book(book_push())
        assert len(h.data) == 1
        tick = h.data[0]
        assert isinstance(tick, QuoteTick)
        assert str(tick.bid_price) == "345.200"
        assert str(tick.ask_price) == "345.400"
        assert int(tick.bid_size) == 1000
        assert tick.ts_event == 1718400000 * 1_000_000_000

    def test_deltas_with_depth_flags_and_sequence(self, h):
        h.client._subscribed_order_books[IID] = 2
        h.client._handle_push_order_book(book_push(levels=5))
        h.client._handle_push_order_book(book_push(levels=5))
        assert len(h.data) == 2
        deltas = h.data[0]
        assert isinstance(deltas, OrderBookDeltas)
        assert deltas.deltas[0].action == BookAction.CLEAR
        assert deltas.deltas[0].flags & RecordFlag.F_SNAPSHOT
        assert len(deltas.deltas) == 1 + 2 + 2  # clear + 2 bids + 2 asks (depth=2)
        assert deltas.deltas[-1].flags & RecordFlag.F_LAST
        assert all(d.sequence == 1 for d in deltas.deltas)
        assert h.data[1].deltas[0].sequence == 2

    def test_both_consumers(self, h):
        h.client._subscribed_quote_ticks.add(IID)
        h.client._subscribed_order_books[IID] = 10
        h.client._handle_push_order_book(book_push())
        assert [type(d) for d in h.data] == [QuoteTick, OrderBookDeltas]

    def test_empty_side_gives_no_quote(self, h):
        h.client._subscribed_quote_ticks.add(IID)
        data = book_push()
        data["asks"] = []
        h.client._handle_push_order_book(data)
        assert h.data == []

    def test_unsubscribed_ignored(self, h):
        h.client._handle_push_order_book(book_push())
        assert h.data == []

    def test_depth10_padded_with_counts(self, h):
        h.client._subscribed_book_depth.add(IID)
        h.client._handle_push_order_book(book_push(levels=5))
        assert len(h.data) == 1
        depth = h.data[0]
        assert isinstance(depth, OrderBookDepth10)
        assert len(depth.bids) == len(depth.asks) == 10
        assert str(depth.bids[0].price) == "345.200"
        assert str(depth.asks[4].price) == "346.200"
        assert int(depth.bids[0].size) == 1000
        assert depth.bids[5].size == 0  # padded level
        assert depth.bid_counts == [3] * 5 + [0] * 5
        assert depth.ask_counts == [2] * 5 + [0] * 5
        assert depth.flags & RecordFlag.F_LAST
        assert depth.sequence == 1
        assert depth.ts_event == 1718400000 * 1_000_000_000

    def test_depth10_uneven_sides_and_zero_volume_levels(self, h):
        h.client._subscribed_book_depth.add(IID)
        data = book_push(levels=3)
        data["bids"][1]["volume"] = 0
        data["asks"] = []
        h.client._handle_push_order_book(data)
        depth = h.data[0]
        assert [str(b.price) for b in depth.bids[:2]] == ["345.200", "344.800"]
        assert depth.bids[2].size == 0
        assert all(a.size == 0 for a in depth.asks)

    def test_depth10_and_deltas_share_sequence(self, h):
        h.client._subscribed_order_books[IID] = 10
        h.client._subscribed_book_depth.add(IID)
        h.client._handle_push_order_book(book_push(levels=2))
        assert [type(d) for d in h.data] == [OrderBookDeltas, OrderBookDepth10]
        assert h.data[0].deltas[0].sequence == h.data[1].sequence == 1


class TestOrderBookDepthSubscription:
    def test_depth_shares_book_stream_with_quotes(self, h):
        cmd = MagicMock(instrument_id=IID)
        h.run(h.client._subscribe_order_book_depth(cmd))
        h.rust.subscribe.assert_called_once_with([(1, "00700")], [FUTU_SUB_TYPE_ORDER_BOOK], True)
        h.run(h.client._subscribe_quote_ticks(IID))
        assert h.rust.subscribe.call_count == 1  # stream reused
        h.run(h.client._unsubscribe_order_book_depth(cmd))
        assert h.rust.subscribe.call_count == 1  # quotes still need it
        h.run(h.client._unsubscribe_quote_ticks(IID))
        assert h.rust.subscribe.call_count == 2
        assert h.rust.subscribe.call_args.args == ([(1, "00700")], [FUTU_SUB_TYPE_ORDER_BOOK], False)

    def test_depth_subscription_restored_after_reconnect(self, h):
        h.run(h.client._subscribe_order_book_depth(MagicMock(instrument_id=IID)))
        h.rust.subscribe.reset_mock()
        h.run(h.client._restore_subscriptions())
        h.rust.subscribe.assert_called_once_with([(1, "00700")], [FUTU_SUB_TYPE_ORDER_BOOK], True)

    def test_depth_subscribe_failure_not_recorded(self, h):
        h.rust.subscribe.side_effect = RuntimeError("no quota")
        h.run(h.client._subscribe_order_book_depth(MagicMock(instrument_id=IID)))
        assert IID not in h.client._subscribed_book_depth


class TestTickerPush:
    def test_trade_ticks_use_instrument_precision(self, h):
        h.client._subscribed_trade_ticks.add(IID)
        h.client._handle_push_ticker({"market": 1, "code": "00700", "tickers": [
            {"price": 345.2, "volume": 100, "dir": 1, "sequence": 5, "timestamp": 1718400000.0},
            {"price": 345.4, "volume": 200, "dir": 2, "sequence": 6, "timestamp": 1718400001.0},
        ]})
        assert len(h.data) == 2
        assert all(isinstance(t, TradeTick) for t in h.data)
        assert str(h.data[0].price) == "345.200"
        assert h.data[1].trade_id.value == "6"


class TestBarPush:
    @pytest.fixture
    def bar_type(self, h):
        bt = BarType(IID, BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST), AggregationSource.EXTERNAL)
        h.client._subscribed_bars[(IID, FUTU_KL_TYPE_1MIN)] = bt
        return bt

    def test_partial_updates_are_not_emitted_until_next_bar(self, h, bar_type):
        h.client._handle_push_kl(kl_push(1718400000.0, 345.1))
        h.client._handle_push_kl(kl_push(1718400000.0, 345.3))
        assert h.data == []
        h.client._handle_push_kl(kl_push(1718400060.0, 345.5))
        assert len(h.data) == 1
        bar = h.data[0]
        assert isinstance(bar, Bar)
        assert str(bar.close) == "345.300"  # last revision of the completed bar
        assert bar.ts_event == 1718400000 * 1_000_000_000
        assert not bar.is_revision

    def test_late_update_for_emitted_bar_ignored(self, h, bar_type):
        h.client._handle_push_kl(kl_push(1718400000.0, 345.1))
        h.client._handle_push_kl(kl_push(1718400060.0, 345.5))
        h.client._handle_push_kl(kl_push(1718400000.0, 345.9))  # stale
        h.client._handle_push_kl(kl_push(1718400120.0, 346.0))
        assert [str(b.close) for b in h.data] == ["345.100", "345.500"]

    def test_revisions_emitted_when_enabled(self):
        harness = Harness(handle_revised_bars=True)
        try:
            bt = BarType(IID, BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST), AggregationSource.EXTERNAL)
            harness.client._subscribed_bars[(IID, FUTU_KL_TYPE_1MIN)] = bt
            harness.client._handle_push_kl(kl_push(1718400000.0, 345.1))
            harness.client._handle_push_kl(kl_push(1718400000.0, 345.3))
            harness.client._handle_push_kl(kl_push(1718400060.0, 345.5))
            kinds = [(b.is_revision, str(b.close)) for b in harness.data]
            assert kinds == [(True, "345.100"), (True, "345.300"), (False, "345.300"), (True, "345.500")]
        finally:
            harness.loop.close()

    def test_flush_emits_closed_bar_without_successor(self, h, bar_type):
        h.client._handle_push_kl(kl_push(1718400000.0, 345.1))  # far in the past -> window closed
        h.client._partial_bars  # noqa: B018 (sanity: present)

        async def one_tick():
            task = h.loop.create_task(h.client._run_bar_flush_loop())
            await asyncio.sleep(1.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        h.run(one_tick())
        assert len(h.data) == 1
        assert not h.data[0].is_revision
        assert h.client._partial_bars == {}

    def test_hour_subscription_receives_60min_pushes(self, h):
        bt = BarType(IID, BarSpecification(1, BarAggregation.HOUR, PriceType.LAST), AggregationSource.EXTERNAL)
        h.run(h.client._subscribe_bars(bt))
        h.client._handle_push_kl(kl_push(1718400000.0, 345.1, kl_type=FUTU_KL_TYPE_60MIN))
        h.client._handle_push_kl(kl_push(1718403600.0, 345.2, kl_type=FUTU_KL_TYPE_60MIN))
        assert len(h.data) == 1
        assert h.data[0].bar_type == bt


class TestRequests:
    def test_request_bars_formats_market_local_time_and_paginates(self, h):
        h.rust.get_history_kl.return_value = [
            {"open_price": 1.0, "high_price": 2.0, "low_price": 0.5, "close_price": 1.5, "volume": 3,
             "timestamp": 1718400000.0, "is_blank": False},
        ]
        bar_type = BarType(IID, BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST), AggregationSource.EXTERNAL)
        request = MagicMock(
            bar_type=bar_type,
            start=datetime(2024, 6, 14, 1, 30, tzinfo=UTC),
            end=datetime(2024, 6, 14, 8, 0, tzinfo=UTC),
            limit=0,
            params={},
        )
        handled = []
        h.client._handle_bars = lambda *a: handled.append(a)

        h.run(h.client._request_bars(request))

        args = h.rust.get_history_kl.call_args.args
        assert args[0:2] == (1, "00700")
        assert args[2] == 1  # rehab_type from config
        assert args[3] == FUTU_KL_TYPE_1MIN
        assert args[4] == "2024-06-14 09:30:00"  # Hong Kong local time
        assert args[5] == "2024-06-14 16:00:00"
        assert args[6] is None  # limit=0 -> unbounded (paginated on Rust side)
        assert len(handled[0][1]) == 1

    def test_request_quote_ticks_uses_snapshot(self, h):
        h.rust.get_security_snapshot.return_value = [
            {"market": 1, "code": "00700", "cur_price": 345.3, "bid_price": 345.2, "ask_price": 345.4,
             "bid_vol": 100, "ask_vol": 200, "update_timestamp": 1718400000.0},
        ]
        handled = []
        h.client._handle_quote_ticks = lambda *a: handled.append(a)
        request = MagicMock(instrument_id=IID, start=None, end=None, params={})
        h.run(h.client._request_quote_ticks(request))
        assert h.rust.get_security_snapshot.called
        ticks = handled[0][1]
        assert str(ticks[0].bid_price) == "345.200"
        assert str(ticks[0].ask_price) == "345.400"


def test_format_futu_time_daily_and_intraday():
    dt = datetime(2024, 6, 14, 23, 30, tzinfo=UTC)
    assert _format_futu_time(dt, 1, intraday=False) == "2024-06-15"  # already next day in HK
    assert _format_futu_time(dt, 11, intraday=True) == "2024-06-14 19:30:00"  # New York (EDT)
    assert _format_futu_time(dt, 999, intraday=True) == "2024-06-14 23:30:00"  # unknown market -> UTC
