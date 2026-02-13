"""Parse Futu instrument data to NautilusTrader instruments."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.objects import Currency, Money, Price, Quantity

from nautilus_futu.common import futu_security_to_instrument_id

logger = logging.getLogger(__name__)


def parse_futu_instrument(static_info: dict[str, Any]) -> Equity | None:
    """Parse Futu static info dict to NautilusTrader Equity instrument.

    Parameters
    ----------
    static_info : dict
        Static info dictionary from Futu API.

    Returns
    -------
    Equity | None
    """
    try:
        market = static_info.get("market", 0)
        code = static_info.get("code", "")
        name = static_info.get("name", code)
        lot_size = static_info.get("lot_size", 1)

        instrument_id = futu_security_to_instrument_id(market, code)

        # Determine currency based on market
        if market == 1 or market == 2:  # HK
            currency = Currency.from_str("HKD")
        elif market == 11:  # US
            currency = Currency.from_str("USD")
        elif market in (21, 22):  # CN
            currency = Currency.from_str("CNY")
        elif market == 31:  # SG
            currency = Currency.from_str("SGD")
        else:
            currency = Currency.from_str("USD")

        return Equity(
            instrument_id=instrument_id,
            raw_symbol=Symbol(code),
            currency=currency,
            price_precision=3,
            price_increment=Price.from_str("0.001"),
            lot_size=Quantity.from_int(lot_size),
            ts_event=0,
            ts_init=0,
        )
    except Exception as e:
        logger.warning("Failed to parse instrument: %s", e)
        return None
