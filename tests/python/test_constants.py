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
    FUTU_TRD_MARKET_HK,
    FUTU_TRD_MARKET_US,
    FUTU_TRD_MARKET_CN,
    FUTU_TRD_MARKET_HKCC,
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
