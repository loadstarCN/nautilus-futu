"""Parse Futu order types to NautilusTrader order types."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.reports import (
    FillReport,
    OrderStatusReport,
    PositionStatusReport,
)
from nautilus_trader.model.enums import (
    LiquiditySide,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    TimeInForce,
    TrailingOffsetType,
    TriggerType,
)
from nautilus_trader.model.identifiers import (
    AccountId,
    ClientOrderId,
    TradeId,
    VenueOrderId,
)
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Currency, Money
from nautilus_trader.model.orders import Order

from nautilus_futu.common import futu_security_to_instrument_id
from nautilus_futu.constants import (
    FUTU_ORDER_STATUS_CANCELLED_ALL,
    FUTU_ORDER_STATUS_CANCELLED_PART,
    FUTU_ORDER_STATUS_CANCELLING_ALL,
    FUTU_ORDER_STATUS_CANCELLING_PART,
    FUTU_ORDER_STATUS_DELETED,
    FUTU_ORDER_STATUS_DISABLED,
    FUTU_ORDER_STATUS_FAILED,
    FUTU_ORDER_STATUS_FILL_CANCELLED,
    FUTU_ORDER_STATUS_FILLED_ALL,
    FUTU_ORDER_STATUS_FILLED_PART,
    FUTU_ORDER_STATUS_SUBMIT_FAILED,
    FUTU_ORDER_STATUS_SUBMITTED,
    FUTU_ORDER_STATUS_SUBMITTING,
    FUTU_ORDER_STATUS_TIMEOUT,
    FUTU_ORDER_STATUS_UNKNOWN,
    FUTU_ORDER_STATUS_UNSUBMITTED,
    FUTU_ORDER_STATUS_WAITING_SUBMIT,
    FUTU_ORDER_TYPE_ABSOLUTE_LIMIT,
    FUTU_ORDER_TYPE_AUCTION,
    FUTU_ORDER_TYPE_AUCTION_LIMIT,
    FUTU_ORDER_TYPE_LIMIT_IF_TOUCHED,
    FUTU_ORDER_TYPE_MARKET,
    FUTU_ORDER_TYPE_MARKET_IF_TOUCHED,
    FUTU_ORDER_TYPE_NORMAL,
    FUTU_ORDER_TYPE_SPECIAL_LIMIT,
    FUTU_ORDER_TYPE_SPECIAL_LIMIT_ALL,
    FUTU_ORDER_TYPE_STOP,
    FUTU_ORDER_TYPE_STOP_LIMIT,
    FUTU_ORDER_TYPE_TRAILING_STOP,
    FUTU_ORDER_TYPE_TRAILING_STOP_LIMIT,
    FUTU_ORDER_TYPE_TWAP_LIMIT,
    FUTU_ORDER_TYPE_TWAP_MARKET,
    FUTU_ORDER_TYPE_VWAP_LIMIT,
    FUTU_ORDER_TYPE_VWAP_MARKET,
    FUTU_POSITION_SIDE_LONG,
    FUTU_POSITION_SIDE_SHORT,
    FUTU_QOT_MARKET_TO_CURRENCY,
    FUTU_TAG_FILL_OUTSIDE_RTH,
    FUTU_TIF_DAY,
    FUTU_TIF_GTC,
    FUTU_TRAIL_TYPE_AMOUNT,
    FUTU_TRAIL_TYPE_RATIO,
    FUTU_TRD_SEC_MARKET_TO_QOT_MARKET,
    FUTU_TRD_SIDE_BUY,
    FUTU_TRD_SIDE_BUY_BACK,
    FUTU_TRD_SIDE_SELL,
    FUTU_TRD_SIDE_SELL_SHORT,
)
from nautilus_futu.parsing.market_data import make_price, make_qty, seconds_to_ns

logger = logging.getLogger(__name__)

# Futu `remark` is capped at 64 bytes
FUTU_REMARK_MAX_BYTES = 64


# ---------------------------------------------------------------------------
# Side / type / status / TIF mappings
# ---------------------------------------------------------------------------


def nautilus_order_side_to_futu(side: OrderSide) -> int:
    """Convert NautilusTrader OrderSide to Futu TrdSide."""
    if side == OrderSide.BUY:
        return FUTU_TRD_SIDE_BUY
    elif side == OrderSide.SELL:
        return FUTU_TRD_SIDE_SELL
    else:
        raise ValueError(f"Unsupported order side: {side}")


def futu_trd_side_to_nautilus(trd_side: int) -> OrderSide:
    """Convert Futu TrdSide to NautilusTrader OrderSide."""
    if trd_side in (FUTU_TRD_SIDE_BUY, FUTU_TRD_SIDE_BUY_BACK):
        return OrderSide.BUY
    elif trd_side in (FUTU_TRD_SIDE_SELL, FUTU_TRD_SIDE_SELL_SHORT):
        return OrderSide.SELL
    else:
        raise ValueError(f"Unsupported Futu trade side: {trd_side}")


_NAUTILUS_TO_FUTU_ORDER_TYPE: dict[OrderType, int] = {
    OrderType.LIMIT: FUTU_ORDER_TYPE_NORMAL,
    OrderType.MARKET: FUTU_ORDER_TYPE_MARKET,
    OrderType.STOP_MARKET: FUTU_ORDER_TYPE_STOP,
    OrderType.STOP_LIMIT: FUTU_ORDER_TYPE_STOP_LIMIT,
    OrderType.MARKET_IF_TOUCHED: FUTU_ORDER_TYPE_MARKET_IF_TOUCHED,
    OrderType.LIMIT_IF_TOUCHED: FUTU_ORDER_TYPE_LIMIT_IF_TOUCHED,
    OrderType.TRAILING_STOP_MARKET: FUTU_ORDER_TYPE_TRAILING_STOP,
    OrderType.TRAILING_STOP_LIMIT: FUTU_ORDER_TYPE_TRAILING_STOP_LIMIT,
}

_FUTU_TO_NAUTILUS_ORDER_TYPE: dict[int, OrderType] = {
    FUTU_ORDER_TYPE_NORMAL: OrderType.LIMIT,
    FUTU_ORDER_TYPE_ABSOLUTE_LIMIT: OrderType.LIMIT,
    FUTU_ORDER_TYPE_AUCTION_LIMIT: OrderType.LIMIT,
    FUTU_ORDER_TYPE_SPECIAL_LIMIT: OrderType.LIMIT,
    FUTU_ORDER_TYPE_SPECIAL_LIMIT_ALL: OrderType.LIMIT,
    FUTU_ORDER_TYPE_TWAP_LIMIT: OrderType.LIMIT,
    FUTU_ORDER_TYPE_VWAP_LIMIT: OrderType.LIMIT,
    FUTU_ORDER_TYPE_MARKET: OrderType.MARKET,
    FUTU_ORDER_TYPE_AUCTION: OrderType.MARKET,
    FUTU_ORDER_TYPE_TWAP_MARKET: OrderType.MARKET,
    FUTU_ORDER_TYPE_VWAP_MARKET: OrderType.MARKET,
    FUTU_ORDER_TYPE_STOP: OrderType.STOP_MARKET,
    FUTU_ORDER_TYPE_STOP_LIMIT: OrderType.STOP_LIMIT,
    FUTU_ORDER_TYPE_MARKET_IF_TOUCHED: OrderType.MARKET_IF_TOUCHED,
    FUTU_ORDER_TYPE_LIMIT_IF_TOUCHED: OrderType.LIMIT_IF_TOUCHED,
    FUTU_ORDER_TYPE_TRAILING_STOP: OrderType.TRAILING_STOP_MARKET,
    FUTU_ORDER_TYPE_TRAILING_STOP_LIMIT: OrderType.TRAILING_STOP_LIMIT,
}

# Futu order types whose trigger price lives in `aux_price`
_FUTU_TRIGGERED_ORDER_TYPES: frozenset[int] = frozenset(
    {
        FUTU_ORDER_TYPE_STOP,
        FUTU_ORDER_TYPE_STOP_LIMIT,
        FUTU_ORDER_TYPE_MARKET_IF_TOUCHED,
        FUTU_ORDER_TYPE_LIMIT_IF_TOUCHED,
    }
)


def nautilus_order_type_to_futu(order_type: OrderType) -> int:
    """Convert NautilusTrader OrderType to Futu OrderType."""
    try:
        return _NAUTILUS_TO_FUTU_ORDER_TYPE[order_type]
    except KeyError:
        raise ValueError(f"Unsupported order type: {order_type}") from None


def futu_order_type_to_nautilus(order_type: int) -> OrderType:
    """Convert Futu OrderType to NautilusTrader OrderType."""
    nt_type = _FUTU_TO_NAUTILUS_ORDER_TYPE.get(order_type)
    if nt_type is None:
        logger.warning("Unknown Futu order type %d, defaulting to LIMIT", order_type)
        return OrderType.LIMIT
    return nt_type


def futu_order_status_to_nautilus(status: int) -> OrderStatus:
    """Convert Futu OrderStatus to NautilusTrader OrderStatus."""
    if status in (FUTU_ORDER_STATUS_UNSUBMITTED, FUTU_ORDER_STATUS_UNKNOWN):
        return OrderStatus.INITIALIZED
    elif status in (FUTU_ORDER_STATUS_WAITING_SUBMIT, FUTU_ORDER_STATUS_SUBMITTING):
        return OrderStatus.SUBMITTED
    elif status in (FUTU_ORDER_STATUS_SUBMIT_FAILED, FUTU_ORDER_STATUS_TIMEOUT):
        return OrderStatus.REJECTED
    elif status == FUTU_ORDER_STATUS_SUBMITTED:
        return OrderStatus.ACCEPTED
    elif status == FUTU_ORDER_STATUS_FILLED_PART:
        return OrderStatus.PARTIALLY_FILLED
    elif status == FUTU_ORDER_STATUS_FILLED_ALL:
        return OrderStatus.FILLED
    elif status in (FUTU_ORDER_STATUS_CANCELLING_PART, FUTU_ORDER_STATUS_CANCELLING_ALL):
        return OrderStatus.PENDING_CANCEL
    elif status in (
        FUTU_ORDER_STATUS_CANCELLED_PART,
        FUTU_ORDER_STATUS_CANCELLED_ALL,
        FUTU_ORDER_STATUS_DISABLED,
        FUTU_ORDER_STATUS_DELETED,
        FUTU_ORDER_STATUS_FILL_CANCELLED,
    ):
        return OrderStatus.CANCELED
    elif status == FUTU_ORDER_STATUS_FAILED:
        return OrderStatus.REJECTED
    else:
        logger.warning("Unknown Futu order status %d, defaulting to INITIALIZED", status)
        return OrderStatus.INITIALIZED


def futu_time_in_force_to_nautilus(tif: int | None) -> TimeInForce:
    """Convert Futu TimeInForce to NautilusTrader TimeInForce."""
    if tif is None:
        return TimeInForce.DAY
    elif tif == FUTU_TIF_GTC:
        return TimeInForce.GTC
    else:
        return TimeInForce.DAY


def nautilus_time_in_force_to_futu(tif: TimeInForce) -> int:
    """Convert NautilusTrader TimeInForce to Futu TimeInForce (DAY/GTC only)."""
    if tif == TimeInForce.GTC:
        return FUTU_TIF_GTC
    if tif == TimeInForce.DAY:
        return FUTU_TIF_DAY
    raise ValueError(f"Futu only supports DAY and GTC time-in-force, was {tif}")


# ---------------------------------------------------------------------------
# Client order id <-> remark
# ---------------------------------------------------------------------------


def client_order_id_to_remark(client_order_id: ClientOrderId) -> str:
    """Encode a client order ID in Futu's 64-byte ``remark`` field."""
    value = client_order_id.value
    if len(value.encode("utf-8")) > FUTU_REMARK_MAX_BYTES:
        logger.warning("client_order_id %s exceeds 64 bytes; remark truncated", value)
        value = value.encode("utf-8")[:FUTU_REMARK_MAX_BYTES].decode("utf-8", "ignore")
    return value


def client_order_id_from_remark(remark: str | None) -> ClientOrderId | None:
    """Recover a client order ID from a Futu ``remark`` (``None`` if empty/invalid)."""
    if not remark:
        return None
    remark = remark.strip()
    if not remark or any(ch.isspace() for ch in remark):
        return None
    try:
        return ClientOrderId(remark)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Order -> Futu place_order parameters
# ---------------------------------------------------------------------------


def _fill_outside_rth_from_tags(tags: list[str] | None) -> bool | None:
    """Read the ``FUTU_RTH:0|1`` order tag."""
    for tag in tags or []:
        if tag.startswith(FUTU_TAG_FILL_OUTSIDE_RTH + ":"):
            value = tag.split(":", 1)[1].strip().lower()
            return value in ("1", "true", "yes")
    return None


def build_futu_order_params(
    order: Order,
    default_fill_outside_rth: bool = False,
) -> dict[str, Any]:
    """Translate a Nautilus order into ``PyFutuClient.place_order`` keyword arguments.

    Raises ``ValueError`` for combinations Futu cannot express (IOC/FOK, post-only,
    unsupported order types), so the caller can reject the order up front.
    """
    if order.is_post_only:
        raise ValueError("Futu does not support post-only orders")

    order_type = nautilus_order_type_to_futu(order.order_type)
    params: dict[str, Any] = {
        "trd_side": nautilus_order_side_to_futu(order.side),
        "order_type": order_type,
        "qty": float(order.quantity),
        "price": None,
        "aux_price": None,
        "trail_type": None,
        "trail_value": None,
        "trail_spread": None,
        "time_in_force": nautilus_time_in_force_to_futu(order.time_in_force),
        "remark": client_order_id_to_remark(order.client_order_id),
    }

    if order.has_price:
        params["price"] = float(order.price)

    if order.has_trigger_price and order.order_type in (
        OrderType.STOP_MARKET,
        OrderType.STOP_LIMIT,
        OrderType.MARKET_IF_TOUCHED,
        OrderType.LIMIT_IF_TOUCHED,
    ):
        params["aux_price"] = float(order.trigger_price)

    if order.order_type in (OrderType.TRAILING_STOP_MARKET, OrderType.TRAILING_STOP_LIMIT):
        offset_type = order.trailing_offset_type
        offset = order.trailing_offset
        if offset is None:
            raise ValueError("Trailing stop orders require `trailing_offset`")
        if offset_type == TrailingOffsetType.PRICE:
            params["trail_type"] = FUTU_TRAIL_TYPE_AMOUNT
            params["trail_value"] = float(offset)
        elif offset_type == TrailingOffsetType.BASIS_POINTS:
            params["trail_type"] = FUTU_TRAIL_TYPE_RATIO
            params["trail_value"] = float(offset) / 100.0  # bps -> percent
        else:
            raise ValueError(f"Unsupported trailing offset type for Futu: {offset_type}")
        if order.order_type == OrderType.TRAILING_STOP_LIMIT:
            limit_offset = getattr(order, "limit_offset", None)
            params["trail_spread"] = float(limit_offset) if limit_offset is not None else 0.0
            # Futu derives the limit price from the trail; explicit price not used
            params["price"] = None

    tag_rth = _fill_outside_rth_from_tags(order.tags)
    fill_outside_rth = default_fill_outside_rth if tag_rth is None else tag_rth
    params["fill_outside_rth"] = bool(fill_outside_rth)

    return params


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def _trigger_fields(order: dict[str, Any], instrument: Instrument | None) -> dict[str, Any]:
    """Trigger / trailing fields for a status report."""
    fields: dict[str, Any] = {}
    futu_type = order.get("order_type")
    aux = order.get("aux_price")
    if futu_type in _FUTU_TRIGGERED_ORDER_TYPES and aux:
        fields["trigger_price"] = make_price(aux, instrument)
        fields["trigger_type"] = TriggerType.LAST_PRICE
    if futu_type in (FUTU_ORDER_TYPE_TRAILING_STOP, FUTU_ORDER_TYPE_TRAILING_STOP_LIMIT):
        trail_type = order.get("trail_type")
        trail_value = order.get("trail_value")
        if trail_value is not None:
            if trail_type == FUTU_TRAIL_TYPE_RATIO:
                fields["trailing_offset"] = Decimal(str(trail_value * 100))
                fields["trailing_offset_type"] = TrailingOffsetType.BASIS_POINTS
            else:
                fields["trailing_offset"] = Decimal(str(trail_value))
                fields["trailing_offset_type"] = TrailingOffsetType.PRICE
        spread = order.get("trail_spread")
        if spread is not None:
            fields["limit_offset"] = Decimal(str(spread))
    return fields


def parse_futu_order_to_report(
    order: dict[str, Any],
    account_id: AccountId,
    instrument: Instrument | None = None,
    ts_init: int | None = None,
) -> OrderStatusReport:
    """Parse a Futu order dict to NautilusTrader OrderStatusReport.

    Parameters
    ----------
    order : dict
        Order dictionary from PyFutuClient.get_order_list().
    account_id : AccountId
        The account ID.
    instrument : Instrument, optional
        Used for price/quantity precision when available.
    ts_init : int, optional
        Report init timestamp (defaults to the order's last update time).

    Returns
    -------
    OrderStatusReport
    """
    code = order["code"]
    sec_market = order.get("sec_market")
    market = sec_market_to_qot_market(sec_market)
    instrument_id = instrument.id if instrument is not None else futu_security_to_instrument_id(market, code)

    order_side = futu_trd_side_to_nautilus(order["trd_side"])
    order_type = futu_order_type_to_nautilus(order["order_type"])
    order_status = futu_order_status_to_nautilus(order["order_status"])
    time_in_force = futu_time_in_force_to_nautilus(order.get("time_in_force"))

    qty = make_qty(order["qty"], instrument)
    filled_qty = make_qty(order.get("fill_qty") or 0.0, instrument)
    price = make_price(order["price"], instrument) if order.get("price") else None
    avg_px = Decimal(str(order.get("fill_avg_price") or 0)) if order.get("fill_avg_price") else None

    ts_accepted = seconds_to_ns(order.get("create_timestamp"), 0)
    ts_last = seconds_to_ns(order.get("update_timestamp"), ts_accepted)
    if ts_init is None:
        ts_init = ts_last

    cancel_reason = None
    if order_status in (OrderStatus.CANCELED, OrderStatus.REJECTED):
        cancel_reason = order.get("last_err_msg") or None

    return OrderStatusReport(
        account_id=account_id,
        instrument_id=instrument_id,
        client_order_id=client_order_id_from_remark(order.get("remark")),
        venue_order_id=VenueOrderId(str(order["order_id"])),
        order_side=order_side,
        order_type=order_type,
        time_in_force=time_in_force,
        order_status=order_status,
        quantity=qty,
        filled_qty=filled_qty,
        price=price,
        avg_px=avg_px,
        cancel_reason=cancel_reason,
        report_id=UUID4(),
        ts_accepted=ts_accepted,
        ts_last=ts_last,
        ts_init=ts_init,
        **_trigger_fields(order, instrument),
    )


def parse_futu_fill_to_report(
    fill: dict[str, Any],
    account_id: AccountId,
    instrument: Instrument | None = None,
    client_order_id: ClientOrderId | None = None,
    ts_init: int | None = None,
) -> FillReport:
    """Parse a Futu order fill dict to NautilusTrader FillReport."""
    code = fill["code"]
    sec_market = fill.get("sec_market")
    market = sec_market_to_qot_market(sec_market)
    instrument_id = instrument.id if instrument is not None else futu_security_to_instrument_id(market, code)

    order_side = futu_trd_side_to_nautilus(fill["trd_side"])

    ts_event = seconds_to_ns(fill.get("create_timestamp"), 0)
    if ts_init is None:
        ts_init = ts_event

    # Futu fills carry no commission; fees are only available per order via
    # `get_order_fee`, so commission is reported as zero here.
    currency = instrument.quote_currency if instrument is not None else qot_market_to_currency(market)
    commission = Money(0, currency)

    return FillReport(
        account_id=account_id,
        instrument_id=instrument_id,
        client_order_id=client_order_id,
        venue_order_id=VenueOrderId(str(fill.get("order_id") or 0)),
        trade_id=TradeId(str(fill["fill_id"])),
        order_side=order_side,
        last_qty=make_qty(fill["qty"], instrument),
        last_px=make_price(fill["price"], instrument),
        commission=commission,
        liquidity_side=LiquiditySide.NO_LIQUIDITY_SIDE,
        report_id=UUID4(),
        ts_event=ts_event,
        ts_init=ts_init,
    )


def parse_futu_position_to_report(
    position: dict[str, Any],
    account_id: AccountId,
    instrument: Instrument | None = None,
    ts_init: int = 0,
) -> PositionStatusReport:
    """Parse a Futu position dict to NautilusTrader PositionStatusReport."""
    code = position["code"]
    sec_market = position.get("sec_market")
    market = sec_market_to_qot_market(sec_market)
    instrument_id = instrument.id if instrument is not None else futu_security_to_instrument_id(market, code)

    qty = position["qty"]
    position_side_int = position.get("position_side", FUTU_POSITION_SIDE_LONG)
    if qty == 0:
        position_side = PositionSide.FLAT
    elif position_side_int == FUTU_POSITION_SIDE_SHORT or qty < 0:
        position_side = PositionSide.SHORT
    else:
        position_side = PositionSide.LONG

    cost = position.get("cost_price")
    avg_px_open = Decimal(str(cost)) if cost else None

    return PositionStatusReport(
        account_id=account_id,
        instrument_id=instrument_id,
        position_side=position_side,
        quantity=make_qty(abs(qty), instrument),
        avg_px_open=avg_px_open,
        report_id=UUID4(),
        ts_last=ts_init,
        ts_init=ts_init,
    )


def sec_market_to_qot_market(sec_market: int | None) -> int:
    """Map Futu TrdSecMarket to QotMarket for instrument_id resolution."""
    if sec_market is None:
        return 0
    result = FUTU_TRD_SEC_MARKET_TO_QOT_MARKET.get(sec_market)
    if result is None:
        logger.warning("Unknown sec_market=%d, defaulting to 0", sec_market)
        return 0
    return result


def qot_market_to_currency(market: int) -> Currency:
    """Map QotMarket to default currency for commission."""
    code = FUTU_QOT_MARKET_TO_CURRENCY.get(market)
    if code is None:
        logger.warning("Unknown QotMarket=%d, defaulting to USD", market)
        code = "USD"
    return Currency.from_str(code)
