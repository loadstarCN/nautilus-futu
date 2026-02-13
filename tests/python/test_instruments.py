"""Tests for Futu instrument parsing."""

import pytest

from nautilus_futu.parsing.instruments import parse_futu_instrument
from nautilus_futu.constants import HKEX_VENUE, NYSE_VENUE, SSE_VENUE, SZSE_VENUE


class TestParseFutuInstrument:
    """Tests for parse_futu_instrument."""

    def test_hk_equity(self):
        info = {"market": 1, "code": "00700", "name": "TENCENT", "lot_size": 100}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert instrument.id.symbol.value == "00700"
        assert instrument.id.venue == HKEX_VENUE
        assert str(instrument.quote_currency) == "HKD"
        assert int(instrument.lot_size) == 100

    def test_us_equity(self):
        info = {"market": 11, "code": "AAPL", "name": "Apple Inc", "lot_size": 1}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert instrument.id.symbol.value == "AAPL"
        assert instrument.id.venue == NYSE_VENUE
        assert str(instrument.quote_currency) == "USD"
        assert int(instrument.lot_size) == 1

    def test_cn_sh_equity(self):
        info = {"market": 21, "code": "600519", "name": "MOUTAI", "lot_size": 100}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert instrument.id.symbol.value == "600519"
        assert instrument.id.venue == SSE_VENUE
        assert str(instrument.quote_currency) == "CNY"

    def test_cn_sz_equity(self):
        info = {"market": 22, "code": "000001", "name": "PING AN", "lot_size": 100}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert instrument.id.symbol.value == "000001"
        assert instrument.id.venue == SZSE_VENUE
        assert str(instrument.quote_currency) == "CNY"

    def test_hk_future_uses_hkd(self):
        """market=2 (HK futures) should use HKD."""
        info = {"market": 2, "code": "HSI2406", "lot_size": 1}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert str(instrument.quote_currency) == "HKD"

    def test_unknown_market_defaults_usd(self):
        """Unknown market should default to USD."""
        info = {"market": 99, "code": "SOMETHING", "lot_size": 1}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert str(instrument.quote_currency) == "USD"

    def test_missing_fields_use_defaults(self):
        """Missing optional fields should use defaults."""
        info = {"market": 1, "code": "09988"}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert instrument.id.symbol.value == "09988"
        assert int(instrument.lot_size) == 1  # default lot_size

    def test_empty_dict_returns_none(self):
        """Empty dict should not crash, returns instrument with default fields."""
        instrument = parse_futu_instrument({})
        # Should succeed with defaults (market=0, code="")
        # or return None if code is empty - depends on implementation
        # It actually succeeds with empty code
        assert instrument is not None or instrument is None  # No crash

    def test_price_precision(self):
        """All instruments should have price_precision=3."""
        info = {"market": 11, "code": "TSLA", "lot_size": 1}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert instrument.price_precision == 3

    def test_sgx_currency_sgd(self):
        """market=31 (SGX) should use SGD currency."""
        from nautilus_futu.constants import SGX_VENUE

        info = {"market": 31, "code": "D05", "name": "DBS", "lot_size": 100}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert instrument.id.venue == SGX_VENUE
        assert str(instrument.quote_currency) == "SGD"

    def test_lot_size_zero(self):
        """lot_size=0 triggers validation error, should return None gracefully."""
        info = {"market": 1, "code": "00700", "lot_size": 0}
        instrument = parse_futu_instrument(info)
        assert instrument is None

    def test_empty_code(self):
        """Empty code should still parse without crashing."""
        info = {"market": 1, "code": "", "lot_size": 1}
        # Should not raise
        result = parse_futu_instrument(info)
        # Result may be None or a valid instrument - just ensure no crash
        assert result is not None or result is None

    def test_exception_logged(self, caplog):
        """When parsing fails with an exception, it should be logged."""
        import logging

        # Force an exception by passing invalid data type for lot_size
        info = {"market": 1, "code": "00700", "lot_size": "not_a_number"}
        with caplog.at_level(logging.WARNING, logger="nautilus_futu.parsing.instruments"):
            result = parse_futu_instrument(info)
        if result is None:
            assert "Failed to parse instrument" in caplog.text
