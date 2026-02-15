"""Tests for Futu data parsing utilities."""

import pytest

from nautilus_futu.parsing.orders import (
    futu_order_status_to_nautilus,
    futu_order_type_to_nautilus,
    futu_time_in_force_to_nautilus,
    futu_trd_side_to_nautilus,
    nautilus_order_side_to_futu,
    nautilus_order_type_to_futu,
    parse_futu_fill_to_report,
    parse_futu_order_to_report,
    parse_futu_position_to_report,
    sec_market_to_qot_market,
    qot_market_to_currency,
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
    FUTU_QOT_MARKET_HK,
    FUTU_QOT_MARKET_US,
    FUTU_SUB_TYPE_KL_1MIN,
    FUTU_SUB_TYPE_KL_DAY,
    FUTU_TRD_SIDE_BUY,
    FUTU_TRD_SIDE_SELL,
    FUTU_TRD_SIDE_SELL_SHORT,
    FUTU_TRD_SEC_MARKET_HK,
    FUTU_TRD_SEC_MARKET_US,
    FUTU_TRD_SEC_MARKET_CN_SH,
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


class TestOrderConversionEdgeCases:
    """Edge case tests for order type conversion."""

    def test_sell_short_maps_to_sell(self):
        """Futu SELL_SHORT should map to Nautilus SELL."""
        from nautilus_trader.model.enums import OrderSide

        assert futu_trd_side_to_nautilus(FUTU_TRD_SIDE_SELL_SHORT) == OrderSide.SELL

    def test_unsupported_order_side_raises(self):
        from nautilus_trader.model.enums import OrderSide

        with pytest.raises(ValueError, match="Unsupported order side"):
            nautilus_order_side_to_futu(OrderSide.NO_ORDER_SIDE)

    def test_unsupported_futu_side_raises(self):
        with pytest.raises(ValueError, match="Unsupported Futu trade side"):
            futu_trd_side_to_nautilus(99)

    def test_unsupported_nautilus_order_type_raises(self):
        from nautilus_trader.model.enums import OrderType

        with pytest.raises(ValueError, match="Unsupported order type"):
            nautilus_order_type_to_futu(OrderType.STOP_MARKET)

    def test_unknown_futu_order_type_defaults_to_limit(self):
        """Unknown Futu order type should default to LIMIT."""
        from nautilus_trader.model.enums import OrderType

        assert futu_order_type_to_nautilus(999) == OrderType.LIMIT

    def test_futu_trd_side_buy_back(self):
        """Futu BUY_BACK(4) should map to Nautilus BUY."""
        from nautilus_trader.model.enums import OrderSide
        from nautilus_futu.constants import FUTU_TRD_SIDE_BUY_BACK

        assert futu_trd_side_to_nautilus(FUTU_TRD_SIDE_BUY_BACK) == OrderSide.BUY

    def test_futu_order_type_unknown_logs_warning(self, caplog):
        """Unknown Futu order type should return LIMIT and log a warning."""
        import logging
        from nautilus_trader.model.enums import OrderType

        with caplog.at_level(logging.WARNING, logger="nautilus_futu.parsing.orders"):
            result = futu_order_type_to_nautilus(999)
        assert result == OrderType.LIMIT
        assert "Unknown Futu order type 999" in caplog.text


class TestOrderStatusConversion:
    """Tests for Futu OrderStatus to NautilusTrader OrderStatus conversion.

    Values must match official Trd_Common.proto OrderStatus enum.
    """

    def test_unsubmitted_to_initialized(self):
        from nautilus_trader.model.enums import OrderStatus
        assert futu_order_status_to_nautilus(0) == OrderStatus.INITIALIZED   # Unsubmitted
        assert futu_order_status_to_nautilus(-1) == OrderStatus.INITIALIZED  # Unknown

    def test_waiting_submit_to_submitted(self):
        from nautilus_trader.model.enums import OrderStatus
        assert futu_order_status_to_nautilus(1) == OrderStatus.SUBMITTED  # WaitingSubmit
        assert futu_order_status_to_nautilus(2) == OrderStatus.SUBMITTED  # Submitting

    def test_submit_failed_to_rejected(self):
        from nautilus_trader.model.enums import OrderStatus
        assert futu_order_status_to_nautilus(3) == OrderStatus.REJECTED  # SubmitFailed

    def test_timeout_to_rejected(self):
        from nautilus_trader.model.enums import OrderStatus
        assert futu_order_status_to_nautilus(4) == OrderStatus.REJECTED  # TimeOut

    def test_submitted_to_accepted(self):
        from nautilus_trader.model.enums import OrderStatus
        assert futu_order_status_to_nautilus(5) == OrderStatus.ACCEPTED  # Submitted

    def test_filled_part_to_partially_filled(self):
        from nautilus_trader.model.enums import OrderStatus
        assert futu_order_status_to_nautilus(10) == OrderStatus.PARTIALLY_FILLED  # FilledPart

    def test_filled_all_to_filled(self):
        from nautilus_trader.model.enums import OrderStatus
        assert futu_order_status_to_nautilus(11) == OrderStatus.FILLED  # FilledAll

    def test_cancelling_to_pending_cancel(self):
        from nautilus_trader.model.enums import OrderStatus
        assert futu_order_status_to_nautilus(12) == OrderStatus.PENDING_CANCEL  # CancellingPart
        assert futu_order_status_to_nautilus(13) == OrderStatus.PENDING_CANCEL  # CancellingAll

    def test_cancelled_to_canceled(self):
        from nautilus_trader.model.enums import OrderStatus
        assert futu_order_status_to_nautilus(14) == OrderStatus.CANCELED  # CancelledPart
        assert futu_order_status_to_nautilus(15) == OrderStatus.CANCELED  # CancelledAll

    def test_failed_to_rejected(self):
        from nautilus_trader.model.enums import OrderStatus
        assert futu_order_status_to_nautilus(21) == OrderStatus.REJECTED  # Failed

    def test_disabled_deleted_to_canceled(self):
        from nautilus_trader.model.enums import OrderStatus
        assert futu_order_status_to_nautilus(22) == OrderStatus.CANCELED  # Disabled
        assert futu_order_status_to_nautilus(23) == OrderStatus.CANCELED  # Deleted
        assert futu_order_status_to_nautilus(24) == OrderStatus.CANCELED  # FillCancelled

    def test_unknown_status_defaults_to_initialized(self, caplog):
        import logging
        from nautilus_trader.model.enums import OrderStatus
        with caplog.at_level(logging.WARNING, logger="nautilus_futu.parsing.orders"):
            result = futu_order_status_to_nautilus(999)
        assert result == OrderStatus.INITIALIZED
        assert "Unknown Futu order status 999" in caplog.text


class TestTimeInForceConversion:
    """Tests for Futu TimeInForce to NautilusTrader TimeInForce conversion."""

    def test_none_defaults_to_day(self):
        from nautilus_trader.model.enums import TimeInForce
        assert futu_time_in_force_to_nautilus(None) == TimeInForce.DAY

    def test_zero_is_day(self):
        from nautilus_trader.model.enums import TimeInForce
        assert futu_time_in_force_to_nautilus(0) == TimeInForce.DAY

    def test_one_is_gtc(self):
        from nautilus_trader.model.enums import TimeInForce
        assert futu_time_in_force_to_nautilus(1) == TimeInForce.GTC


class TestParseOrderToReport:
    """Tests for parsing Futu order dict to OrderStatusReport."""

    def _make_order_dict(self, **overrides):
        base = {
            "trd_side": 1,
            "order_type": 1,
            "order_status": 5,
            "order_id": 123456,
            "order_id_ex": "ORD123456",
            "code": "00700",
            "name": "TENCENT",
            "qty": 100.0,
            "price": 350.0,
            "create_time": "2024-06-01 10:00:00",
            "update_time": "2024-06-01 10:00:01",
            "fill_qty": 50.0,
            "fill_avg_price": 349.5,
            "sec_market": 1,
            "create_timestamp": 1717225200.0,
            "update_timestamp": 1717225201.0,
            "time_in_force": 0,
            "remark": "",
        }
        base.update(overrides)
        return base

    def test_basic_order_report(self):
        from nautilus_trader.model.enums import OrderSide, OrderStatus, OrderType
        from nautilus_trader.model.identifiers import AccountId

        order = self._make_order_dict()
        account_id = AccountId("FUTU-12345")
        report = parse_futu_order_to_report(order, account_id)

        assert report.account_id == account_id
        assert report.venue_order_id.value == "123456"
        assert report.order_side == OrderSide.BUY
        assert report.order_type == OrderType.LIMIT
        assert report.order_status == OrderStatus.ACCEPTED

    def test_sell_market_order_report(self):
        from nautilus_trader.model.enums import OrderSide, OrderType
        from nautilus_trader.model.identifiers import AccountId

        order = self._make_order_dict(trd_side=2, order_type=2)
        report = parse_futu_order_to_report(order, AccountId("FUTU-1"))
        assert report.order_side == OrderSide.SELL
        assert report.order_type == OrderType.MARKET

    def test_us_market_sec_market(self):
        from nautilus_trader.model.identifiers import AccountId

        order = self._make_order_dict(code="AAPL", sec_market=2)
        report = parse_futu_order_to_report(order, AccountId("FUTU-1"))
        assert report.instrument_id.venue.value == "NYSE"


class TestParseFillToReport:
    """Tests for parsing Futu fill dict to FillReport."""

    def _make_fill_dict(self, **overrides):
        base = {
            "trd_side": 1,
            "fill_id": 789,
            "fill_id_ex": "FILL789",
            "order_id": 123456,
            "order_id_ex": "ORD123456",
            "code": "00700",
            "name": "TENCENT",
            "qty": 100.0,
            "price": 350.0,
            "create_time": "2024-06-01 10:00:05",
            "create_timestamp": 1717225205.0,
            "update_timestamp": 1717225205.0,
            "sec_market": 1,
            "status": None,
        }
        base.update(overrides)
        return base

    def test_basic_fill_report(self):
        from nautilus_trader.model.enums import OrderSide
        from nautilus_trader.model.identifiers import AccountId

        fill = self._make_fill_dict()
        report = parse_futu_fill_to_report(fill, AccountId("FUTU-1"))
        assert report.trade_id.value == "789"
        assert report.order_side == OrderSide.BUY
        assert report.venue_order_id.value == "123456"

    def test_sell_fill_report(self):
        from nautilus_trader.model.enums import OrderSide
        from nautilus_trader.model.identifiers import AccountId

        fill = self._make_fill_dict(trd_side=2)
        report = parse_futu_fill_to_report(fill, AccountId("FUTU-1"))
        assert report.order_side == OrderSide.SELL


class TestParsePositionToReport:
    """Tests for parsing Futu position dict to PositionStatusReport."""

    def _make_position_dict(self, **overrides):
        base = {
            "position_id": 1001,
            "position_side": 0,
            "code": "00700",
            "name": "TENCENT",
            "qty": 200.0,
            "can_sell_qty": 200.0,
            "price": 350.0,
            "cost_price": 340.0,
            "val": 70000.0,
            "pl_val": 2000.0,
            "pl_ratio": 0.0294,
            "sec_market": 1,
            "unrealized_pl": 2000.0,
            "realized_pl": 0.0,
            "currency": None,
        }
        base.update(overrides)
        return base

    def test_long_position(self):
        from nautilus_trader.model.enums import PositionSide
        from nautilus_trader.model.identifiers import AccountId

        pos = self._make_position_dict()
        report = parse_futu_position_to_report(pos, AccountId("FUTU-1"))
        assert report.position_side == PositionSide.LONG

    def test_short_position(self):
        from nautilus_trader.model.enums import PositionSide
        from nautilus_trader.model.identifiers import AccountId

        pos = self._make_position_dict(position_side=1, qty=100.0)
        report = parse_futu_position_to_report(pos, AccountId("FUTU-1"))
        assert report.position_side == PositionSide.SHORT

    def test_flat_position(self):
        from nautilus_trader.model.enums import PositionSide
        from nautilus_trader.model.identifiers import AccountId

        pos = self._make_position_dict(qty=0.0)
        report = parse_futu_position_to_report(pos, AccountId("FUTU-1"))
        assert report.position_side == PositionSide.FLAT


class TestSecMarketToQotMarket:
    """Tests for sec_market_to_qot_market helper."""

    def test_hk_mapping(self):
        assert sec_market_to_qot_market(FUTU_TRD_SEC_MARKET_HK) == FUTU_QOT_MARKET_HK

    def test_us_mapping(self):
        assert sec_market_to_qot_market(FUTU_TRD_SEC_MARKET_US) == FUTU_QOT_MARKET_US

    def test_cn_sh_mapping(self):
        from nautilus_futu.constants import FUTU_QOT_MARKET_CNSH
        assert sec_market_to_qot_market(FUTU_TRD_SEC_MARKET_CN_SH) == FUTU_QOT_MARKET_CNSH

    def test_none_returns_zero(self):
        assert sec_market_to_qot_market(None) == 0

    def test_unknown_returns_zero(self):
        assert sec_market_to_qot_market(9999) == 0


class TestQotMarketToCurrency:
    """Tests for qot_market_to_currency helper."""

    def test_hk_returns_hkd(self):
        currency = qot_market_to_currency(FUTU_QOT_MARKET_HK)
        assert str(currency) == "HKD"

    def test_us_returns_usd(self):
        currency = qot_market_to_currency(FUTU_QOT_MARKET_US)
        assert str(currency) == "USD"

    def test_unknown_market_returns_usd(self):
        """Unknown market codes should fall back to USD."""
        currency = qot_market_to_currency(9999)
        assert str(currency) == "USD"
