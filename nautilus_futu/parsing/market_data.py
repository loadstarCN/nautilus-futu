"""Parse Futu market data to NautilusTrader data types."""

from __future__ import annotations

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
    AggressorSide,
    BarAggregation,
    BookAction,
    OrderSide,
    PriceType,
)
from nautilus_trader.model.identifiers import InstrumentId, TradeId
from nautilus_trader.model.objects import Price, Quantity

from nautilus_futu.constants import (
    FUTU_KL_TYPE_1MIN,
    FUTU_KL_TYPE_5MIN,
    FUTU_KL_TYPE_15MIN,
    FUTU_KL_TYPE_30MIN,
    FUTU_KL_TYPE_60MIN,
    FUTU_KL_TYPE_DAY,
    FUTU_KL_TYPE_WEEK,
    FUTU_KL_TYPE_MONTH,
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
        if spec.step == 1:
            return FUTU_SUB_TYPE_KL_DAY
        return None
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
        if spec.step == 1:
            return FUTU_KL_TYPE_DAY
        return None
    elif spec.aggregation == BarAggregation.WEEK:
        if spec.step == 1:
            return FUTU_KL_TYPE_WEEK
        return None
    elif spec.aggregation == BarAggregation.MONTH:
        if spec.step == 1:
            return FUTU_KL_TYPE_MONTH
        return None
    return None


def parse_futu_quote_tick(
    data: dict[str, Any],
    instrument_id: InstrumentId,
    ts_init: int,
) -> QuoteTick:
    """Parse Futu basic quote to NautilusTrader QuoteTick.

    Uses ``price_spread`` to derive bid/ask prices instead of fabricating
    a zero-spread tick from ``cur_price`` alone.
    """
    cur_price = data.get("cur_price") or 0
    spread = data.get("price_spread") or 0
    bid_price = cur_price
    ask_price = cur_price + spread
    volume = max(data.get("volume") or 0, 1)  # avoid zero-quantity
    return QuoteTick(
        instrument_id=instrument_id,
        bid_price=Price.from_str(str(bid_price)),
        ask_price=Price.from_str(str(ask_price)),
        bid_size=Quantity.from_int(volume),
        ask_size=Quantity.from_int(volume),
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
        price=Price.from_str(str(data.get("price") or 0)),
        size=Quantity.from_int(max(data.get("volume") or 0, 1)),
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

        # Use `or 0` to handle explicit None values (key exists but value is None)
        open_val = kl.get("open_price") or 0
        high_val = kl.get("high_price") or 0
        low_val = kl.get("low_price") or 0
        close_val = kl.get("close_price") or 0
        vol_val = max(kl.get("volume") or 0, 1)  # avoid zero-quantity
        ts_val = kl.get("timestamp")
        ts_ns = int(ts_val * 1e9) if ts_val else 0

        bar = Bar(
            bar_type=bar_type,
            open=Price.from_str(str(open_val)),
            high=Price.from_str(str(high_val)),
            low=Price.from_str(str(low_val)),
            close=Price.from_str(str(close_val)),
            volume=Quantity.from_int(vol_val),
            ts_event=ts_ns,
            ts_init=ts_ns,
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
    FUTU_KL_TYPE_WEEK: BarSpecification(1, BarAggregation.WEEK, PriceType.LAST),
    FUTU_KL_TYPE_MONTH: BarSpecification(1, BarAggregation.MONTH, PriceType.LAST),
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
