"""Parse Futu market data to NautilusTrader data types."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from nautilus_trader.model.data import (
    Bar,
    BarSpecification,
    BarType,
    BookOrder,
    OrderBookDelta,
    OrderBookDeltas,
    QuoteTick,
    TradeTick,
)
from nautilus_trader.model.enums import (
    AggregationSource,
    AggressorSide,
    BarAggregation,
    BookAction,
    OrderSide,
    PriceType,
)
from nautilus_trader.model.identifiers import InstrumentId, TradeId
from nautilus_trader.model.objects import Price, Quantity

from nautilus_futu.common import futu_security_to_instrument_id
from nautilus_futu.constants import (
    FUTU_KL_TYPE_1MIN,
    FUTU_KL_TYPE_5MIN,
    FUTU_KL_TYPE_15MIN,
    FUTU_KL_TYPE_30MIN,
    FUTU_KL_TYPE_60MIN,
    FUTU_KL_TYPE_DAY,
    FUTU_SUB_TYPE_KL_1MIN,
    FUTU_SUB_TYPE_KL_5MIN,
    FUTU_SUB_TYPE_KL_15MIN,
    FUTU_SUB_TYPE_KL_30MIN,
    FUTU_SUB_TYPE_KL_60MIN,
    FUTU_SUB_TYPE_KL_DAY,
    FUTU_TICKER_DIR_ASK,
    FUTU_TICKER_DIR_BID,
)


def bar_spec_to_futu_sub_type(spec: BarSpecification) -> int | None:
    """Convert NautilusTrader BarSpecification to Futu SubType."""
    if spec.aggregation == BarAggregation.MINUTE:
        mapping = {
            1: FUTU_SUB_TYPE_KL_1MIN,
            5: FUTU_SUB_TYPE_KL_5MIN,
            15: FUTU_SUB_TYPE_KL_15MIN,
            30: FUTU_SUB_TYPE_KL_30MIN,
            60: FUTU_SUB_TYPE_KL_60MIN,
        }
        return mapping.get(spec.step)
    elif spec.aggregation == BarAggregation.HOUR:
        if spec.step == 1:
            return FUTU_SUB_TYPE_KL_60MIN
        return None
    elif spec.aggregation == BarAggregation.DAY:
        return FUTU_SUB_TYPE_KL_DAY
    return None


def bar_spec_to_futu_kl_type(spec: BarSpecification) -> int | None:
    """Convert NautilusTrader BarSpecification to Futu KLType."""
    if spec.aggregation == BarAggregation.MINUTE:
        mapping = {
            1: FUTU_KL_TYPE_1MIN,
            5: FUTU_KL_TYPE_5MIN,
            15: FUTU_KL_TYPE_15MIN,
            30: FUTU_KL_TYPE_30MIN,
            60: FUTU_KL_TYPE_60MIN,
        }
        return mapping.get(spec.step)
    elif spec.aggregation == BarAggregation.HOUR:
        if spec.step == 1:
            return FUTU_KL_TYPE_60MIN
        return None
    elif spec.aggregation == BarAggregation.DAY:
        return FUTU_KL_TYPE_DAY
    return None


def parse_futu_quote_tick(
    data: dict[str, Any],
    instrument_id: InstrumentId,
    ts_init: int,
) -> QuoteTick:
    """Parse Futu basic quote to NautilusTrader QuoteTick."""
    return QuoteTick(
        instrument_id=instrument_id,
        bid_price=Price.from_str(str(data.get("cur_price", 0))),
        ask_price=Price.from_str(str(data.get("cur_price", 0))),
        bid_size=Quantity.from_int(data.get("volume", 0)),
        ask_size=Quantity.from_int(data.get("volume", 0)),
        ts_event=ts_init,
        ts_init=ts_init,
    )


def parse_futu_trade_tick(
    data: dict[str, Any],
    instrument_id: InstrumentId,
    ts_init: int,
) -> TradeTick:
    """Parse Futu ticker to NautilusTrader TradeTick."""
    direction = data.get("dir", 0)
    if direction == FUTU_TICKER_DIR_BID:
        aggressor_side = AggressorSide.BUYER
    elif direction == FUTU_TICKER_DIR_ASK:
        aggressor_side = AggressorSide.SELLER
    else:
        aggressor_side = AggressorSide.NO_AGGRESSOR

    return TradeTick(
        instrument_id=instrument_id,
        price=Price.from_str(str(data.get("price", 0))),
        size=Quantity.from_int(data.get("volume", 0)),
        aggressor_side=aggressor_side,
        trade_id=TradeId(str(data.get("sequence", 0))),
        ts_event=ts_init,
        ts_init=ts_init,
    )


def parse_futu_bars(
    kl_data: list[dict[str, Any]],
    bar_type: BarType,
) -> list[Bar]:
    """Parse Futu K-line data to NautilusTrader Bars."""
    bars = []
    for kl in kl_data:
        if kl.get("is_blank", False):
            continue

        bar = Bar(
            bar_type=bar_type,
            open=Price.from_str(str(kl.get("open_price", 0))),
            high=Price.from_str(str(kl.get("high_price", 0))),
            low=Price.from_str(str(kl.get("low_price", 0))),
            close=Price.from_str(str(kl.get("close_price", 0))),
            volume=Quantity.from_int(kl.get("volume", 0)),
            ts_event=int(kl.get("timestamp", 0) * 1e9) if kl.get("timestamp") else 0,
            ts_init=int(kl.get("timestamp", 0) * 1e9) if kl.get("timestamp") else 0,
        )
        bars.append(bar)

    return bars


# KLType -> BarSpecification reverse mapping
_KL_TYPE_TO_BAR_SPEC: dict[int, BarSpecification] = {
    FUTU_KL_TYPE_1MIN: BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST),
    FUTU_KL_TYPE_5MIN: BarSpecification(5, BarAggregation.MINUTE, PriceType.LAST),
    FUTU_KL_TYPE_15MIN: BarSpecification(15, BarAggregation.MINUTE, PriceType.LAST),
    FUTU_KL_TYPE_30MIN: BarSpecification(30, BarAggregation.MINUTE, PriceType.LAST),
    FUTU_KL_TYPE_60MIN: BarSpecification(1, BarAggregation.HOUR, PriceType.LAST),
    FUTU_KL_TYPE_DAY: BarSpecification(1, BarAggregation.DAY, PriceType.LAST),
}


def futu_kl_type_to_bar_spec(kl_type: int) -> BarSpecification | None:
    """Convert Futu KLType to NautilusTrader BarSpecification."""
    return _KL_TYPE_TO_BAR_SPEC.get(kl_type)


def parse_push_order_book(
    data: dict[str, Any],
    instrument_id: InstrumentId,
    ts_init: int,
) -> OrderBookDeltas:
    """Parse Futu push order book data to NautilusTrader OrderBookDeltas.

    Uses full snapshot mode: CLEAR then ADD for each level.
    """
    deltas: list[OrderBookDelta] = []

    # First delta: CLEAR the book
    deltas.append(
        OrderBookDelta.clear(
            instrument_id=instrument_id,
            ts_event=ts_init,
            ts_init=ts_init,
            sequence=0,
        )
    )

    # Add bid levels
    for bid in data.get("bids", []):
        order = BookOrder(
            side=OrderSide.BUY,
            price=Price.from_str(str(bid["price"])),
            size=Quantity.from_int(bid["volume"]),
            order_id=0,
        )
        deltas.append(
            OrderBookDelta(
                instrument_id=instrument_id,
                action=BookAction.ADD,
                order=order,
                ts_event=ts_init,
                ts_init=ts_init,
                flags=0,
                sequence=0,
            )
        )

    # Add ask levels
    for ask in data.get("asks", []):
        order = BookOrder(
            side=OrderSide.SELL,
            price=Price.from_str(str(ask["price"])),
            size=Quantity.from_int(ask["volume"]),
            order_id=0,
        )
        deltas.append(
            OrderBookDelta(
                instrument_id=instrument_id,
                action=BookAction.ADD,
                order=order,
                ts_event=ts_init,
                ts_init=ts_init,
                flags=0,
                sequence=0,
            )
        )

    return OrderBookDeltas(instrument_id=instrument_id, deltas=deltas)
