"""Common utilities for Futu OpenD adapter."""

from __future__ import annotations

from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue

from nautilus_futu.constants import FUTU_MARKET_TO_VENUE, VENUE_TO_FUTU_MARKET, FUTU_VENUE


def futu_security_to_instrument_id(market: int, code: str) -> InstrumentId:
    """Convert Futu security (market, code) to NautilusTrader InstrumentId.

    Parameters
    ----------
    market : int
        Futu QotMarket value.
    code : str
        Futu security code (e.g., "00700", "AAPL").

    Returns
    -------
    InstrumentId
    """
    venue = FUTU_MARKET_TO_VENUE.get(market, FUTU_VENUE)
    return InstrumentId(Symbol(code), venue)


def instrument_id_to_futu_security(instrument_id: InstrumentId) -> tuple[int, str]:
    """Convert NautilusTrader InstrumentId to Futu security (market, code).

    Parameters
    ----------
    instrument_id : InstrumentId
        The NautilusTrader instrument ID.

    Returns
    -------
    tuple[int, str]
        (market, code) pair.
    """
    venue = instrument_id.venue
    market = VENUE_TO_FUTU_MARKET.get(venue, 0)
    code = instrument_id.symbol.value
    return market, code
