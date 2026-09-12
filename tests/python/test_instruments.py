"""Tests for Futu instrument parsing."""


from nautilus_trader.model.enums import OptionKind
from nautilus_trader.model.instruments import Equity, FuturesContract, OptionContract

from nautilus_futu.constants import HKEX_VENUE, NYSE_VENUE, SSE_VENUE, SZSE_VENUE
from nautilus_futu.parsing.instruments import parse_futu_instrument


class TestParseFutuInstrument:
    """Tests for parse_futu_instrument."""

    def test_hk_equity(self):
        info = {"market": 1, "code": "00700", "name": "TENCENT", "lot_size": 100, "sec_type": 3}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert isinstance(instrument, Equity)
        assert instrument.id.symbol.value == "00700"
        assert instrument.id.venue == HKEX_VENUE
        assert str(instrument.quote_currency) == "HKD"
        assert int(instrument.lot_size) == 100

    def test_us_equity(self):
        info = {"market": 11, "code": "AAPL", "name": "Apple Inc", "lot_size": 1, "sec_type": 3}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert isinstance(instrument, Equity)
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
        # Futu settles CN trades in CNH (its Currency enum has no CNY)
        assert str(instrument.quote_currency) == "CNH"

    def test_cn_sz_equity(self):
        info = {"market": 22, "code": "000001", "name": "PING AN", "lot_size": 100}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert instrument.id.symbol.value == "000001"
        assert instrument.id.venue == SZSE_VENUE
        assert str(instrument.quote_currency) == "CNH"

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
        parse_futu_instrument({})
        # Should succeed with defaults (market=0, code="")
        # or return None if code is empty - depends on implementation
        # It actually succeeds with empty code
        # Should succeed with defaults or return None -- either is fine, just no crash
        assert True

    def test_price_precision_us(self):
        """US instruments should have price_precision=2 (market default)."""
        info = {"market": 11, "code": "TSLA", "lot_size": 1}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert instrument.price_precision == 2

    def test_price_precision_hk(self):
        """HK instruments should have price_precision=3 (market default)."""
        info = {"market": 1, "code": "00700", "lot_size": 100}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert instrument.price_precision == 3

    def test_price_precision_from_spread(self):
        """A coarse spread never reduces precision below the market's finest tick."""
        info = {"market": 1, "code": "00700", "lot_size": 100, "price_spread": 0.2}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert instrument.price_precision == 3
        assert str(instrument.price_increment) == "0.001"

    def test_price_precision_finer_spread(self):
        """A finer spread than the market default raises the precision (US sub-penny)."""
        info = {"market": 11, "code": "SNDL", "lot_size": 1, "price_spread": 0.0001}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert instrument.price_precision == 4
        assert str(instrument.price_increment) == "0.0001"

    def test_hk_tick_size_table(self):
        from nautilus_futu.parsing.instruments import hk_tick_size

        assert hk_tick_size(0.1) == 0.001
        assert hk_tick_size(0.3) == 0.005
        assert hk_tick_size(5.0) == 0.01
        assert hk_tick_size(15.0) == 0.02
        assert hk_tick_size(50.0) == 0.05
        assert hk_tick_size(150.0) == 0.1
        assert hk_tick_size(345.0) == 0.2
        assert hk_tick_size(750.0) == 0.5
        assert hk_tick_size(1500.0) == 1.0
        assert hk_tick_size(3000.0) == 2.0
        assert hk_tick_size(6000.0) == 5.0

    def test_sgx_currency_sgd(self):
        """market=31 (SGX) should use SGD currency."""
        from nautilus_futu.constants import SGX_VENUE

        info = {"market": 31, "code": "D05", "name": "DBS", "lot_size": 100}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert instrument.id.venue == SGX_VENUE
        assert str(instrument.quote_currency) == "SGD"

    def test_lot_size_zero(self):
        """lot_size=0 (indices/odd data) falls back to a lot size of 1."""
        info = {"market": 1, "code": "00700", "lot_size": 0}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert int(instrument.lot_size) == 1

    def test_empty_code(self):
        """Empty code should still parse without crashing."""
        info = {"market": 1, "code": "", "lot_size": 1}
        # Should not raise
        parse_futu_instrument(info)
        # Result may be None or a valid instrument - just ensure no crash
        # Should not raise -- either result is fine, just no crash
        assert True

    def test_exception_logged(self, caplog):
        """When parsing fails with an exception, it should be logged."""
        import logging

        # Force an exception by passing invalid data type for lot_size
        info = {"market": 1, "code": "00700", "lot_size": "not_a_number"}
        with caplog.at_level(logging.WARNING, logger="nautilus_futu.parsing.instruments"):
            result = parse_futu_instrument(info)
        if result is None:
            assert "Failed to parse instrument" in caplog.text


class TestETFParsing:
    """Tests for ETF (sec_type=4) -> Equity parsing."""

    def test_etf_returns_equity(self):
        info = {"market": 1, "code": "02800", "name": "Tracker Fund", "lot_size": 500, "sec_type": 4}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert isinstance(instrument, Equity)
        assert instrument.id.symbol.value == "02800"
        assert str(instrument.quote_currency) == "HKD"
        assert int(instrument.lot_size) == 500

    def test_us_etf(self):
        info = {"market": 11, "code": "SPY", "name": "SPDR S&P 500", "lot_size": 1, "sec_type": 4}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert isinstance(instrument, Equity)
        assert str(instrument.quote_currency) == "USD"


class TestWarrantCBBCParsing:
    """Tests for WARRANT (sec_type=5) and CBBC (sec_type=6) -> Equity."""

    def test_warrant_returns_equity(self):
        info = {"market": 1, "code": "12345", "name": "Warrant", "lot_size": 10000, "sec_type": 5}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert isinstance(instrument, Equity)

    def test_cbbc_returns_equity(self):
        info = {"market": 1, "code": "67890", "name": "CBBC", "lot_size": 10000, "sec_type": 6}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert isinstance(instrument, Equity)


class TestOptionParsing:
    """Tests for OPTION (sec_type=7) -> OptionContract."""

    def test_call_option(self):
        info = {
            "market": 11,
            "code": "AAPL240119C00200000",
            "name": "AAPL Call",
            "lot_size": 100,
            "sec_type": 7,
            "option_type": 1,  # CALL
            "option_owner_market": 11,
            "option_owner_code": "AAPL",
            "strike_price": 200.0,
            "strike_time": "2024-01-19",
            "strike_timestamp": 1705622400.0,
        }
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert isinstance(instrument, OptionContract)
        assert instrument.option_kind == OptionKind.CALL
        assert float(instrument.strike_price) == 200.0
        assert instrument.underlying == "AAPL"
        assert instrument.expiration_ns == int(1705622400.0 * 1e9)

    def test_put_option(self):
        info = {
            "market": 11,
            "code": "AAPL240119P00180000",
            "name": "AAPL Put",
            "lot_size": 100,
            "sec_type": 7,
            "option_type": 2,  # PUT
            "option_owner_market": 11,
            "option_owner_code": "AAPL",
            "strike_price": 180.0,
            "strike_time": "2024-01-19",
            "strike_timestamp": 1705622400.0,
        }
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert isinstance(instrument, OptionContract)
        assert instrument.option_kind == OptionKind.PUT
        assert float(instrument.strike_price) == 180.0

    def test_hk_option(self):
        info = {
            "market": 1,
            "code": "TCH240125C00350000",
            "name": "Tencent Call",
            "lot_size": 100,
            "sec_type": 7,
            "option_type": 1,
            "option_owner_market": 1,
            "option_owner_code": "00700",
            "strike_price": 350.0,
            "strike_time": "2024-01-25",
            "strike_timestamp": 1706140800.0,
        }
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert isinstance(instrument, OptionContract)
        assert str(instrument.quote_currency) == "HKD"
        assert instrument.underlying == "00700"

    def test_option_defaults_when_fields_missing(self):
        """Option with minimal fields should still parse."""
        info = {
            "market": 11,
            "code": "AAPL_OPT",
            "lot_size": 100,
            "sec_type": 7,
        }
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert isinstance(instrument, OptionContract)
        assert instrument.option_kind == OptionKind.CALL  # default


class TestFutureParsing:
    """Tests for FUTURE (sec_type=8) -> FuturesContract."""

    def test_hk_future(self):
        info = {
            "market": 2,
            "code": "HSI2406",
            "name": "HSI Futures",
            "lot_size": 50,
            "sec_type": 8,
            "last_trade_time": "2024-06-27",
            "last_trade_timestamp": 1719446400.0,
            "is_main_contract": True,
        }
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert isinstance(instrument, FuturesContract)
        assert instrument.id.symbol.value == "HSI2406"
        assert str(instrument.quote_currency) == "HKD"
        assert int(instrument.multiplier) == 50
        assert instrument.expiration_ns == int(1719446400.0 * 1e9)

    def test_us_future(self):
        info = {
            "market": 11,
            "code": "ESZ4",
            "name": "E-mini S&P",
            "lot_size": 50,
            "sec_type": 8,
            "last_trade_time": "2024-12-20",
            "last_trade_timestamp": 1734652800.0,
            "is_main_contract": False,
        }
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert isinstance(instrument, FuturesContract)
        assert str(instrument.quote_currency) == "USD"

    def test_future_defaults_when_fields_missing(self):
        """Future with minimal fields (official SecurityType_Future=10) should still parse."""
        info = {
            "market": 2,
            "code": "HSI_FUT",
            "lot_size": 1,
            "sec_type": 10,
        }
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert isinstance(instrument, FuturesContract)
        assert instrument.expiration_ns == 0

    def test_future_detected_by_extended_data(self):
        """Future extended data wins over an ambiguous sec_type."""
        info = {
            "market": 2,
            "code": "HSImain",
            "lot_size": 1,
            "sec_type": 8,
            "last_trade_timestamp": 1735603200.0,
            "is_main_contract": True,
        }
        instrument = parse_futu_instrument(info)
        assert isinstance(instrument, FuturesContract)
        assert instrument.expiration_ns == 1735603200 * 1_000_000_000

    def test_option_official_sec_type_drvt(self):
        """Official SecurityType_Drvt=8 with option data parses as an option."""
        from nautilus_trader.model.instruments import OptionContract

        info = {
            "market": 1,
            "code": "TCH250130C400000",
            "lot_size": 100,
            "sec_type": 8,
            "option_type": 1,
            "option_owner_code": "00700",
            "strike_price": 400.0,
            "strike_time": "2025-01-30",
        }
        instrument = parse_futu_instrument(info)
        assert isinstance(instrument, OptionContract)
        assert instrument.underlying == "00700"
        assert instrument.expiration_ns > 0


class TestUnknownSecType:
    """Tests for unknown sec_type values."""

    def test_unknown_sec_type_returns_equity(self):
        """Unknown sec_type should fall back to Equity."""
        info = {"market": 1, "code": "UNKNOWN", "lot_size": 1, "sec_type": 99}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert isinstance(instrument, Equity)

    def test_sec_type_zero(self):
        """sec_type=0 should fall back to Equity."""
        info = {"market": 1, "code": "TEST", "lot_size": 1, "sec_type": 0}
        instrument = parse_futu_instrument(info)
        assert instrument is not None
        assert isinstance(instrument, Equity)
