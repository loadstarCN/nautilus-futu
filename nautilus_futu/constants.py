"""Constants for Futu OpenD adapter."""

from nautilus_trader.model.identifiers import Venue

# Venue identifiers
FUTU_VENUE = Venue("FUTU")
HKEX_VENUE = Venue("HKEX")
NYSE_VENUE = Venue("NYSE")
NASDAQ_VENUE = Venue("NASDAQ")
SSE_VENUE = Venue("SSE")
SZSE_VENUE = Venue("SZSE")
SGX_VENUE = Venue("SGX")

# Futu QotMarket -> Venue mapping
FUTU_MARKET_TO_VENUE = {
    1: HKEX_VENUE,    # QotMarket_HK_Security
    2: HKEX_VENUE,    # QotMarket_HK_Future
    11: NYSE_VENUE,   # QotMarket_US_Security (default, override per exchange)
    21: SSE_VENUE,    # QotMarket_CNSH_Security
    22: SZSE_VENUE,   # QotMarket_CNSZ_Security
    31: SGX_VENUE,    # QotMarket_SG_Security
}

# Venue -> Futu QotMarket mapping
VENUE_TO_FUTU_MARKET = {
    HKEX_VENUE: 1,
    NYSE_VENUE: 11,
    NASDAQ_VENUE: 11,
    SSE_VENUE: 21,
    SZSE_VENUE: 22,
    SGX_VENUE: 31,
}

# Futu TrdMarket values
FUTU_TRD_MARKET_HK = 1
FUTU_TRD_MARKET_US = 2
FUTU_TRD_MARKET_CN = 3
FUTU_TRD_MARKET_HKCC = 4

# Futu SubType values
FUTU_SUB_TYPE_BASIC = 1
FUTU_SUB_TYPE_ORDER_BOOK = 2
FUTU_SUB_TYPE_TICKER = 4
FUTU_SUB_TYPE_RT = 5
FUTU_SUB_TYPE_KL_DAY = 6
FUTU_SUB_TYPE_KL_5MIN = 7
FUTU_SUB_TYPE_KL_15MIN = 8
FUTU_SUB_TYPE_KL_30MIN = 9
FUTU_SUB_TYPE_KL_60MIN = 10
FUTU_SUB_TYPE_KL_1MIN = 11

# Futu KLType values
FUTU_KL_TYPE_1MIN = 1
FUTU_KL_TYPE_DAY = 2
FUTU_KL_TYPE_WEEK = 3
FUTU_KL_TYPE_MONTH = 4
FUTU_KL_TYPE_5MIN = 6
FUTU_KL_TYPE_15MIN = 7
FUTU_KL_TYPE_30MIN = 8
FUTU_KL_TYPE_60MIN = 9

# Futu OrderType values
FUTU_ORDER_TYPE_NORMAL = 1
FUTU_ORDER_TYPE_MARKET = 2
FUTU_ORDER_TYPE_ABSOLUTE_LIMIT = 5
FUTU_ORDER_TYPE_AUCTION = 6

# Futu TrdSide values
FUTU_TRD_SIDE_BUY = 1
FUTU_TRD_SIDE_SELL = 2
FUTU_TRD_SIDE_SELL_SHORT = 3
FUTU_TRD_SIDE_BUY_BACK = 4

# Futu TrdEnv values
FUTU_TRD_ENV_SIMULATE = 0
FUTU_TRD_ENV_REAL = 1
