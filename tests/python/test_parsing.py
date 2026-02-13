"""Tests for Futu data parsing utilities."""

import pytest

from nautilus_futu.parsing.orders import (
    futu_order_type_to_nautilus,
    futu_trd_side_to_nautilus,
    nautilus_order_side_to_futu,
    nautilus_order_type_to_futu,
)
from nautilus_futu.parsing.market_data import (
    bar_spec_to_futu_kl_type,
    bar_spec_to_futu_sub_type,
)
from nautilus_futu.constants import (
    FUTU_KL_TYPE_1MIN,
    FUTU_KL_TYPE_DAY,
    FUTU_ORDER_TYPE_MARKET,
    FUTU_ORDER_TYPE_NORMAL,
    FUTU_SUB_TYPE_KL_1MIN,
    FUTU_SUB_TYPE_KL_DAY,
    FUTU_TRD_SIDE_BUY,
    FUTU_TRD_SIDE_SELL,
)


class TestOrderConversion:
    """Tests for order type conversion."""

    def test_buy_side_conversion(self):
        from nautilus_trader.model.enums import OrderSide

        assert nautilus_order_side_to_futu(OrderSide.BUY) == FUTU_TRD_SIDE_BUY
        assert futu_trd_side_to_nautilus(FUTU_TRD_SIDE_BUY) == OrderSide.BUY

    def test_sell_side_conversion(self):
        from nautilus_trader.model.enums import OrderSide

        assert nautilus_order_side_to_futu(OrderSide.SELL) == FUTU_TRD_SIDE_SELL
        assert futu_trd_side_to_nautilus(FUTU_TRD_SIDE_SELL) == OrderSide.SELL

    def test_limit_order_type_conversion(self):
        from nautilus_trader.model.enums import OrderType

        assert nautilus_order_type_to_futu(OrderType.LIMIT) == FUTU_ORDER_TYPE_NORMAL
        assert futu_order_type_to_nautilus(FUTU_ORDER_TYPE_NORMAL) == OrderType.LIMIT

    def test_market_order_type_conversion(self):
        from nautilus_trader.model.enums import OrderType

        assert nautilus_order_type_to_futu(OrderType.MARKET) == FUTU_ORDER_TYPE_MARKET
        assert futu_order_type_to_nautilus(FUTU_ORDER_TYPE_MARKET) == OrderType.MARKET


class TestBarTypeConversion:
    """Tests for bar type conversion."""

    def test_1min_bar_sub_type(self):
        from nautilus_trader.model.data import BarSpecification
        from nautilus_trader.model.enums import BarAggregation, PriceType

        spec = BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST)
        assert bar_spec_to_futu_sub_type(spec) == FUTU_SUB_TYPE_KL_1MIN

    def test_daily_bar_sub_type(self):
        from nautilus_trader.model.data import BarSpecification
        from nautilus_trader.model.enums import BarAggregation, PriceType

        spec = BarSpecification(1, BarAggregation.DAY, PriceType.LAST)
        assert bar_spec_to_futu_sub_type(spec) == FUTU_SUB_TYPE_KL_DAY

    def test_1min_bar_kl_type(self):
        from nautilus_trader.model.data import BarSpecification
        from nautilus_trader.model.enums import BarAggregation, PriceType

        spec = BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST)
        assert bar_spec_to_futu_kl_type(spec) == FUTU_KL_TYPE_1MIN

    def test_daily_bar_kl_type(self):
        from nautilus_trader.model.data import BarSpecification
        from nautilus_trader.model.enums import BarAggregation, PriceType

        spec = BarSpecification(1, BarAggregation.DAY, PriceType.LAST)
        assert bar_spec_to_futu_kl_type(spec) == FUTU_KL_TYPE_DAY

    def test_unsupported_bar_returns_none(self):
        from nautilus_trader.model.data import BarSpecification
        from nautilus_trader.model.enums import BarAggregation, PriceType

        spec = BarSpecification(1, BarAggregation.TICK, PriceType.LAST)
        assert bar_spec_to_futu_sub_type(spec) is None
        assert bar_spec_to_futu_kl_type(spec) is None
