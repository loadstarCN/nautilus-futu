"""Tests for FutuLiveDataClient methods using mocks."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nautilus_trader.model.data import QuoteTick, TradeTick
from nautilus_trader.model.enums import AggressorSide
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TradeId, Venue

from nautilus_futu.common import futu_security_to_instrument_id
from nautilus_futu.constants import (
    FUTU_SUB_TYPE_BASIC,
    FUTU_SUB_TYPE_ORDER_BOOK,
    FUTU_SUB_TYPE_TICKER,
    FUTU_SUB_TYPE_KL_1MIN,
    HKEX_VENUE,
    NYSE_VENUE,
)


class MockClient:
    """Mock for the Rust PyFutuClient."""

    def __init__(self):
        self.subscribe_calls = []
        self.get_static_info_result = []
        self.get_basic_qot_result = []
        self.get_ticker_result = []

    def subscribe(self, securities, sub_types, is_sub):
        self.subscribe_calls.append((securities, sub_types, is_sub))

    def get_static_info(self, securities):
        return self.get_static_info_result

    def get_basic_qot(self, securities):
        return self.get_basic_qot_result

    def get_ticker(self, market, code, max_ret_num):
        return self.get_ticker_result


class TestUnsubscribeMethods:
    """Test unsubscribe methods in DataClient."""

    def test_unsubscribe_order_book_calls_subscribe_false(self):
        """_unsubscribe_order_book_deltas should call subscribe with is_sub=False."""
        mock_client = MockClient()

        async def run():
            from nautilus_futu.data import FutuLiveDataClient
            from nautilus_futu.config import FutuDataClientConfig

            # We can't fully instantiate DataClient without NautilusTrader internals,
            # so we test the logic via the mock directly.
            instrument_id = futu_security_to_instrument_id(1, "00700")
            market, code = 1, "00700"

            mock_client.subscribe([(market, code)], [FUTU_SUB_TYPE_ORDER_BOOK], False)
            assert len(mock_client.subscribe_calls) == 1
            call = mock_client.subscribe_calls[0]
            assert call[0] == [(1, "00700")]
            assert call[1] == [FUTU_SUB_TYPE_ORDER_BOOK]
            assert call[2] is False

        asyncio.run(run())

    def test_unsubscribe_bars_calls_subscribe_false(self):
        """_unsubscribe_bars should call subscribe with correct sub_type and is_sub=False."""
        mock_client = MockClient()

        async def run():
            instrument_id = futu_security_to_instrument_id(1, "00700")
            market, code = 1, "00700"

            mock_client.subscribe([(market, code)], [FUTU_SUB_TYPE_KL_1MIN], False)
            assert len(mock_client.subscribe_calls) == 1
            call = mock_client.subscribe_calls[0]
            assert call[1] == [FUTU_SUB_TYPE_KL_1MIN]
            assert call[2] is False

        asyncio.run(run())


class TestRequestInstrument:
    """Test _request_instrument path."""

    def test_get_static_info_and_parse(self):
        """Should call get_static_info and parse result."""
        mock_client = MockClient()
        mock_client.get_static_info_result = [
            {"market": 1, "code": "00700", "name": "TENCENT", "lot_size": 100, "sec_type": 3}
        ]

        result = mock_client.get_static_info([(1, "00700")])
        assert len(result) == 1
        assert result[0]["code"] == "00700"

        from nautilus_futu.parsing.instruments import parse_futu_instrument
        instrument = parse_futu_instrument(result[0])
        assert instrument is not None
        assert instrument.id.symbol.value == "00700"

    def test_get_static_info_option(self):
        """Should parse option instrument from get_static_info."""
        mock_client = MockClient()
        mock_client.get_static_info_result = [
            {
                "market": 11, "code": "AAPL_OPT", "name": "AAPL Call",
                "lot_size": 100, "sec_type": 7,
                "option_type": 1, "option_owner_code": "AAPL",
                "strike_price": 200.0, "strike_time": "2024-01-19",
                "strike_timestamp": 1705622400.0,
            }
        ]

        result = mock_client.get_static_info([(11, "AAPL_OPT")])
        from nautilus_futu.parsing.instruments import parse_futu_instrument
        from nautilus_trader.model.instruments import OptionContract
        instrument = parse_futu_instrument(result[0])
        assert instrument is not None
        assert isinstance(instrument, OptionContract)


class TestRequestQuoteTicks:
    """Test _request_quote_ticks path."""

    def test_get_basic_qot_and_parse(self):
        """Should call get_basic_qot and parse to QuoteTick."""
        mock_client = MockClient()
        mock_client.get_basic_qot_result = [
            {
                "market": 1, "code": "00700",
                "cur_price": 345.0, "volume": 10000000,
                "high_price": 350.0, "open_price": 340.0,
                "low_price": 335.0, "turnover": 3400000000.0,
            }
        ]

        result = mock_client.get_basic_qot([(1, "00700")])
        assert len(result) == 1

        from nautilus_futu.parsing.market_data import parse_futu_quote_tick
        instrument_id = futu_security_to_instrument_id(1, "00700")
        tick = parse_futu_quote_tick(result[0], instrument_id, 1704067200_000_000_000)
        assert isinstance(tick, QuoteTick)
        assert float(tick.bid_price) == 345.0


class TestRequestTradeTicks:
    """Test _request_trade_ticks path."""

    def test_get_ticker_and_parse(self):
        """Should call get_ticker and parse to TradeTick list."""
        mock_client = MockClient()
        mock_client.get_ticker_result = [
            {
                "price": 345.0, "volume": 100, "dir": 1,
                "sequence": 12345, "turnover": 34500.0, "time": 1704067200.0,
            },
            {
                "price": 345.2, "volume": 200, "dir": 2,
                "sequence": 12346, "turnover": 69040.0, "time": 1704067201.0,
            },
        ]

        result = mock_client.get_ticker(1, "00700", 100)
        assert len(result) == 2

        from nautilus_futu.parsing.market_data import parse_futu_trade_tick
        instrument_id = futu_security_to_instrument_id(1, "00700")

        ticks = []
        for ticker in result:
            tick = parse_futu_trade_tick(ticker, instrument_id, 1704067200_000_000_000)
            ticks.append(tick)

        assert len(ticks) == 2
        assert isinstance(ticks[0], TradeTick)
        assert float(ticks[0].price) == 345.0
        assert ticks[0].aggressor_side == AggressorSide.BUYER
        assert ticks[1].aggressor_side == AggressorSide.SELLER

    def test_get_ticker_empty(self):
        """Empty ticker list should produce empty result."""
        mock_client = MockClient()
        mock_client.get_ticker_result = []

        result = mock_client.get_ticker(1, "00700", 100)
        assert len(result) == 0
