"""Parse Futu instrument data to NautilusTrader instruments."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from nautilus_trader.model.enums import AssetClass, OptionKind
from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments import Equity, FuturesContract, OptionContract
from nautilus_trader.model.objects import Currency, Price, Quantity

from nautilus_futu.common import futu_security_to_instrument_id
from nautilus_futu.constants import (
    FUTU_OPTION_TYPE_CALL,
    FUTU_QOT_MARKET_HK,
    FUTU_QOT_MARKET_HK_FUTURE,
    FUTU_QOT_MARKET_TO_CURRENCY,
    FUTU_SEC_TYPE_DRVT,
    FUTU_SEC_TYPE_ETF,
    FUTU_SEC_TYPE_FUTURE,
    FUTU_SEC_TYPE_STOCK,
    FUTU_SEC_TYPE_WARRANT,
)
from nautilus_futu.parsing.market_data import infer_precision

logger = logging.getLogger(__name__)

# Market-based minimum price precision.  Futu's `price_spread` is the tick for
# the *current* price band only (HK spreads change with price), so the finest
# tick of the market is used as the instrument precision and strategies should
# round to the live band with `hk_tick_size()` when needed.
_MARKET_PRECISION: dict[int, int] = {
    1: 3,   # HK (finest tick 0.001)
    2: 3,   # HK_FUTURE
    11: 2,  # US
    12: 2,  # US_OPTION
    21: 2,  # CN_SH
    22: 2,  # CN_SZ
    31: 3,  # SG
}
_DEFAULT_PRECISION = 3

# HKEX spread table (price band lower bound -> tick size), HKD
HK_TICK_TABLE: tuple[tuple[float, float], ...] = (
    (0.01, 0.001),
    (0.25, 0.005),
    (0.50, 0.010),
    (10.00, 0.020),
    (20.00, 0.050),
    (100.00, 0.100),
    (200.00, 0.200),
    (500.00, 0.500),
    (1000.00, 1.000),
    (2000.00, 2.000),
    (5000.00, 5.000),
)

# Backwards-compatible aliases (sec_type constants used to live here)
_SEC_TYPE_STOCK = FUTU_SEC_TYPE_STOCK
_SEC_TYPE_ETF = FUTU_SEC_TYPE_ETF
_SEC_TYPE_WARRANT = FUTU_SEC_TYPE_WARRANT
_SEC_TYPE_CBBC = 6  # legacy adapter value, kept for callers passing it
_SEC_TYPE_OPTION = 7  # legacy adapter value
_SEC_TYPE_FUTURE = 8  # legacy adapter value

# sec_type -> instrument family.  Both the official Qot_Common.SecurityType
# values (DRVT=8 options, FUTURE=10) and the legacy adapter values (7/8) are
# accepted; ambiguity on 8 is resolved by looking at the extended data.
_EQUITY_SEC_TYPES = frozenset({FUTU_SEC_TYPE_STOCK, FUTU_SEC_TYPE_ETF, FUTU_SEC_TYPE_WARRANT, _SEC_TYPE_CBBC, 2})


def hk_tick_size(price: float) -> float:
    """Return the HKEX tick size for the price band containing ``price``."""
    tick = HK_TICK_TABLE[0][1]
    for lower, size in HK_TICK_TABLE:
        if price >= lower:
            tick = size
        else:
            break
    return tick


def _precision_from_spread(spread: float | None, market: int = 0) -> tuple[int, str]:
    """Derive price precision and increment.

    The precision is the finer of the market's finest tick and the spread
    reported by OpenD; the increment is ``10**-precision``.
    """
    precision = _MARKET_PRECISION.get(market, _DEFAULT_PRECISION)
    if spread is not None and spread > 0:
        precision = max(precision, infer_precision(spread))
    precision = min(precision, 9)
    increment = f"{10 ** -precision:.{precision}f}" if precision > 0 else "1"
    return precision, increment


def _determine_currency(market: int) -> Currency:
    """Determine currency based on Futu market code."""
    return Currency.from_str(FUTU_QOT_MARKET_TO_CURRENCY.get(market, "USD"))


def _instrument_family(static_info: dict[str, Any]) -> str:
    sec_type = static_info.get("sec_type", FUTU_SEC_TYPE_STOCK)
    if "option_owner_code" in static_info or "strike_price" in static_info or sec_type in (FUTU_SEC_TYPE_DRVT, _SEC_TYPE_OPTION):
        if sec_type == FUTU_SEC_TYPE_DRVT and "last_trade_timestamp" in static_info and "strike_price" not in static_info:
            return "future"
        return "option"
    if sec_type == FUTU_SEC_TYPE_FUTURE or "last_trade_timestamp" in static_info or "is_main_contract" in static_info:
        return "future"
    if sec_type in _EQUITY_SEC_TYPES:
        return "equity"
    logger.warning("Unknown sec_type %s for %s, treating as Equity", sec_type, static_info.get("code"))
    return "equity"


def parse_futu_instrument(
    static_info: dict[str, Any],
    ts_init: int = 0,
) -> Equity | OptionContract | FuturesContract | None:
    """Parse Futu static info dict to NautilusTrader instrument.

    Dispatches by ``sec_type`` and the presence of option/future extended data:
    stocks/ETFs/warrants/CBBCs -> ``Equity``; options -> ``OptionContract``;
    futures -> ``FuturesContract``.
    """
    try:
        market = static_info.get("market", 0)
        code = static_info.get("code", "")
        instrument_id = futu_security_to_instrument_id(market, code)
        currency = _determine_currency(market)

        family = _instrument_family(static_info)
        if family == "option":
            return _parse_futu_option(static_info, instrument_id, currency, ts_init)
        if family == "future":
            return _parse_futu_future(static_info, instrument_id, currency, ts_init)
        return _parse_futu_equity(static_info, instrument_id, currency, ts_init)
    except Exception as e:
        logger.warning("Failed to parse instrument: %s", e)
        return None


def _parse_futu_equity(
    static_info: dict[str, Any],
    instrument_id: InstrumentId,
    currency: Currency,
    ts_init: int = 0,
) -> Equity:
    """Parse Futu static info to NautilusTrader Equity."""
    code = static_info.get("code", "")
    lot_size = static_info.get("lot_size", 1) or 1
    market = static_info.get("market", 0)
    spread = static_info.get("price_spread")
    precision, increment = _precision_from_spread(spread, market)

    return Equity(
        instrument_id=instrument_id,
        raw_symbol=Symbol(code),
        currency=currency,
        price_precision=precision,
        price_increment=Price.from_str(increment),
        lot_size=Quantity.from_int(int(lot_size)),
        ts_event=ts_init,
        ts_init=ts_init,
    )


def _parse_time_string_ns(value: str | None) -> int:
    """Parse ``YYYY-MM-DD`` / ``YYYY-MM-DD HH:MM:SS`` (treated as UTC) to nanoseconds."""
    if not value:
        return 0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt).replace(tzinfo=UTC)
            return int(dt.timestamp() * 1_000_000_000)
        except ValueError:
            continue
    return 0


def _parse_futu_option(
    static_info: dict[str, Any],
    instrument_id: InstrumentId,
    currency: Currency,
    ts_init: int = 0,
) -> OptionContract:
    """Parse Futu static info to NautilusTrader OptionContract."""
    code = static_info.get("code", "")
    lot_size = static_info.get("lot_size", 1) or 1

    futu_option_type = static_info.get("option_type", FUTU_OPTION_TYPE_CALL)
    option_kind = OptionKind.CALL if futu_option_type == FUTU_OPTION_TYPE_CALL else OptionKind.PUT

    strike_price_val = static_info.get("strike_price", 0.0) or 0.0
    strike_timestamp = static_info.get("strike_timestamp", 0.0) or 0.0
    expiration_ns = int(strike_timestamp * 1e9) if strike_timestamp else _parse_time_string_ns(static_info.get("strike_time"))

    owner_code = static_info.get("option_owner_code", "") or code

    market = static_info.get("market", 0)
    spread = static_info.get("price_spread")
    precision, increment = _precision_from_spread(spread, market)
    strike_precision = max(precision, infer_precision(float(strike_price_val)))

    return OptionContract(
        instrument_id=instrument_id,
        raw_symbol=Symbol(code),
        asset_class=AssetClass.EQUITY,
        currency=currency,
        price_precision=precision,
        price_increment=Price.from_str(increment),
        multiplier=Quantity.from_int(int(lot_size)),
        lot_size=Quantity.from_int(1),
        underlying=owner_code,
        option_kind=option_kind,
        strike_price=Price(round(float(strike_price_val), strike_precision), strike_precision),
        activation_ns=0,
        expiration_ns=expiration_ns,
        ts_event=ts_init,
        ts_init=ts_init,
    )


def _parse_futu_future(
    static_info: dict[str, Any],
    instrument_id: InstrumentId,
    currency: Currency,
    ts_init: int = 0,
) -> FuturesContract:
    """Parse Futu static info to NautilusTrader FuturesContract."""
    code = static_info.get("code", "")
    lot_size = static_info.get("lot_size", 1) or 1

    last_trade_timestamp = static_info.get("last_trade_timestamp", 0.0) or 0.0
    expiration_ns = int(last_trade_timestamp * 1e9) if last_trade_timestamp else _parse_time_string_ns(static_info.get("last_trade_time"))

    market = static_info.get("market", 0)
    spread = static_info.get("price_spread")
    precision, increment = _precision_from_spread(spread, market)
    asset_class = AssetClass.INDEX if market in (FUTU_QOT_MARKET_HK, FUTU_QOT_MARKET_HK_FUTURE) else AssetClass.COMMODITY
    underlying = static_info.get("owner_code") or code

    return FuturesContract(
        instrument_id=instrument_id,
        raw_symbol=Symbol(code),
        asset_class=asset_class,
        currency=currency,
        price_precision=precision,
        price_increment=Price.from_str(increment),
        multiplier=Quantity.from_int(int(lot_size)),
        lot_size=Quantity.from_int(1),
        underlying=underlying,
        activation_ns=0,
        expiration_ns=expiration_ns,
        ts_event=ts_init,
        ts_init=ts_init,
    )


def parse_option_chain(
    chain: list[dict[str, Any]],
    owner_market: int,
    owner_code: str,
    ts_init: int = 0,
) -> list[OptionContract]:
    """Convert ``PyFutuClient.get_option_chain`` output into ``OptionContract`` objects.

    Each chain item has ``strike_time``/``strike_timestamp`` and an
    ``option_list`` of ``{"call": {...}, "put": {...}}`` dicts.
    """
    contracts: list[OptionContract] = []
    for expiry in chain:
        strike_time = expiry.get("strike_time")
        strike_timestamp = expiry.get("strike_timestamp")
        for item in expiry.get("option_list", []):
            for leg in ("call", "put"):
                info = item.get(leg)
                if not info:
                    continue
                static = dict(info)
                static.setdefault("strike_time", strike_time)
                if strike_timestamp:
                    static.setdefault("strike_timestamp", strike_timestamp)
                static.setdefault("option_owner_code", owner_code)
                static.setdefault("option_owner_market", owner_market)
                static.setdefault("option_type", FUTU_OPTION_TYPE_CALL if leg == "call" else 2)
                static["sec_type"] = FUTU_SEC_TYPE_DRVT
                parsed = parse_futu_instrument(static, ts_init)
                if isinstance(parsed, OptionContract):
                    contracts.append(parsed)
    return contracts
