"""Parse Futu order types to NautilusTrader order types."""

from __future__ import annotations

from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce

from nautilus_futu.constants import (
    FUTU_ORDER_TYPE_MARKET,
    FUTU_ORDER_TYPE_NORMAL,
    FUTU_TRD_SIDE_BUY,
    FUTU_TRD_SIDE_SELL,
    FUTU_TRD_SIDE_SELL_SHORT,
)


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
    if trd_side == FUTU_TRD_SIDE_BUY:
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
        return OrderType.LIMIT  # Default to LIMIT
