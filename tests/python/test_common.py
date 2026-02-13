"""Tests for Futu common utilities."""

import pytest

from nautilus_futu.common import (
    futu_security_to_instrument_id,
    instrument_id_to_futu_security,
    parse_futu_datetime,
)
from nautilus_futu.constants import FUTU_VENUE, HKEX_VENUE, NYSE_VENUE, SSE_VENUE


class TestSymbolConversion:
    """Tests for symbol conversion utilities."""

    def test_hk_security_to_instrument_id(self):
        instrument_id = futu_security_to_instrument_id(1, "00700")
        assert instrument_id.symbol.value == "00700"
        assert instrument_id.venue == HKEX_VENUE

    def test_us_security_to_instrument_id(self):
        instrument_id = futu_security_to_instrument_id(11, "AAPL")
        assert instrument_id.symbol.value == "AAPL"
        assert instrument_id.venue == NYSE_VENUE

    def test_cn_sh_security_to_instrument_id(self):
        instrument_id = futu_security_to_instrument_id(21, "600519")
        assert instrument_id.symbol.value == "600519"
        assert instrument_id.venue == SSE_VENUE

    def test_unknown_market_uses_futu_venue(self):
        instrument_id = futu_security_to_instrument_id(99, "UNKNOWN")
        assert instrument_id.venue == FUTU_VENUE

    def test_instrument_id_to_futu_hk(self):
        from nautilus_trader.model.identifiers import InstrumentId, Symbol

        instrument_id = InstrumentId(Symbol("00700"), HKEX_VENUE)
        market, code = instrument_id_to_futu_security(instrument_id)
        assert market == 1
        assert code == "00700"

    def test_instrument_id_to_futu_us(self):
        from nautilus_trader.model.identifiers import InstrumentId, Symbol

        instrument_id = InstrumentId(Symbol("AAPL"), NYSE_VENUE)
        market, code = instrument_id_to_futu_security(instrument_id)
        assert market == 11
        assert code == "AAPL"


class TestSymbolConversionExtended:
    """Extended tests for more market/venue combinations."""

    def test_hk_futures_to_instrument_id(self):
        """market=2 (HK futures) should also map to HKEX."""
        instrument_id = futu_security_to_instrument_id(2, "HSI2406")
        assert instrument_id.symbol.value == "HSI2406"
        assert instrument_id.venue == HKEX_VENUE

    def test_cn_sz_security_to_instrument_id(self):
        from nautilus_futu.constants import SZSE_VENUE

        instrument_id = futu_security_to_instrument_id(22, "000001")
        assert instrument_id.symbol.value == "000001"
        assert instrument_id.venue == SZSE_VENUE

    def test_sg_security_to_instrument_id(self):
        from nautilus_futu.constants import SGX_VENUE

        instrument_id = futu_security_to_instrument_id(31, "D05")
        assert instrument_id.symbol.value == "D05"
        assert instrument_id.venue == SGX_VENUE

    def test_instrument_id_to_futu_cn_sz(self):
        from nautilus_trader.model.identifiers import InstrumentId, Symbol
        from nautilus_futu.constants import SZSE_VENUE

        instrument_id = InstrumentId(Symbol("000001"), SZSE_VENUE)
        market, code = instrument_id_to_futu_security(instrument_id)
        assert market == 22
        assert code == "000001"

    def test_instrument_id_to_futu_sg(self):
        from nautilus_trader.model.identifiers import InstrumentId, Symbol
        from nautilus_futu.constants import SGX_VENUE

        instrument_id = InstrumentId(Symbol("D05"), SGX_VENUE)
        market, code = instrument_id_to_futu_security(instrument_id)
        assert market == 31
        assert code == "D05"

    def test_instrument_id_to_futu_nasdaq(self):
        """NASDAQ venue should also map to market=11 (US)."""
        from nautilus_trader.model.identifiers import InstrumentId, Symbol
        from nautilus_futu.constants import NASDAQ_VENUE

        instrument_id = InstrumentId(Symbol("TSLA"), NASDAQ_VENUE)
        market, code = instrument_id_to_futu_security(instrument_id)
        assert market == 11
        assert code == "TSLA"

    def test_unknown_venue_returns_zero_market(self):
        from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue

        instrument_id = InstrumentId(Symbol("XYZ"), Venue("UNKNOWN"))
        market, code = instrument_id_to_futu_security(instrument_id)
        assert market == 0
        assert code == "XYZ"


class TestDatetimeParsing:
    """Tests for datetime parsing."""

    def test_parse_futu_datetime(self):
        result = parse_futu_datetime("2024-01-15 09:30:00")
        assert result == "2024-01-15T09:30:00"

    def test_parse_futu_datetime_date_only(self):
        """Date-only string has no space, so should return as-is."""
        result = parse_futu_datetime("2024-01-15")
        assert result == "2024-01-15"

    def test_parse_futu_datetime_empty(self):
        result = parse_futu_datetime("")
        assert result == ""
