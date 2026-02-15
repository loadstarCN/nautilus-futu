"""Tests for Futu constants and mapping consistency."""

import pytest

from nautilus_futu.constants import (
    FUTU_MARKET_TO_VENUE,
    VENUE_TO_FUTU_MARKET,
    FUTU_VENUE,
    HKEX_VENUE,
    NYSE_VENUE,
    NASDAQ_VENUE,
    SSE_VENUE,
    SZSE_VENUE,
    SGX_VENUE,
    FUTU_QOT_MARKET_HK,
    FUTU_QOT_MARKET_HK_FUTURE,
    FUTU_QOT_MARKET_US,
    FUTU_QOT_MARKET_CNSH,
    FUTU_QOT_MARKET_CNSZ,
    FUTU_QOT_MARKET_SG,
    FUTU_QOT_MARKET_TO_CURRENCY,
    FUTU_TRD_MARKET_HK,
    FUTU_TRD_MARKET_US,
    FUTU_TRD_MARKET_CN,
    FUTU_TRD_MARKET_HKCC,
    FUTU_TRD_SEC_MARKET_HK,
    FUTU_TRD_SEC_MARKET_US,
    FUTU_TRD_SEC_MARKET_CN_SH,
    FUTU_TRD_SEC_MARKET_CN_SZ,
    FUTU_TRD_SEC_MARKET_SG,
    FUTU_TRD_SEC_MARKET_TO_QOT_MARKET,
    FUTU_SUB_TYPE_BASIC,
    FUTU_SUB_TYPE_ORDER_BOOK,
    FUTU_SUB_TYPE_TICKER,
    FUTU_SUB_TYPE_RT,
    FUTU_SUB_TYPE_KL_DAY,
    FUTU_SUB_TYPE_KL_5MIN,
    FUTU_SUB_TYPE_KL_15MIN,
    FUTU_SUB_TYPE_KL_30MIN,
    FUTU_SUB_TYPE_KL_60MIN,
    FUTU_SUB_TYPE_KL_1MIN,
    FUTU_KL_TYPE_1MIN,
    FUTU_KL_TYPE_DAY,
    FUTU_KL_TYPE_WEEK,
    FUTU_KL_TYPE_MONTH,
    FUTU_KL_TYPE_5MIN,
    FUTU_KL_TYPE_15MIN,
    FUTU_KL_TYPE_30MIN,
    FUTU_KL_TYPE_60MIN,
    FUTU_ORDER_TYPE_NORMAL,
    FUTU_ORDER_TYPE_MARKET,
    FUTU_ORDER_TYPE_ABSOLUTE_LIMIT,
    FUTU_ORDER_TYPE_AUCTION,
    FUTU_TRD_SIDE_BUY,
    FUTU_TRD_SIDE_SELL,
    FUTU_TRD_SIDE_SELL_SHORT,
    FUTU_TRD_SIDE_BUY_BACK,
    FUTU_TRD_ENV_SIMULATE,
    FUTU_TRD_ENV_REAL,
    FUTU_TICKER_DIR_BID,
    FUTU_TICKER_DIR_ASK,
    FUTU_OPTION_TYPE_CALL,
    FUTU_OPTION_TYPE_PUT,
    FUTU_PROTO_BASIC_QOT,
    FUTU_PROTO_KL,
    FUTU_PROTO_TICKER,
    FUTU_PROTO_ORDER_BOOK,
    FUTU_PROTO_TRD_ORDER,
    FUTU_PROTO_TRD_FILL,
)


class TestVenueMappingConsistency:
    """Verify FUTU_MARKET_TO_VENUE and VENUE_TO_FUTU_MARKET are consistent."""

    def test_venue_to_market_roundtrip(self):
        """Every venue in VENUE_TO_FUTU_MARKET should map back correctly."""
        for venue, market in VENUE_TO_FUTU_MARKET.items():
            assert market in FUTU_MARKET_TO_VENUE
            # NASDAQ and NYSE both map to market=11, which maps back to NYSE
            if venue == NASDAQ_VENUE:
                assert FUTU_MARKET_TO_VENUE[market] == NYSE_VENUE
            else:
                assert FUTU_MARKET_TO_VENUE[market] == venue

    def test_market_to_venue_known_entries(self):
        assert FUTU_MARKET_TO_VENUE[1] == HKEX_VENUE
        assert FUTU_MARKET_TO_VENUE[2] == HKEX_VENUE
        assert FUTU_MARKET_TO_VENUE[11] == NYSE_VENUE
        assert FUTU_MARKET_TO_VENUE[21] == SSE_VENUE
        assert FUTU_MARKET_TO_VENUE[22] == SZSE_VENUE
        assert FUTU_MARKET_TO_VENUE[31] == SGX_VENUE

    def test_venue_to_market_known_entries(self):
        assert VENUE_TO_FUTU_MARKET[HKEX_VENUE] == 1
        assert VENUE_TO_FUTU_MARKET[NYSE_VENUE] == 11
        assert VENUE_TO_FUTU_MARKET[NASDAQ_VENUE] == 11
        assert VENUE_TO_FUTU_MARKET[SSE_VENUE] == 21
        assert VENUE_TO_FUTU_MARKET[SZSE_VENUE] == 22
        assert VENUE_TO_FUTU_MARKET[SGX_VENUE] == 31


class TestTrdMarketConstants:
    """Verify trading market constants match Futu protocol."""

    def test_values(self):
        assert FUTU_TRD_MARKET_HK == 1
        assert FUTU_TRD_MARKET_US == 2
        assert FUTU_TRD_MARKET_CN == 3
        assert FUTU_TRD_MARKET_HKCC == 4


class TestSubTypeConstants:
    """Verify subscription type constants."""

    def test_values(self):
        assert FUTU_SUB_TYPE_BASIC == 1
        assert FUTU_SUB_TYPE_ORDER_BOOK == 2
        assert FUTU_SUB_TYPE_TICKER == 4
        assert FUTU_SUB_TYPE_RT == 5
        assert FUTU_SUB_TYPE_KL_DAY == 6
        assert FUTU_SUB_TYPE_KL_5MIN == 7
        assert FUTU_SUB_TYPE_KL_15MIN == 8
        assert FUTU_SUB_TYPE_KL_30MIN == 9
        assert FUTU_SUB_TYPE_KL_60MIN == 10
        assert FUTU_SUB_TYPE_KL_1MIN == 11

    def test_all_unique(self):
        values = [
            FUTU_SUB_TYPE_BASIC, FUTU_SUB_TYPE_ORDER_BOOK, FUTU_SUB_TYPE_TICKER,
            FUTU_SUB_TYPE_RT, FUTU_SUB_TYPE_KL_DAY, FUTU_SUB_TYPE_KL_5MIN,
            FUTU_SUB_TYPE_KL_15MIN, FUTU_SUB_TYPE_KL_30MIN, FUTU_SUB_TYPE_KL_60MIN,
            FUTU_SUB_TYPE_KL_1MIN,
        ]
        assert len(values) == len(set(values))


class TestKLTypeConstants:
    """Verify K-line type constants."""

    def test_values(self):
        assert FUTU_KL_TYPE_1MIN == 1
        assert FUTU_KL_TYPE_DAY == 2
        assert FUTU_KL_TYPE_WEEK == 3
        assert FUTU_KL_TYPE_MONTH == 4
        assert FUTU_KL_TYPE_5MIN == 6
        assert FUTU_KL_TYPE_15MIN == 7
        assert FUTU_KL_TYPE_30MIN == 8
        assert FUTU_KL_TYPE_60MIN == 9

    def test_all_unique(self):
        values = [
            FUTU_KL_TYPE_1MIN, FUTU_KL_TYPE_DAY, FUTU_KL_TYPE_WEEK,
            FUTU_KL_TYPE_MONTH, FUTU_KL_TYPE_5MIN, FUTU_KL_TYPE_15MIN,
            FUTU_KL_TYPE_30MIN, FUTU_KL_TYPE_60MIN,
        ]
        assert len(values) == len(set(values))


class TestOrderConstants:
    """Verify order-related constants."""

    def test_order_types(self):
        assert FUTU_ORDER_TYPE_NORMAL == 1
        assert FUTU_ORDER_TYPE_MARKET == 2
        assert FUTU_ORDER_TYPE_ABSOLUTE_LIMIT == 5
        assert FUTU_ORDER_TYPE_AUCTION == 6

    def test_trd_sides(self):
        assert FUTU_TRD_SIDE_BUY == 1
        assert FUTU_TRD_SIDE_SELL == 2
        assert FUTU_TRD_SIDE_SELL_SHORT == 3
        assert FUTU_TRD_SIDE_BUY_BACK == 4

    def test_trd_envs(self):
        assert FUTU_TRD_ENV_SIMULATE == 0
        assert FUTU_TRD_ENV_REAL == 1


class TestQotMarketConstants:
    """Verify QotMarket constants and currency mapping."""

    def test_values(self):
        assert FUTU_QOT_MARKET_HK == 1
        assert FUTU_QOT_MARKET_HK_FUTURE == 2
        assert FUTU_QOT_MARKET_US == 11
        assert FUTU_QOT_MARKET_CNSH == 21
        assert FUTU_QOT_MARKET_CNSZ == 22
        assert FUTU_QOT_MARKET_SG == 31

    def test_currency_mapping_known_markets(self):
        assert FUTU_QOT_MARKET_TO_CURRENCY[FUTU_QOT_MARKET_HK] == "HKD"
        assert FUTU_QOT_MARKET_TO_CURRENCY[FUTU_QOT_MARKET_HK_FUTURE] == "HKD"
        assert FUTU_QOT_MARKET_TO_CURRENCY[FUTU_QOT_MARKET_US] == "USD"
        assert FUTU_QOT_MARKET_TO_CURRENCY[FUTU_QOT_MARKET_CNSH] == "CNY"
        assert FUTU_QOT_MARKET_TO_CURRENCY[FUTU_QOT_MARKET_CNSZ] == "CNY"
        assert FUTU_QOT_MARKET_TO_CURRENCY[FUTU_QOT_MARKET_SG] == "SGD"

    def test_currency_mapping_covers_all_markets(self):
        """All QotMarket values used in FUTU_MARKET_TO_VENUE should have a currency."""
        for market in FUTU_MARKET_TO_VENUE:
            assert market in FUTU_QOT_MARKET_TO_CURRENCY


class TestTrdSecMarketMapping:
    """Verify TrdSecMarket -> QotMarket mapping."""

    def test_known_mappings(self):
        assert FUTU_TRD_SEC_MARKET_TO_QOT_MARKET[FUTU_TRD_SEC_MARKET_HK] == FUTU_QOT_MARKET_HK
        assert FUTU_TRD_SEC_MARKET_TO_QOT_MARKET[FUTU_TRD_SEC_MARKET_US] == FUTU_QOT_MARKET_US
        assert FUTU_TRD_SEC_MARKET_TO_QOT_MARKET[FUTU_TRD_SEC_MARKET_CN_SH] == FUTU_QOT_MARKET_CNSH
        assert FUTU_TRD_SEC_MARKET_TO_QOT_MARKET[FUTU_TRD_SEC_MARKET_CN_SZ] == FUTU_QOT_MARKET_CNSZ
        assert FUTU_TRD_SEC_MARKET_TO_QOT_MARKET[FUTU_TRD_SEC_MARKET_SG] == FUTU_QOT_MARKET_SG

    def test_all_sec_markets_map_to_valid_qot_market(self):
        """Every TrdSecMarket should map to a QotMarket in FUTU_MARKET_TO_VENUE."""
        for sec_market, qot_market in FUTU_TRD_SEC_MARKET_TO_QOT_MARKET.items():
            assert qot_market in FUTU_MARKET_TO_VENUE, (
                f"TrdSecMarket {sec_market} maps to QotMarket {qot_market} "
                f"which has no venue mapping"
            )


class TestTickerDirectionConstants:
    """Verify ticker direction constants."""

    def test_values(self):
        assert FUTU_TICKER_DIR_BID == 1
        assert FUTU_TICKER_DIR_ASK == 2

    def test_distinct(self):
        assert FUTU_TICKER_DIR_BID != FUTU_TICKER_DIR_ASK


class TestOptionTypeConstants:
    """Verify option type constants."""

    def test_values(self):
        assert FUTU_OPTION_TYPE_CALL == 1
        assert FUTU_OPTION_TYPE_PUT == 2

    def test_distinct(self):
        assert FUTU_OPTION_TYPE_CALL != FUTU_OPTION_TYPE_PUT


class TestProtocolIdConstants:
    """Verify push protocol ID constants."""

    def test_values(self):
        assert FUTU_PROTO_BASIC_QOT == 3005
        assert FUTU_PROTO_KL == 3007
        assert FUTU_PROTO_TICKER == 3011
        assert FUTU_PROTO_ORDER_BOOK == 3013
        assert FUTU_PROTO_TRD_ORDER == 2208
        assert FUTU_PROTO_TRD_FILL == 2218

    def test_all_unique(self):
        values = [
            FUTU_PROTO_BASIC_QOT, FUTU_PROTO_KL, FUTU_PROTO_TICKER,
            FUTU_PROTO_ORDER_BOOK, FUTU_PROTO_TRD_ORDER, FUTU_PROTO_TRD_FILL,
        ]
        assert len(values) == len(set(values))
