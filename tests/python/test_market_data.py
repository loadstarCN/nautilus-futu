"""Tests for Futu market data parsing."""

import pytest

from nautilus_trader.model.data import BarSpecification, BarType, QuoteTick, TradeTick, Bar
from nautilus_trader.model.enums import (
    AggregationSource,
    AggressorSide,
    BarAggregation,
    PriceType,
)
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TradeId
from nautilus_trader.model.objects import Price, Quantity

from nautilus_futu.common import futu_security_to_instrument_id
from nautilus_futu.constants import HKEX_VENUE, NYSE_VENUE
from nautilus_futu.parsing.market_data import (
    bar_spec_to_futu_kl_type,
    bar_spec_to_futu_sub_type,
    parse_futu_bars,
    parse_futu_quote_tick,
    parse_futu_trade_tick,
)
from nautilus_futu.constants import (
    FUTU_KL_TYPE_5MIN,
    FUTU_KL_TYPE_15MIN,
    FUTU_KL_TYPE_30MIN,
    FUTU_KL_TYPE_60MIN,
    FUTU_SUB_TYPE_KL_5MIN,
    FUTU_SUB_TYPE_KL_15MIN,
    FUTU_SUB_TYPE_KL_30MIN,
    FUTU_SUB_TYPE_KL_60MIN,
)


@pytest.fixture
def hk_instrument_id():
    return InstrumentId(Symbol("00700"), HKEX_VENUE)


@pytest.fixture
def us_instrument_id():
    return InstrumentId(Symbol("AAPL"), NYSE_VENUE)


class TestParseQuoteTick:
    """Tests for parse_futu_quote_tick."""

    def test_basic_quote(self, hk_instrument_id):
        data = {"cur_price": 350.6, "volume": 12345678}
        tick = parse_futu_quote_tick(data, hk_instrument_id, ts_init=1000000)
        assert isinstance(tick, QuoteTick)
        assert tick.instrument_id == hk_instrument_id
        assert str(tick.bid_price) == "350.6"
        assert str(tick.ask_price) == "350.6"
        assert tick.ts_init == 1000000

    def test_zero_price(self, hk_instrument_id):
        data = {"cur_price": 0, "volume": 0}
        tick = parse_futu_quote_tick(data, hk_instrument_id, ts_init=0)
        assert str(tick.bid_price) == "0"
        assert str(tick.ask_price) == "0"

    def test_missing_fields_use_defaults(self, hk_instrument_id):
        """Missing fields should default to 0."""
        data = {}
        tick = parse_futu_quote_tick(data, hk_instrument_id, ts_init=0)
        assert str(tick.bid_price) == "0"

    def test_us_instrument(self, us_instrument_id):
        data = {"cur_price": 175.25, "volume": 50000000}
        tick = parse_futu_quote_tick(data, us_instrument_id, ts_init=2000000)
        assert tick.instrument_id == us_instrument_id
        assert tick.ts_event == 2000000


class TestParseTradeTick:
    """Tests for parse_futu_trade_tick."""

    def test_buyer_aggressor(self, hk_instrument_id):
        data = {"price": 350.6, "volume": 1000, "dir": 1, "sequence": 42}
        tick = parse_futu_trade_tick(data, hk_instrument_id, ts_init=1000)
        assert isinstance(tick, TradeTick)
        assert tick.aggressor_side == AggressorSide.BUYER
        assert str(tick.price) == "350.6"
        assert tick.trade_id == TradeId("42")

    def test_seller_aggressor(self, hk_instrument_id):
        data = {"price": 349.0, "volume": 500, "dir": 2, "sequence": 43}
        tick = parse_futu_trade_tick(data, hk_instrument_id, ts_init=2000)
        assert tick.aggressor_side == AggressorSide.SELLER

    def test_no_aggressor(self, hk_instrument_id):
        data = {"price": 350.0, "volume": 200, "dir": 0, "sequence": 44}
        tick = parse_futu_trade_tick(data, hk_instrument_id, ts_init=3000)
        assert tick.aggressor_side == AggressorSide.NO_AGGRESSOR

    def test_unknown_dir_no_aggressor(self, hk_instrument_id):
        """Unknown dir value should result in NO_AGGRESSOR."""
        data = {"price": 350.0, "volume": 100, "dir": 99, "sequence": 45}
        tick = parse_futu_trade_tick(data, hk_instrument_id, ts_init=4000)
        assert tick.aggressor_side == AggressorSide.NO_AGGRESSOR

    def test_missing_dir_defaults_no_aggressor(self, hk_instrument_id):
        """Missing dir field should default to NO_AGGRESSOR."""
        data = {"price": 10.0, "volume": 100, "sequence": 1}
        tick = parse_futu_trade_tick(data, hk_instrument_id, ts_init=0)
        assert tick.aggressor_side == AggressorSide.NO_AGGRESSOR
        assert tick.trade_id == TradeId("1")


class TestParseBars:
    """Tests for parse_futu_bars."""

    @pytest.fixture
    def bar_type(self, hk_instrument_id):
        spec = BarSpecification(1, BarAggregation.DAY, PriceType.LAST)
        return BarType(hk_instrument_id, spec, AggregationSource.EXTERNAL)

    def test_single_bar(self, bar_type):
        kl_data = [
            {
                "open_price": 345.0,
                "high_price": 355.0,
                "low_price": 340.0,
                "close_price": 350.0,
                "volume": 10000000,
                "timestamp": 1718400000.0,
                "is_blank": False,
            },
        ]
        bars = parse_futu_bars(kl_data, bar_type)
        assert len(bars) == 1
        bar = bars[0]
        assert isinstance(bar, Bar)
        assert str(bar.open) == "345.0"
        assert str(bar.high) == "355.0"
        assert str(bar.low) == "340.0"
        assert str(bar.close) == "350.0"
        assert bar.volume == 10000000

    def test_multiple_bars(self, bar_type):
        kl_data = [
            {"open_price": 100, "high_price": 110, "low_price": 95, "close_price": 105, "volume": 1000, "timestamp": 1000.0},
            {"open_price": 105, "high_price": 115, "low_price": 100, "close_price": 112, "volume": 2000, "timestamp": 2000.0},
        ]
        bars = parse_futu_bars(kl_data, bar_type)
        assert len(bars) == 2
        assert str(bars[0].close) == "105"
        assert str(bars[1].close) == "112"

    def test_blank_bars_skipped(self, bar_type):
        kl_data = [
            {"open_price": 100, "high_price": 110, "low_price": 95, "close_price": 105, "volume": 1000, "timestamp": 1000.0, "is_blank": False},
            {"open_price": 0, "high_price": 0, "low_price": 0, "close_price": 0, "volume": 0, "timestamp": 2000.0, "is_blank": True},
            {"open_price": 108, "high_price": 120, "low_price": 105, "close_price": 118, "volume": 3000, "timestamp": 3000.0, "is_blank": False},
        ]
        bars = parse_futu_bars(kl_data, bar_type)
        assert len(bars) == 2

    def test_empty_kl_data(self, bar_type):
        bars = parse_futu_bars([], bar_type)
        assert bars == []

    def test_bar_without_timestamp(self, bar_type):
        """Bar without timestamp should have ts_event=0."""
        kl_data = [
            {"open_price": 100, "high_price": 110, "low_price": 95, "close_price": 105, "volume": 500},
        ]
        bars = parse_futu_bars(kl_data, bar_type)
        assert len(bars) == 1
        assert bars[0].ts_event == 0

    def test_bar_timestamp_conversion(self, bar_type):
        """Timestamp should be converted to nanoseconds."""
        kl_data = [
            {"open_price": 100, "high_price": 110, "low_price": 95, "close_price": 105, "volume": 500, "timestamp": 1718400000.0},
        ]
        bars = parse_futu_bars(kl_data, bar_type)
        assert bars[0].ts_event == 1718400000000000000  # seconds * 1e9


class TestBarSpecConversionsExtended:
    """Extended tests for bar spec conversions (supplement to test_parsing.py)."""

    def test_5min_bar_sub_type(self):
        spec = BarSpecification(5, BarAggregation.MINUTE, PriceType.LAST)
        assert bar_spec_to_futu_sub_type(spec) == FUTU_SUB_TYPE_KL_5MIN

    def test_15min_bar_sub_type(self):
        spec = BarSpecification(15, BarAggregation.MINUTE, PriceType.LAST)
        assert bar_spec_to_futu_sub_type(spec) == FUTU_SUB_TYPE_KL_15MIN

    def test_30min_bar_sub_type(self):
        spec = BarSpecification(30, BarAggregation.MINUTE, PriceType.LAST)
        assert bar_spec_to_futu_sub_type(spec) == FUTU_SUB_TYPE_KL_30MIN

    def test_60min_bar_sub_type(self):
        """60-min uses HOUR aggregation in NautilusTrader."""
        spec = BarSpecification(1, BarAggregation.HOUR, PriceType.LAST)
        assert bar_spec_to_futu_sub_type(spec) == FUTU_SUB_TYPE_KL_60MIN

    def test_5min_bar_kl_type(self):
        spec = BarSpecification(5, BarAggregation.MINUTE, PriceType.LAST)
        assert bar_spec_to_futu_kl_type(spec) == FUTU_KL_TYPE_5MIN

    def test_15min_bar_kl_type(self):
        spec = BarSpecification(15, BarAggregation.MINUTE, PriceType.LAST)
        assert bar_spec_to_futu_kl_type(spec) == FUTU_KL_TYPE_15MIN

    def test_30min_bar_kl_type(self):
        spec = BarSpecification(30, BarAggregation.MINUTE, PriceType.LAST)
        assert bar_spec_to_futu_kl_type(spec) == FUTU_KL_TYPE_30MIN

    def test_60min_bar_kl_type(self):
        """60-min uses HOUR aggregation in NautilusTrader."""
        spec = BarSpecification(1, BarAggregation.HOUR, PriceType.LAST)
        assert bar_spec_to_futu_kl_type(spec) == FUTU_KL_TYPE_60MIN

    def test_unsupported_minute_step(self):
        """Step=3 minutes is not supported by Futu."""
        spec = BarSpecification(3, BarAggregation.MINUTE, PriceType.LAST)
        assert bar_spec_to_futu_sub_type(spec) is None
        assert bar_spec_to_futu_kl_type(spec) is None

    def test_week_bar_not_supported_via_sub_type(self):
        """WEEK aggregation is not exposed in sub_type mapping."""
        spec = BarSpecification(1, BarAggregation.WEEK, PriceType.LAST)
        assert bar_spec_to_futu_sub_type(spec) is None

    def test_month_bar_not_supported_via_sub_type(self):
        spec = BarSpecification(1, BarAggregation.MONTH, PriceType.LAST)
        assert bar_spec_to_futu_sub_type(spec) is None

    def test_hour_2_not_supported(self):
        """HOUR with step=2 is not supported by Futu."""
        spec = BarSpecification(2, BarAggregation.HOUR, PriceType.LAST)
        assert bar_spec_to_futu_sub_type(spec) is None
        assert bar_spec_to_futu_kl_type(spec) is None


class TestParseBarsExtended:
    """Extended tests for parse_futu_bars edge cases."""

    @pytest.fixture
    def bar_type(self):
        instrument_id = InstrumentId(Symbol("00700"), HKEX_VENUE)
        spec = BarSpecification(1, BarAggregation.DAY, PriceType.LAST)
        return BarType(instrument_id, spec, AggregationSource.EXTERNAL)

    def test_parse_bars_all_blank(self, bar_type):
        """All blank bars should produce empty list."""
        kl_data = [
            {"open_price": 0, "high_price": 0, "low_price": 0, "close_price": 0, "volume": 0, "is_blank": True},
            {"open_price": 0, "high_price": 0, "low_price": 0, "close_price": 0, "volume": 0, "is_blank": True},
        ]
        bars = parse_futu_bars(kl_data, bar_type)
        assert len(bars) == 0

    def test_parse_bars_mixed_blank(self, bar_type):
        """Mixed blank and valid data should only include non-blank bars."""
        kl_data = [
            {"open_price": 100, "high_price": 110, "low_price": 95, "close_price": 105, "volume": 1000, "is_blank": True},
            {"open_price": 200, "high_price": 210, "low_price": 195, "close_price": 205, "volume": 2000, "is_blank": False},
            {"open_price": 300, "high_price": 310, "low_price": 295, "close_price": 305, "volume": 3000, "is_blank": True},
            {"open_price": 400, "high_price": 410, "low_price": 395, "close_price": 405, "volume": 4000},
        ]
        bars = parse_futu_bars(kl_data, bar_type)
        assert len(bars) == 2
        assert str(bars[0].close) == "205"
        assert str(bars[1].close) == "405"


class TestTickEdgeCases:
    """Edge case tests for tick parsing."""

    def test_quote_tick_zero_price(self):
        """cur_price=0 should not crash."""
        instrument_id = InstrumentId(Symbol("TEST"), HKEX_VENUE)
        data = {"cur_price": 0, "volume": 0}
        tick = parse_futu_quote_tick(data, instrument_id, ts_init=0)
        assert str(tick.bid_price) == "0"
        assert str(tick.ask_price) == "0"

    def test_trade_tick_zero_volume(self):
        """volume=0 raises ValueError from NautilusTrader validation."""
        instrument_id = InstrumentId(Symbol("TEST"), HKEX_VENUE)
        data = {"price": 100.0, "volume": 0, "dir": 1, "sequence": 1}
        with pytest.raises(ValueError, match="not a positive integer"):
            parse_futu_trade_tick(data, instrument_id, ts_init=0)
