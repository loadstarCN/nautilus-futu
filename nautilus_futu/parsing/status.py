"""Map Futu market states (``Qot_Common.QotMarketState``) to ``InstrumentStatus``."""

from __future__ import annotations

from nautilus_trader.model.data import InstrumentStatus
from nautilus_trader.model.enums import MarketStatusAction
from nautilus_trader.model.identifiers import InstrumentId

from nautilus_futu.constants import (
    HKEX_VENUE,
    NASDAQ_VENUE,
    NYSE_VENUE,
    SGX_VENUE,
    SSE_VENUE,
    SZSE_VENUE,
)

_A = MarketStatusAction

# QotMarketState value -> (name, Nautilus action).  Extended-hours sessions
# (US pre/after/overnight, STAR after-hours) map to PRE_OPEN / POST_CLOSE so
# regular-session strategies do not mistake them for TRADING; the Futu state
# name is kept in `InstrumentStatus.trading_event` for finer handling.
FUTU_MARKET_STATES: dict[int, tuple[str, MarketStatusAction]] = {
    0: ("NONE", _A.CLOSE),
    1: ("AUCTION", _A.PRE_OPEN),
    2: ("WAITING_OPEN", _A.PRE_OPEN),
    3: ("MORNING", _A.TRADING),
    4: ("REST", _A.PAUSE),
    5: ("AFTERNOON", _A.TRADING),
    6: ("CLOSED", _A.CLOSE),
    8: ("PRE_MARKET_BEGIN", _A.PRE_OPEN),
    9: ("PRE_MARKET_END", _A.PRE_OPEN),
    10: ("AFTER_HOURS_BEGIN", _A.POST_CLOSE),
    11: ("AFTER_HOURS_END", _A.CLOSE),
    12: ("FUTU_SWITCH_DATE", _A.CLOSE),
    13: ("NIGHT_OPEN", _A.TRADING),
    14: ("NIGHT_END", _A.CLOSE),
    15: ("FUTURE_DAY_OPEN", _A.TRADING),
    16: ("FUTURE_DAY_BREAK", _A.PAUSE),
    17: ("FUTURE_DAY_CLOSE", _A.CLOSE),
    18: ("FUTURE_DAY_WAIT_FOR_OPEN", _A.PRE_OPEN),
    19: ("HK_CAS", _A.PRE_CLOSE),
    20: ("FUTURE_NIGHT_WAIT", _A.PRE_OPEN),
    21: ("FUTURE_AFTERNOON", _A.TRADING),
    22: ("FUTURE_SWITCH_DATE", _A.CLOSE),
    23: ("FUTURE_OPEN", _A.TRADING),
    24: ("FUTURE_BREAK", _A.PAUSE),
    25: ("FUTURE_BREAK_OVER", _A.TRADING),
    26: ("FUTURE_CLOSE", _A.CLOSE),
    27: ("STIB_AFTER_HOURS_WAIT", _A.POST_CLOSE),
    28: ("STIB_AFTER_HOURS_BEGIN", _A.POST_CLOSE),
    29: ("STIB_AFTER_HOURS_END", _A.CLOSE),
    30: ("CLOSE_AUCTION", _A.PRE_CLOSE),
    31: ("AFTERNOON_END", _A.CLOSE),
    32: ("NIGHT", _A.TRADING),
    33: ("OVERNIGHT_BEGIN", _A.POST_CLOSE),
    34: ("OVERNIGHT_END", _A.CLOSE),
    35: ("TRADE_AT_LAST", _A.PRE_CLOSE),
    36: ("TRADE_AUCTION", _A.PRE_CLOSE),
}


def market_state_field(instrument_id: InstrumentId, is_future: bool = False) -> str | None:
    """The ``get_global_state`` key holding the market state for an instrument."""
    venue = instrument_id.venue
    if venue == HKEX_VENUE:
        return "market_hk_future" if is_future else "market_hk"
    if venue in (NYSE_VENUE, NASDAQ_VENUE):
        return "market_us_future" if is_future else "market_us"
    if venue == SSE_VENUE:
        return "market_sh"
    if venue == SZSE_VENUE:
        return "market_sz"
    if venue == SGX_VENUE:
        return "market_sg_future"
    return None


def parse_futu_instrument_status(
    instrument_id: InstrumentId,
    market_state: int,
    ts_event: int,
    ts_init: int,
) -> InstrumentStatus:
    """Build an ``InstrumentStatus`` from a Futu ``QotMarketState`` value."""
    name, action = FUTU_MARKET_STATES.get(market_state, (f"UNKNOWN_{market_state}", _A.NONE))
    return InstrumentStatus(
        instrument_id=instrument_id,
        action=action,
        ts_event=ts_event,
        ts_init=ts_init,
        reason=None,
        trading_event=name,
    )
