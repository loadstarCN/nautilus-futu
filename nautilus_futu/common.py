"""Common utilities for Futu OpenD adapter."""

from __future__ import annotations

from nautilus_trader.model.identifiers import InstrumentId, Symbol

from nautilus_futu.constants import (
    FUTU_MARKET_TO_VENUE,
    FUTU_NOTIFY_TYPE_CONN_STATUS,
    FUTU_NOTIFY_TYPE_GTW_EVENT,
    FUTU_NOTIFY_TYPE_PROGRAM_STATUS,
    FUTU_NOTIFY_TYPE_USED_QUOTA,
    FUTU_VENUE,
    VENUE_TO_FUTU_MARKET,
)


def log_futu_notify(log, data: dict) -> None:
    """Log an OpenD ``Notify`` (proto 1003) push at an appropriate level.

    ``log`` is a Nautilus component logger (``self._log``).  Shared by the data
    and execution clients so whichever one owns the connection reports gateway
    events, connection status and quota usage.
    """
    ntype = data.get("type")
    if ntype == FUTU_NOTIFY_TYPE_GTW_EVENT:
        event = data.get("event") or {}
        log.warning(f"OpenD gateway event {event.get('event_type')}: {event.get('desc')}")
    elif ntype == FUTU_NOTIFY_TYPE_CONN_STATUS:
        status = data.get("connect_status") or {}
        level = log.info if status.get("qot_logined") else log.warning
        level(
            f"OpenD connection status: qot_logined={status.get('qot_logined')} "
            f"trd_logined={status.get('trd_logined')}",
        )
    elif ntype == FUTU_NOTIFY_TYPE_PROGRAM_STATUS:
        status = data.get("program_status") or {}
        log.info(f"OpenD program status: type={status.get('type')} {status.get('desc') or ''}")
    elif ntype == FUTU_NOTIFY_TYPE_USED_QUOTA:
        quota = data.get("used_quota") or {}
        log.info(
            f"OpenD quota used: subscriptions={quota.get('used_sub_quota')} "
            f"history_kl={quota.get('used_kline_quota')}",
        )
    else:
        log.debug(f"OpenD notify: {data}")


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
