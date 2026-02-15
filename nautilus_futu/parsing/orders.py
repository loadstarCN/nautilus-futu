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
)
from nautilus_trader.model.identifiers import (
    AccountId,
    InstrumentId,
    TradeId,
    VenueOrderId,
)
from nautilus_trader.model.objects import Currency, Money, Price, Quantity

from nautilus_futu.common import futu_security_to_instrument_id
from nautilus_futu.constants import (
    FUTU_QOT_MARKET_TO_CURRENCY,
    FUTU_TRD_SEC_MARKET_TO_QOT_MARKET,
    FUTU_ORDER_STATUS_CANCELLED_ALL,
    FUTU_ORDER_STATUS_CANCELLED_PART,
    FUTU_ORDER_STATUS_CANCELLING_ALL,
    FUTU_ORDER_STATUS_CANCELLING_PART,
    FUTU_ORDER_STATUS_DELETED,
    FUTU_ORDER_STATUS_DISABLED,
    FUTU_ORDER_STATUS_FAILED,
    FUTU_ORDER_STATUS_FILLED_ALL,
    FUTU_ORDER_STATUS_FILLED_PART,
    FUTU_ORDER_STATUS_FILL_CANCELLED,
    FUTU_ORDER_STATUS_SUBMITTED,
    FUTU_ORDER_STATUS_SUBMIT_FAILED,
    FUTU_ORDER_STATUS_SUBMITTING,
    FUTU_ORDER_STATUS_TIMEOUT,
    FUTU_ORDER_STATUS_UNKNOWN,
    FUTU_ORDER_STATUS_UNSUBMITTED,
    FUTU_ORDER_STATUS_WAITING_SUBMIT,
    FUTU_ORDER_TYPE_MARKET,
    FUTU_ORDER_TYPE_NORMAL,
    FUTU_POSITION_SIDE_LONG,
    FUTU_POSITION_SIDE_SHORT,
    FUTU_TIF_GTC,
    FUTU_TRD_SIDE_BUY,
    FUTU_TRD_SIDE_BUY_BACK,
    FUTU_TRD_SIDE_SELL,
    FUTU_TRD_SIDE_SELL_SHORT,
)

logger = logging.getLogger(__name__)


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


def nautilus_order_type_to_futu(order_type: OrderType) -> int:
    """Convert NautilusTrader OrderType to Futu OrderType."""
    if order_type == OrderType.LIMIT:
        return FUTU_ORDER_TYPE_NORMAL
    elif order_type == OrderType.MARKET:
        return FUTU_ORDER_TYPE_MARKET
    else:
        raise ValueError(f"Unsupported order type: {order_type}")


def futu_order_type_to_nautilus(order_type: int) -> OrderType:
    """Convert Futu OrderType to NautilusTrader OrderType."""
    if order_type == FUTU_ORDER_TYPE_NORMAL:
        return OrderType.LIMIT
    elif order_type == FUTU_ORDER_TYPE_MARKET:
        return OrderType.MARKET
    else:
        logger.warning("Unknown Futu order type %d, defaulting to LIMIT", order_type)
        return OrderType.LIMIT  # Default to LIMIT


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


def parse_futu_order_to_report(
    order: dict[str, Any],
    account_id: AccountId,
) -> OrderStatusReport:
    """Parse a Futu order dict to NautilusTrader OrderStatusReport.

    Parameters
    ----------
    order : dict
        Order dictionary from PyFutuClient.get_order_list().
    account_id : AccountId
        The account ID.

    Returns
    -------
    OrderStatusReport
    """
    code = order["code"]
    sec_market = order.get("sec_market")
    market = sec_market_to_qot_market(sec_market)
    instrument_id = futu_security_to_instrument_id(market, code)

    order_side = futu_trd_side_to_nautilus(order["trd_side"])
    order_type = futu_order_type_to_nautilus(order["order_type"])
    order_status = futu_order_status_to_nautilus(order["order_status"])
    time_in_force = futu_time_in_force_to_nautilus(order.get("time_in_force"))

    qty = Quantity.from_raw(int(order["qty"] * 1e9), precision=9)
    filled_qty = Quantity.from_raw(int((order.get("fill_qty") or 0.0) * 1e9), precision=9)
    price = Price.from_str(str(order.get("price") or 0)) if order.get("price") else None
    avg_px = Decimal(str(order.get("fill_avg_price") or 0)) if order.get("fill_avg_price") else None

    ts_accepted = int((order.get("create_timestamp") or 0) * 1e9)
    ts_last = int((order.get("update_timestamp") or 0) * 1e9)

    return OrderStatusReport(
        account_id=account_id,
        instrument_id=instrument_id,
        venue_order_id=VenueOrderId(str(order["order_id"])),
        order_side=order_side,
        order_type=order_type,
        time_in_force=time_in_force,
        order_status=order_status,
        quantity=qty,
        filled_qty=filled_qty,
        price=price,
        avg_px=avg_px,
        report_id=UUID4(),
        ts_accepted=ts_accepted,
        ts_last=ts_last,
        ts_init=ts_last,
    )


def parse_futu_fill_to_report(
    fill: dict[str, Any],
    account_id: AccountId,
) -> FillReport:
    """Parse a Futu order fill dict to NautilusTrader FillReport.

    Parameters
    ----------
    fill : dict
        Fill dictionary from PyFutuClient.get_order_fill_list().
    account_id : AccountId
        The account ID.

    Returns
    -------
    FillReport
    """
    code = fill["code"]
    sec_market = fill.get("sec_market")
    market = sec_market_to_qot_market(sec_market)
    instrument_id = futu_security_to_instrument_id(market, code)

    order_side = futu_trd_side_to_nautilus(fill["trd_side"])

    ts_event = int((fill.get("create_timestamp") or 0) * 1e9)

    # Derive currency from market for commission
    currency = qot_market_to_currency(market)
    commission = Money(0, currency)

    return FillReport(
        account_id=account_id,
        instrument_id=instrument_id,
        venue_order_id=VenueOrderId(str(fill.get("order_id") or 0)),
        trade_id=TradeId(str(fill["fill_id"])),
        order_side=order_side,
        last_qty=Quantity.from_raw(int(fill["qty"] * 1e9), precision=9),
        last_px=Price.from_str(str(fill["price"])),
        commission=commission,
        liquidity_side=LiquiditySide.NO_LIQUIDITY_SIDE,
        report_id=UUID4(),
        ts_event=ts_event,
        ts_init=ts_event,
    )


def parse_futu_position_to_report(
    position: dict[str, Any],
    account_id: AccountId,
) -> PositionStatusReport:
    """Parse a Futu position dict to NautilusTrader PositionStatusReport.

    Parameters
    ----------
    position : dict
        Position dictionary from PyFutuClient.get_position_list().
    account_id : AccountId
        The account ID.

    Returns
    -------
    PositionStatusReport
    """
    code = position["code"]
    sec_market = position.get("sec_market")
    market = sec_market_to_qot_market(sec_market)
    instrument_id = futu_security_to_instrument_id(market, code)

    qty = position["qty"]
    position_side_int = position.get("position_side", FUTU_POSITION_SIDE_LONG)
    if qty == 0:
        position_side = PositionSide.FLAT
    elif position_side_int == FUTU_POSITION_SIDE_SHORT:
        position_side = PositionSide.SHORT
    else:
        position_side = PositionSide.LONG

    return PositionStatusReport(
        account_id=account_id,
        instrument_id=instrument_id,
        position_side=position_side,
        quantity=Quantity.from_raw(int(abs(qty) * 1e9), precision=9),
        report_id=UUID4(),
        ts_last=0,
        ts_init=0,
    )


def sec_market_to_qot_market(sec_market: int | None) -> int:
    """Map Futu TrdSecMarket to QotMarket for instrument_id resolution."""
    if sec_market is None:
        return 0
    return FUTU_TRD_SEC_MARKET_TO_QOT_MARKET.get(sec_market, 0)


def qot_market_to_currency(market: int) -> Currency:
    """Map QotMarket to default currency for commission."""
    return Currency.from_str(FUTU_QOT_MARKET_TO_CURRENCY.get(market, "USD"))
