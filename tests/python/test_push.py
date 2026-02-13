"""Tests for push notification parsing."""

from __future__ import annotations

import pytest
from nautilus_trader.model.data import (
    Bar,
    BarSpecification,
    BarType,
    OrderBookDelta,
    OrderBookDeltas,
    QuoteTick,
    TradeTick,
)
from nautilus_trader.model.enums import (
    AggressorSide,
    BarAggregation,
    BookAction,
    OrderSide,
    OrderStatus,
    PriceType,
)
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TradeId, Venue

from nautilus_futu.common import futu_security_to_instrument_id
from nautilus_futu.constants import (
    FUTU_KL_TYPE_1MIN,
    FUTU_KL_TYPE_5MIN,
    FUTU_KL_TYPE_15MIN,
    FUTU_KL_TYPE_30MIN,
    FUTU_KL_TYPE_60MIN,
    FUTU_KL_TYPE_DAY,
    FUTU_ORDER_STATUS_CANCELLED_ALL,
    FUTU_ORDER_STATUS_FILLED_ALL,
    FUTU_ORDER_STATUS_FILLED_PART,
    FUTU_ORDER_STATUS_SUBMITTED,
    FUTU_ORDER_STATUS_SUBMIT_FAILED,
)
from nautilus_futu.parsing.market_data import (
    futu_kl_type_to_bar_spec,
    parse_futu_bars,
    parse_futu_quote_tick,
    parse_futu_trade_tick,
    parse_push_order_book,
)
from nautilus_futu.parsing.orders import futu_order_status_to_nautilus


class TestPushQuoteTick:
    """Test push basic quote -> QuoteTick conversion."""

    def test_basic_qot_to_quote_tick(self):
        data = {
            "market": 1,
            "code": "00700",
            "cur_price": 345.0,
            "volume": 10000000,
            "high_price": 350.0,
            "open_price": 340.0,
            "low_price": 335.0,
            "turnover": 3400000000.0,
            "update_timestamp": 1704067200.0,
        }
        instrument_id = futu_security_to_instrument_id(1, "00700")
        ts_init = 1704067200_000_000_000

        tick = parse_futu_quote_tick(data, instrument_id, ts_init)

        assert isinstance(tick, QuoteTick)
        assert tick.instrument_id == instrument_id
        assert float(tick.bid_price) == 345.0
        assert float(tick.ask_price) == 345.0
        assert tick.ts_init == ts_init

    def test_basic_qot_us_stock(self):
        data = {
            "market": 11,
            "code": "AAPL",
            "cur_price": 195.5,
            "volume": 50000000,
        }
        instrument_id = futu_security_to_instrument_id(11, "AAPL")
        ts_init = 1704067200_000_000_000

        tick = parse_futu_quote_tick(data, instrument_id, ts_init)

        assert tick.instrument_id == instrument_id
        assert float(tick.bid_price) == 195.5


class TestPushTradeTick:
    """Test push ticker -> TradeTick conversion."""

    def test_ticker_to_trade_tick_buyer(self):
        data = {
            "price": 345.0,
            "volume": 100,
            "dir": 1,  # Buyer
            "sequence": 12345,
            "timestamp": 1704067200.0,
            "turnover": 34500.0,
        }
        instrument_id = futu_security_to_instrument_id(1, "00700")
        ts_init = 1704067200_000_000_000

        tick = parse_futu_trade_tick(data, instrument_id, ts_init)

        assert isinstance(tick, TradeTick)
        assert tick.instrument_id == instrument_id
        assert float(tick.price) == 345.0
        assert tick.aggressor_side == AggressorSide.BUYER
        assert tick.trade_id == TradeId("12345")

    def test_ticker_to_trade_tick_seller(self):
        data = {
            "price": 195.0,
            "volume": 200,
            "dir": 2,  # Seller
            "sequence": 67890,
        }
        instrument_id = futu_security_to_instrument_id(11, "AAPL")
        ts_init = 1704067200_000_000_000

        tick = parse_futu_trade_tick(data, instrument_id, ts_init)

        assert tick.aggressor_side == AggressorSide.SELLER
        assert tick.trade_id == TradeId("67890")

    def test_ticker_no_direction(self):
        data = {
            "price": 100.0,
            "volume": 50,
            "dir": 0,
            "sequence": 111,
        }
        instrument_id = futu_security_to_instrument_id(1, "00700")
        tick = parse_futu_trade_tick(data, instrument_id, 0)
        assert tick.aggressor_side == AggressorSide.NO_AGGRESSOR


class TestPushOrderBook:
    """Test push order book -> OrderBookDeltas conversion."""

    def test_order_book_to_deltas(self):
        data = {
            "market": 1,
            "code": "00700",
            "bids": [
                {"price": 345.0, "volume": 1000, "order_count": 20},
                {"price": 344.8, "volume": 2000, "order_count": 15},
            ],
            "asks": [
                {"price": 345.2, "volume": 500, "order_count": 10},
                {"price": 345.4, "volume": 800, "order_count": 8},
            ],
        }
        instrument_id = futu_security_to_instrument_id(1, "00700")
        ts_init = 1704067200_000_000_000

        deltas = parse_push_order_book(data, instrument_id, ts_init)

        assert isinstance(deltas, OrderBookDeltas)
        assert deltas.instrument_id == instrument_id
        # 1 CLEAR + 2 bids + 2 asks = 5 deltas
        assert len(deltas.deltas) == 5
        # First delta should be CLEAR
        assert deltas.deltas[0].action == BookAction.CLEAR
        # Next 2 are bid ADDs
        assert deltas.deltas[1].action == BookAction.ADD
        assert deltas.deltas[1].order.side == OrderSide.BUY
        assert float(deltas.deltas[1].order.price) == 345.0
        assert deltas.deltas[2].order.side == OrderSide.BUY
        # Next 2 are ask ADDs
        assert deltas.deltas[3].action == BookAction.ADD
        assert deltas.deltas[3].order.side == OrderSide.SELL
        assert float(deltas.deltas[3].order.price) == 345.2

    def test_order_book_empty(self):
        data = {
            "market": 1,
            "code": "00700",
            "bids": [],
            "asks": [],
        }
        instrument_id = futu_security_to_instrument_id(1, "00700")
        deltas = parse_push_order_book(data, instrument_id, 0)
        # Only CLEAR delta
        assert len(deltas.deltas) == 1
        assert deltas.deltas[0].action == BookAction.CLEAR


class TestPushKLine:
    """Test push K-line -> Bar conversion."""

    def test_kl_to_bars(self):
        kl_data = [
            {
                "open_price": 340.0,
                "high_price": 350.0,
                "low_price": 335.0,
                "close_price": 345.0,
                "volume": 10000,
                "timestamp": 1704067200.0,
                "is_blank": False,
            },
        ]
        instrument_id = futu_security_to_instrument_id(1, "00700")
        bar_spec = BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST)
        bar_type = BarType(instrument_id, bar_spec)

        bars = parse_futu_bars(kl_data, bar_type)

        assert len(bars) == 1
        bar = bars[0]
        assert isinstance(bar, Bar)
        assert float(bar.open) == 340.0
        assert float(bar.high) == 350.0
        assert float(bar.low) == 335.0
        assert float(bar.close) == 345.0

    def test_kl_blank_skipped(self):
        kl_data = [
            {
                "open_price": 0,
                "high_price": 0,
                "low_price": 0,
                "close_price": 0,
                "volume": 0,
                "timestamp": 0,
                "is_blank": True,
            },
        ]
        instrument_id = futu_security_to_instrument_id(1, "00700")
        bar_spec = BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST)
        bar_type = BarType(instrument_id, bar_spec)

        bars = parse_futu_bars(kl_data, bar_type)
        assert len(bars) == 0


class TestKLTypeReverseMapping:
    """Test KLType -> BarSpecification reverse mapping."""

    def test_1min(self):
        spec = futu_kl_type_to_bar_spec(FUTU_KL_TYPE_1MIN)
        assert spec is not None
        assert spec.step == 1
        assert spec.aggregation == BarAggregation.MINUTE

    def test_5min(self):
        spec = futu_kl_type_to_bar_spec(FUTU_KL_TYPE_5MIN)
        assert spec is not None
        assert spec.step == 5
        assert spec.aggregation == BarAggregation.MINUTE

    def test_15min(self):
        spec = futu_kl_type_to_bar_spec(FUTU_KL_TYPE_15MIN)
        assert spec is not None
        assert spec.step == 15
        assert spec.aggregation == BarAggregation.MINUTE

    def test_30min(self):
        spec = futu_kl_type_to_bar_spec(FUTU_KL_TYPE_30MIN)
        assert spec is not None
        assert spec.step == 30
        assert spec.aggregation == BarAggregation.MINUTE

    def test_60min(self):
        spec = futu_kl_type_to_bar_spec(FUTU_KL_TYPE_60MIN)
        assert spec is not None
        assert spec.step == 1
        assert spec.aggregation == BarAggregation.HOUR

    def test_day(self):
        spec = futu_kl_type_to_bar_spec(FUTU_KL_TYPE_DAY)
        assert spec is not None
        assert spec.step == 1
        assert spec.aggregation == BarAggregation.DAY

    def test_unknown_returns_none(self):
        spec = futu_kl_type_to_bar_spec(999)
        assert spec is None


class TestPushOrderStatus:
    """Test push order status mapping."""

    def test_submitted_maps_to_accepted(self):
        status = futu_order_status_to_nautilus(FUTU_ORDER_STATUS_SUBMITTED)
        assert status == OrderStatus.ACCEPTED

    def test_filled_all_maps_to_filled(self):
        status = futu_order_status_to_nautilus(FUTU_ORDER_STATUS_FILLED_ALL)
        assert status == OrderStatus.FILLED

    def test_filled_part_maps_to_partially_filled(self):
        status = futu_order_status_to_nautilus(FUTU_ORDER_STATUS_FILLED_PART)
        assert status == OrderStatus.PARTIALLY_FILLED

    def test_cancelled_maps_to_canceled(self):
        status = futu_order_status_to_nautilus(FUTU_ORDER_STATUS_CANCELLED_ALL)
        assert status == OrderStatus.CANCELED

    def test_submit_failed_maps_to_rejected(self):
        status = futu_order_status_to_nautilus(FUTU_ORDER_STATUS_SUBMIT_FAILED)
        assert status == OrderStatus.REJECTED
