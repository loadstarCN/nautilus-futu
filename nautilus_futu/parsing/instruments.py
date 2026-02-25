"""Parse Futu instrument data to NautilusTrader instruments."""

from __future__ import annotations

import logging
from typing import Any

from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments import Equity, FuturesContract, OptionContract
from nautilus_trader.model.enums import AssetClass, OptionKind
from nautilus_trader.model.objects import Currency, Price, Quantity

from nautilus_futu.common import futu_security_to_instrument_id
from nautilus_futu.constants import (
    FUTU_OPTION_TYPE_CALL,
    FUTU_QOT_MARKET_TO_CURRENCY,
)

logger = logging.getLogger(__name__)

# Market-based default price precision (used when price_spread is unavailable)
_MARKET_PRECISION: dict[int, tuple[int, str]] = {
    1: (3, "0.001"),   # HK
    2: (3, "0.001"),   # HK_FUTURE
    11: (2, "0.01"),   # US
    12: (2, "0.01"),   # US_OPTION
    21: (2, "0.01"),   # CN_SH
    22: (2, "0.01"),   # CN_SZ
    31: (3, "0.001"),  # SG
}
_DEFAULT_PRECISION = (3, "0.001")


def _precision_from_spread(spread: float | None, market: int = 0) -> tuple[int, str]:
    """Derive price precision and increment from tick spread.

    Falls back to market-based defaults when spread is unavailable or zero.
    """
    if spread is not None and spread > 0:
        s = f"{spread:.10f}".rstrip("0")
        decimals = len(s.split(".")[-1]) if "." in s else 0
        return decimals, str(spread)
    return _MARKET_PRECISION.get(market, _DEFAULT_PRECISION)


# Futu SecurityType constants
_SEC_TYPE_STOCK = 3
_SEC_TYPE_ETF = 4
_SEC_TYPE_WARRANT = 5
_SEC_TYPE_CBBC = 6
_SEC_TYPE_OPTION = 7
_SEC_TYPE_FUTURE = 8


def _determine_currency(market: int) -> Currency:
    """Determine currency based on Futu market code."""
    return Currency.from_str(FUTU_QOT_MARKET_TO_CURRENCY.get(market, "USD"))


def parse_futu_instrument(
    static_info: dict[str, Any],
) -> Equity | OptionContract | FuturesContract | None:
    """Parse Futu static info dict to NautilusTrader instrument.

    Dispatches by sec_type:
    - 3 (STOCK), 4 (ETF), 5 (WARRANT), 6 (CBBC) -> Equity
    - 7 (OPTION) -> OptionContract
    - 8 (FUTURE) -> FuturesContract

    Parameters
    ----------
    static_info : dict
        Static info dictionary from Futu API.

    Returns
    -------
    Equity | OptionContract | FuturesContract | None
    """
    try:
        market = static_info.get("market", 0)
        code = static_info.get("code", "")
        sec_type = static_info.get("sec_type", _SEC_TYPE_STOCK)

        instrument_id = futu_security_to_instrument_id(market, code)
        currency = _determine_currency(market)

        if sec_type == _SEC_TYPE_OPTION:
            return _parse_futu_option(static_info, instrument_id, currency)
        elif sec_type == _SEC_TYPE_FUTURE:
            return _parse_futu_future(static_info, instrument_id, currency)
        elif sec_type in (_SEC_TYPE_STOCK, _SEC_TYPE_ETF, _SEC_TYPE_WARRANT, _SEC_TYPE_CBBC):
            return _parse_futu_equity(static_info, instrument_id, currency)
        else:
            logger.warning("Unknown sec_type %d for %s, treating as Equity", sec_type, code)
            return _parse_futu_equity(static_info, instrument_id, currency)
    except Exception as e:
        logger.warning("Failed to parse instrument: %s", e)
        return None


def _parse_futu_equity(
    static_info: dict[str, Any],
    instrument_id: InstrumentId,
    currency: Currency,
) -> Equity:
    """Parse Futu static info to NautilusTrader Equity."""
    code = static_info.get("code", "")
    lot_size = static_info.get("lot_size", 1)
    market = static_info.get("market", 0)
    spread = static_info.get("price_spread")
    precision, increment = _precision_from_spread(spread, market)

    return Equity(
        instrument_id=instrument_id,
        raw_symbol=Symbol(code),
        currency=currency,
        price_precision=precision,
        price_increment=Price.from_str(increment),
        lot_size=Quantity.from_int(lot_size),
        ts_event=0,
        ts_init=0,
    )


def _parse_futu_option(
    static_info: dict[str, Any],
    instrument_id: InstrumentId,
    currency: Currency,
) -> OptionContract:
    """Parse Futu static info to NautilusTrader OptionContract."""
    code = static_info.get("code", "")
    lot_size = static_info.get("lot_size", 1)

    # Option-specific fields from get_static_info extended data
    futu_option_type = static_info.get("option_type", FUTU_OPTION_TYPE_CALL)
    option_kind = OptionKind.CALL if futu_option_type == FUTU_OPTION_TYPE_CALL else OptionKind.PUT

    strike_price_val = static_info.get("strike_price", 0.0)
    strike_timestamp = static_info.get("strike_timestamp", 0.0)

    # Underlying from option_owner fields
    owner_code = static_info.get("option_owner_code", "")

    # Convert strike_timestamp to nanoseconds for expiration_ns
    expiration_ns = int(strike_timestamp * 1e9) if strike_timestamp else 0

    market = static_info.get("market", 0)
    spread = static_info.get("price_spread")
    precision, increment = _precision_from_spread(spread, market)

    return OptionContract(
        instrument_id=instrument_id,
        raw_symbol=Symbol(code),
        asset_class=AssetClass.EQUITY,
        currency=currency,
        price_precision=precision,
        price_increment=Price.from_str(increment),
        multiplier=Quantity.from_int(lot_size),
        lot_size=Quantity.from_int(lot_size),
        underlying=owner_code,
        option_kind=option_kind,
        strike_price=Price.from_str(str(strike_price_val)),
        activation_ns=0,
        expiration_ns=expiration_ns,
        ts_event=0,
        ts_init=0,
    )


def _parse_futu_future(
    static_info: dict[str, Any],
    instrument_id: InstrumentId,
    currency: Currency,
) -> FuturesContract:
    """Parse Futu static info to NautilusTrader FuturesContract."""
    code = static_info.get("code", "")
    lot_size = static_info.get("lot_size", 1)

    # Future-specific fields
    last_trade_timestamp = static_info.get("last_trade_timestamp", 0.0)
    expiration_ns = int(last_trade_timestamp * 1e9) if last_trade_timestamp else 0

    market = static_info.get("market", 0)
    spread = static_info.get("price_spread")
    precision, increment = _precision_from_spread(spread, market)

    return FuturesContract(
        instrument_id=instrument_id,
        raw_symbol=Symbol(code),
        asset_class=AssetClass.INDEX,
        currency=currency,
        price_precision=precision,
        price_increment=Price.from_str(increment),
        multiplier=Quantity.from_int(lot_size),
        lot_size=Quantity.from_int(lot_size),
        underlying=code,
        activation_ns=0,
        expiration_ns=expiration_ns,
        ts_event=0,
        ts_init=0,
    )
