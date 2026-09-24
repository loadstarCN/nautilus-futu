"""Parse Futu market data to NautilusTrader data types."""

from __future__ import annotations

import math
from typing import Any

from nautilus_trader.model.data import (
    NULL_ORDER,
    Bar,
    BarSpecification,
    BarType,
    BookOrder,
    OrderBookDelta,
    OrderBookDeltas,
    OrderBookDepth10,
    QuoteTick,
    TradeTick,
)
from nautilus_trader.model.enums import (
    AggressorSide,
    BarAggregation,
    BookAction,
    OrderSide,
    PriceType,
    RecordFlag,
)
from nautilus_trader.model.identifiers import InstrumentId, TradeId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Price, Quantity

from nautilus_futu.constants import (
    FUTU_KL_TYPE_1MIN,
    FUTU_KL_TYPE_5MIN,
    FUTU_KL_TYPE_15MIN,
    FUTU_KL_TYPE_30MIN,
    FUTU_KL_TYPE_60MIN,
    FUTU_KL_TYPE_DAY,
    FUTU_KL_TYPE_MONTH,
    FUTU_KL_TYPE_TO_SUB_TYPE,
    FUTU_KL_TYPE_WEEK,
    FUTU_SUB_TYPE_TO_KL_TYPE,
    FUTU_TICKER_DIR_ASK,
    FUTU_TICKER_DIR_BID,
)

# NautilusTrader's maximum fixed-point precision (standard precision build).
MAX_PRECISION = 9

# Levels per side of an `OrderBookDepth10`
DEPTH10_LEVELS = 10

_MINUTE_STEP_TO_KL_TYPE: dict[int, int] = {
    1: FUTU_KL_TYPE_1MIN,
    5: FUTU_KL_TYPE_5MIN,
    15: FUTU_KL_TYPE_15MIN,
    30: FUTU_KL_TYPE_30MIN,
    60: FUTU_KL_TYPE_60MIN,
}


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------


def infer_precision(value: float, max_precision: int = MAX_PRECISION) -> int:
    """Return the number of significant decimals in ``value`` (capped)."""
    if value is None or not math.isfinite(value):
        return 0
    text = f"{abs(value):.{max_precision}f}".rstrip("0")
    if "." not in text:
        return 0
    return min(len(text.split(".")[1]), max_precision)


def make_price(value: float | None, instrument: Instrument | None = None) -> Price:
    """Build a ``Price`` from a Futu float.

    Uses the instrument's price precision when available, otherwise infers a
    precision from the value (never exceeding Nautilus' 9-decimal limit, which
    a raw ``str(float)`` conversion can violate).
    """
    value = float(value or 0.0)
    if instrument is not None:
        return instrument.make_price(value)
    precision = infer_precision(value)
    return Price(round(value, precision), precision)


def make_qty(value: float | None, instrument: Instrument | None = None) -> Quantity:
    """Build a ``Quantity`` from a Futu float/int (fractional US shares supported)."""
    value = float(value or 0.0)
    if value < 0:
        value = abs(value)
    if instrument is not None:
        return instrument.make_qty(value)
    precision = infer_precision(value)
    return Quantity(round(value, precision), precision)


def seconds_to_ns(seconds: float | None, default: int) -> int:
    """Convert a Futu epoch-seconds timestamp to nanoseconds, or ``default``."""
    if seconds is None or seconds <= 0:
        return default
    return int(round(seconds * 1_000_000_000))


# ---------------------------------------------------------------------------
# Bar specification mappings
# ---------------------------------------------------------------------------


def bar_spec_to_futu_kl_type(spec: BarSpecification) -> int | None:
    """Convert NautilusTrader BarSpecification to Futu KLType.

    ``60-MINUTE`` and ``1-HOUR`` both map to the 60-minute K-line.
    """
    if spec.aggregation == BarAggregation.MINUTE:
        return _MINUTE_STEP_TO_KL_TYPE.get(spec.step)
    if spec.aggregation == BarAggregation.HOUR:
        return FUTU_KL_TYPE_60MIN if spec.step == 1 else None
    if spec.aggregation == BarAggregation.DAY:
        return FUTU_KL_TYPE_DAY if spec.step == 1 else None
    if spec.aggregation == BarAggregation.WEEK:
        return FUTU_KL_TYPE_WEEK if spec.step == 1 else None
    if spec.aggregation == BarAggregation.MONTH:
        return FUTU_KL_TYPE_MONTH if spec.step == 1 else None
    return None


def bar_spec_to_futu_sub_type(spec: BarSpecification) -> int | None:
    """Convert NautilusTrader BarSpecification to Futu SubType (for subscriptions)."""
    kl_type = bar_spec_to_futu_kl_type(spec)
    if kl_type is None:
        return None
    return FUTU_KL_TYPE_TO_SUB_TYPE.get(kl_type)


def futu_sub_type_to_kl_type(sub_type: int) -> int | None:
    """Convert a K-line SubType to the KLType found in push payloads."""
    return FUTU_SUB_TYPE_TO_KL_TYPE.get(sub_type)


# KLType -> canonical BarSpecification (60-minute is reported as 1-HOUR)
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
    """Convert Futu KLType to the canonical NautilusTrader BarSpecification."""
    return _KL_TYPE_TO_BAR_SPEC.get(kl_type)


def bar_spec_duration_ns(spec: BarSpecification) -> int:
    """Nominal bar duration in nanoseconds (calendar months approximated as 30 days)."""
    if spec.aggregation == BarAggregation.MINUTE:
        return spec.step * 60 * 1_000_000_000
    if spec.aggregation == BarAggregation.HOUR:
        return spec.step * 3_600 * 1_000_000_000
    if spec.aggregation == BarAggregation.DAY:
        return spec.step * 86_400 * 1_000_000_000
    if spec.aggregation == BarAggregation.WEEK:
        return spec.step * 7 * 86_400 * 1_000_000_000
    if spec.aggregation == BarAggregation.MONTH:
        return spec.step * 30 * 86_400 * 1_000_000_000
    return 0


# ---------------------------------------------------------------------------
# Ticks
# ---------------------------------------------------------------------------


def parse_futu_quote_tick(
    data: dict[str, Any],
    instrument_id: InstrumentId,
    ts_init: int,
    instrument: Instrument | None = None,
) -> QuoteTick:
    """Parse a Futu basic quote / snapshot dict to a ``QuoteTick``.

    Prefers real ``bid_price``/``ask_price``/``bid_vol``/``ask_vol`` fields
    (present in ``get_security_snapshot``).  Falls back to ``cur_price`` and
    ``price_spread`` for BasicQot payloads, which carry no bid/ask.
    """
    ts_event = seconds_to_ns(data.get("update_timestamp"), ts_init)

    bid = data.get("bid_price")
    ask = data.get("ask_price")
    if bid and ask:
        bid_price = make_price(bid, instrument)
        ask_price = make_price(ask, instrument)
        bid_size = make_qty(data.get("bid_vol") or 0, instrument)
        ask_size = make_qty(data.get("ask_vol") or 0, instrument)
    else:
        cur_price = float(data.get("cur_price") or 0)
        spread = float(data.get("price_spread") or 0)
        precision = (
            instrument.price_precision
            if instrument is not None
            else max(infer_precision(cur_price), infer_precision(spread))
        )
        bid_price = make_price(round(cur_price, precision), instrument)
        ask_price = make_price(round(cur_price + spread, precision), instrument)
        bid_size = make_qty(data.get("volume") or 0, instrument)
        ask_size = bid_size

    return QuoteTick(
        instrument_id=instrument_id,
        bid_price=bid_price,
        ask_price=ask_price,
        bid_size=bid_size,
        ask_size=ask_size,
        ts_event=ts_event,
        ts_init=ts_init,
    )


def parse_order_book_to_quote_tick(
    data: dict[str, Any],
    instrument_id: InstrumentId,
    ts_init: int,
    instrument: Instrument | None = None,
) -> QuoteTick | None:
    """Build a level-1 ``QuoteTick`` from an order book push/snapshot dict.

    Returns ``None`` when either side is empty (e.g. auction phase).
    """
    bids = data.get("bids") or []
    asks = data.get("asks") or []
    if not bids or not asks:
        return None
    best_bid = bids[0]
    best_ask = asks[0]
    ts_event = seconds_to_ns(
        max(
            float(data.get("svr_recv_time_bid_timestamp") or 0),
            float(data.get("svr_recv_time_ask_timestamp") or 0),
        ),
        ts_init,
    )
    return QuoteTick(
        instrument_id=instrument_id,
        bid_price=make_price(best_bid["price"], instrument),
        ask_price=make_price(best_ask["price"], instrument),
        bid_size=make_qty(best_bid.get("volume") or 0, instrument),
        ask_size=make_qty(best_ask.get("volume") or 0, instrument),
        ts_event=ts_event,
        ts_init=ts_init,
    )


def parse_futu_trade_tick(
    data: dict[str, Any],
    instrument_id: InstrumentId,
    ts_init: int,
    instrument: Instrument | None = None,
) -> TradeTick | None:
    """Parse Futu ticker to NautilusTrader TradeTick.

    Returns ``None`` for zero-volume prints (a ``TradeTick`` size must be positive).
    """
    volume = data.get("volume") or 0
    if volume <= 0:
        return None
    direction = data.get("dir", 0)
    if direction == FUTU_TICKER_DIR_BID:
        aggressor_side = AggressorSide.BUYER
    elif direction == FUTU_TICKER_DIR_ASK:
        aggressor_side = AggressorSide.SELLER
    else:
        aggressor_side = AggressorSide.NO_AGGRESSOR

    ts_event = seconds_to_ns(data.get("timestamp"), ts_init)
    sequence = data.get("sequence")
    trade_id = str(sequence) if sequence else f"{ts_event}"

    return TradeTick(
        instrument_id=instrument_id,
        price=make_price(data.get("price") or 0, instrument),
        size=make_qty(volume, instrument),
        aggressor_side=aggressor_side,
        trade_id=TradeId(trade_id),
        ts_event=ts_event,
        ts_init=ts_init,
    )


# ---------------------------------------------------------------------------
# Bars
# ---------------------------------------------------------------------------


def parse_futu_bar(
    kl: dict[str, Any],
    bar_type: BarType,
    instrument: Instrument | None = None,
    ts_init: int | None = None,
    is_revision: bool = False,
) -> Bar | None:
    """Parse one Futu K-line dict to a ``Bar`` (``None`` for blank placeholders).

    ``ts_event`` is the K-line's own timestamp (bar open time in Futu's
    convention); ``ts_init`` defaults to the same value for historical data.
    """
    if kl.get("is_blank", False):
        return None

    # Use `or 0` to handle explicit None values (key exists but value is None)
    open_val = kl.get("open_price") or 0
    high_val = kl.get("high_price") or 0
    low_val = kl.get("low_price") or 0
    close_val = kl.get("close_price") or 0
    vol_val = kl.get("volume") or 0
    ts_ns = seconds_to_ns(kl.get("timestamp"), 0)

    return Bar(
        bar_type=bar_type,
        open=make_price(open_val, instrument),
        high=make_price(high_val, instrument),
        low=make_price(low_val, instrument),
        close=make_price(close_val, instrument),
        volume=make_qty(vol_val, instrument),
        ts_event=ts_ns,
        ts_init=ts_init if ts_init is not None else ts_ns,
        is_revision=is_revision,
    )


def parse_futu_bars(
    kl_data: list[dict[str, Any]],
    bar_type: BarType,
    instrument: Instrument | None = None,
    ts_init: int | None = None,
) -> list[Bar]:
    """Parse Futu K-line data to NautilusTrader Bars (blank bars skipped)."""
    bars: list[Bar] = []
    for kl in kl_data:
        bar = parse_futu_bar(kl, bar_type, instrument, ts_init)
        if bar is not None:
            bars.append(bar)
    return bars


# ---------------------------------------------------------------------------
# Order book
# ---------------------------------------------------------------------------


def parse_push_order_book(
    data: dict[str, Any],
    instrument_id: InstrumentId,
    ts_init: int,
    instrument: Instrument | None = None,
    depth: int = 0,
    sequence: int = 0,
) -> OrderBookDeltas:
    """Parse a Futu order book push/snapshot into ``OrderBookDeltas``.

    Futu always sends the full book, so this emits ``CLEAR`` followed by one
    ``ADD`` per level (L2 semantics, ``order_id=0``).  The final delta carries
    ``F_LAST`` so the book applies the batch atomically; ``depth`` (>0)
    truncates each side.
    """
    ts_event = _book_timestamp(data, ts_init)
    bids = data.get("bids") or []
    asks = data.get("asks") or []
    if depth and depth > 0:
        bids = bids[:depth]
        asks = asks[:depth]

    deltas: list[OrderBookDelta] = [
        OrderBookDelta.clear(
            instrument_id=instrument_id,
            ts_event=ts_event,
            ts_init=ts_init,
            sequence=sequence,
        )
    ]
    # Nautilus requires `flags` to carry F_SNAPSHOT on the clear of a snapshot
    deltas[0] = OrderBookDelta(
        instrument_id=instrument_id,
        action=BookAction.CLEAR,
        order=deltas[0].order,
        flags=RecordFlag.F_SNAPSHOT,
        sequence=sequence,
        ts_event=ts_event,
        ts_init=ts_init,
    )

    for side, levels in ((OrderSide.BUY, bids), (OrderSide.SELL, asks)):
        for level in levels:
            volume = level.get("volume") or 0
            if volume <= 0:
                continue
            order = BookOrder(
                side=side,
                price=make_price(level["price"], instrument),
                size=make_qty(volume, instrument),
                order_id=0,
            )
            deltas.append(
                OrderBookDelta(
                    instrument_id=instrument_id,
                    action=BookAction.ADD,
                    order=order,
                    flags=0,
                    sequence=sequence,
                    ts_event=ts_event,
                    ts_init=ts_init,
                )
            )

    last = deltas[-1]
    deltas[-1] = OrderBookDelta(
        instrument_id=instrument_id,
        action=last.action,
        order=last.order,
        flags=last.flags | RecordFlag.F_LAST,
        sequence=sequence,
        ts_event=ts_event,
        ts_init=ts_init,
    )
    return OrderBookDeltas(instrument_id=instrument_id, deltas=deltas)


def _book_timestamp(data: dict[str, Any], ts_init: int) -> int:
    return seconds_to_ns(
        max(
            float(data.get("svr_recv_time_bid_timestamp") or 0),
            float(data.get("svr_recv_time_ask_timestamp") or 0),
        ),
        ts_init,
    )


def parse_order_book_depth10(
    data: dict[str, Any],
    instrument_id: InstrumentId,
    ts_init: int,
    instrument: Instrument | None = None,
    sequence: int = 0,
) -> OrderBookDepth10:
    """Parse a Futu order book push/snapshot into an ``OrderBookDepth10``.

    OpenD sends up to 10 levels per side (5 for A-shares); missing levels are
    padded with null orders and zero counts.  Per-level order counts come from
    Futu's ``order_count``.
    """

    def side_levels(levels: list[dict[str, Any]], side: OrderSide) -> tuple[list[BookOrder], list[int]]:
        orders: list[BookOrder] = []
        counts: list[int] = []
        for level in levels:
            volume = level.get("volume") or 0
            if volume <= 0:
                continue
            orders.append(
                BookOrder(
                    side=side,
                    price=make_price(level["price"], instrument),
                    size=make_qty(volume, instrument),
                    order_id=0,
                )
            )
            counts.append(max(0, int(level.get("order_count") or 0)))
            if len(orders) == DEPTH10_LEVELS:
                break
        padding = DEPTH10_LEVELS - len(orders)
        return orders + [NULL_ORDER] * padding, counts + [0] * padding

    bids, bid_counts = side_levels(data.get("bids") or [], OrderSide.BUY)
    asks, ask_counts = side_levels(data.get("asks") or [], OrderSide.SELL)
    return OrderBookDepth10(
        instrument_id=instrument_id,
        bids=bids,
        asks=asks,
        bid_counts=bid_counts,
        ask_counts=ask_counts,
        flags=RecordFlag.F_SNAPSHOT | RecordFlag.F_LAST,
        sequence=sequence,
        ts_event=_book_timestamp(data, ts_init),
        ts_init=ts_init,
    )
