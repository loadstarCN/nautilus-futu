"""Tests for Nautilus order -> Futu place_order parameter mapping and reports."""

from __future__ import annotations

from decimal import Decimal

import pytest
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.model.enums import OrderSide, OrderStatus, OrderType, TimeInForce, TrailingOffsetType, TriggerType
from nautilus_trader.model.identifiers import AccountId, ClientOrderId, StrategyId, TraderId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from nautilus_futu.constants import (
    FUTU_ORDER_TYPE_LIMIT_IF_TOUCHED,
    FUTU_ORDER_TYPE_MARKET,
    FUTU_ORDER_TYPE_NORMAL,
    FUTU_ORDER_TYPE_STOP,
    FUTU_ORDER_TYPE_STOP_LIMIT,
    FUTU_ORDER_TYPE_TRAILING_STOP,
    FUTU_ORDER_TYPE_TRAILING_STOP_LIMIT,
    FUTU_TIF_DAY,
    FUTU_TIF_GTC,
    FUTU_TRAIL_TYPE_AMOUNT,
    FUTU_TRAIL_TYPE_RATIO,
    FUTU_TRD_SEC_MARKET_US,
    FUTU_TRD_SIDE_BUY,
    FUTU_TRD_SIDE_SELL,
)
from nautilus_futu.parsing.instruments import parse_futu_instrument
from nautilus_futu.parsing.orders import (
    build_futu_order_params,
    client_order_id_from_remark,
    client_order_id_to_remark,
    parse_futu_order_to_report,
)

HK = parse_futu_instrument({"market": 1, "code": "00700", "lot_size": 100, "sec_type": 3})
US = parse_futu_instrument({"market": 11, "code": "AAPL", "lot_size": 1, "sec_type": 3})


@pytest.fixture
def factory():
    return OrderFactory(
        trader_id=TraderId("TESTER-000"),
        strategy_id=StrategyId("S-001"),
        clock=TestComponentStubs.clock(),
    )


class TestBuildFutuOrderParams:
    def test_limit_day(self, factory):
        order = factory.limit(HK.id, OrderSide.BUY, Quantity.from_int(100), Price.from_str("300.000"), time_in_force=TimeInForce.DAY)
        p = build_futu_order_params(order)
        assert p["order_type"] == FUTU_ORDER_TYPE_NORMAL
        assert p["trd_side"] == FUTU_TRD_SIDE_BUY
        assert p["qty"] == 100.0
        assert p["price"] == 300.0
        assert p["aux_price"] is None
        assert p["time_in_force"] == FUTU_TIF_DAY
        assert p["fill_outside_rth"] is False
        assert p["remark"] == order.client_order_id.value

    def test_nautilus_default_tif_is_gtc(self, factory):
        order = factory.limit(HK.id, OrderSide.BUY, Quantity.from_int(100), Price.from_str("300.000"))
        assert build_futu_order_params(order)["time_in_force"] == FUTU_TIF_GTC

    def test_market_gtc(self, factory):
        order = factory.market(US.id, OrderSide.SELL, Quantity.from_int(5), time_in_force=TimeInForce.GTC)
        p = build_futu_order_params(order, default_fill_outside_rth=True)
        assert p["order_type"] == FUTU_ORDER_TYPE_MARKET
        assert p["trd_side"] == FUTU_TRD_SIDE_SELL
        assert p["price"] is None
        assert p["time_in_force"] == FUTU_TIF_GTC
        assert p["fill_outside_rth"] is True

    def test_rth_tag_overrides_default(self, factory):
        order = factory.limit(US.id, OrderSide.BUY, Quantity.from_int(1), Price.from_str("190.00"), tags=["FUTU_RTH:0"])
        assert build_futu_order_params(order, default_fill_outside_rth=True)["fill_outside_rth"] is False
        order = factory.limit(US.id, OrderSide.BUY, Quantity.from_int(1), Price.from_str("190.00"), tags=["FUTU_RTH:1"])
        assert build_futu_order_params(order, default_fill_outside_rth=False)["fill_outside_rth"] is True

    def test_stop_market(self, factory):
        order = factory.stop_market(HK.id, OrderSide.SELL, Quantity.from_int(100), Price.from_str("290.000"))
        p = build_futu_order_params(order)
        assert p["order_type"] == FUTU_ORDER_TYPE_STOP
        assert p["price"] is None
        assert p["aux_price"] == 290.0

    def test_stop_limit(self, factory):
        order = factory.stop_limit(
            HK.id, OrderSide.SELL, Quantity.from_int(100), Price.from_str("289.000"), Price.from_str("290.000"),
        )
        p = build_futu_order_params(order)
        assert p["order_type"] == FUTU_ORDER_TYPE_STOP_LIMIT
        assert p["price"] == 289.0
        assert p["aux_price"] == 290.0

    def test_limit_if_touched(self, factory):
        order = factory.limit_if_touched(
            HK.id, OrderSide.BUY, Quantity.from_int(100), Price.from_str("301.000"), Price.from_str("300.000"),
        )
        p = build_futu_order_params(order)
        assert p["order_type"] == FUTU_ORDER_TYPE_LIMIT_IF_TOUCHED
        assert p["aux_price"] == 300.0

    def test_trailing_stop_price_offset(self, factory):
        order = factory.trailing_stop_market(
            HK.id, OrderSide.SELL, Quantity.from_int(100), trailing_offset=Decimal("2.5"),
            trailing_offset_type=TrailingOffsetType.PRICE, trigger_type=TriggerType.LAST_PRICE,
        )
        p = build_futu_order_params(order)
        assert p["order_type"] == FUTU_ORDER_TYPE_TRAILING_STOP
        assert p["trail_type"] == FUTU_TRAIL_TYPE_AMOUNT
        assert p["trail_value"] == 2.5

    def test_trailing_stop_limit_bps_offset(self, factory):
        order = factory.trailing_stop_limit(
            instrument_id=HK.id, order_side=OrderSide.SELL, quantity=Quantity.from_int(100),
            price=Price.from_str("280.000"), trailing_offset=Decimal("150"),
            trailing_offset_type=TrailingOffsetType.BASIS_POINTS,
            limit_offset=Decimal("0.5"), trigger_type=TriggerType.LAST_PRICE,
        )
        p = build_futu_order_params(order)
        assert p["order_type"] == FUTU_ORDER_TYPE_TRAILING_STOP_LIMIT
        assert p["trail_type"] == FUTU_TRAIL_TYPE_RATIO
        assert p["trail_value"] == 1.5  # 150 bps -> 1.5 %
        assert p["trail_spread"] == 0.5

    def test_ioc_rejected(self, factory):
        order = factory.limit(HK.id, OrderSide.BUY, Quantity.from_int(100), Price.from_str("300.000"), time_in_force=TimeInForce.IOC)
        with pytest.raises(ValueError, match="DAY and GTC"):
            build_futu_order_params(order)

    def test_post_only_rejected(self, factory):
        order = factory.limit(HK.id, OrderSide.BUY, Quantity.from_int(100), Price.from_str("300.000"), post_only=True)
        with pytest.raises(ValueError, match="post-only"):
            build_futu_order_params(order)


class TestRemark:
    def test_roundtrip(self):
        cid = ClientOrderId("O-20260912-001-000-1")
        assert client_order_id_from_remark(client_order_id_to_remark(cid)) == cid

    def test_invalid_remarks(self):
        assert client_order_id_from_remark(None) is None
        assert client_order_id_from_remark("") is None
        assert client_order_id_from_remark("   ") is None
        assert client_order_id_from_remark("has space") is None

    def test_long_remark_truncated(self):
        cid = ClientOrderId("X" * 80)
        remark = client_order_id_to_remark(cid)
        assert len(remark.encode()) == 64


class TestOrderStatusReport:
    def _order(self, **extra):
        base = {
            "trd_side": 1, "order_type": FUTU_ORDER_TYPE_STOP_LIMIT, "order_status": 5, "order_id": 42,
            "code": "AAPL", "qty": 10.0, "price": 189.5, "aux_price": 190.0, "fill_qty": 0.0,
            "sec_market": FUTU_TRD_SEC_MARKET_US, "create_timestamp": 1718400000.0,
            "update_timestamp": 1718400001.0, "time_in_force": 1, "remark": "O-123",
        }
        base.update(extra)
        return base

    def test_report_carries_client_order_id_and_trigger(self):
        report = parse_futu_order_to_report(self._order(), AccountId("FUTU-1"), US, ts_init=7)
        assert report.client_order_id == ClientOrderId("O-123")
        assert report.order_type == OrderType.STOP_LIMIT
        assert report.order_status == OrderStatus.ACCEPTED
        assert report.time_in_force == TimeInForce.GTC
        assert str(report.price) == "189.50"
        assert str(report.trigger_price) == "190.00"
        assert report.trigger_type == TriggerType.LAST_PRICE
        assert report.ts_init == 7
        assert report.instrument_id == US.id

    def test_report_without_remark(self):
        report = parse_futu_order_to_report(self._order(remark=""), AccountId("FUTU-1"))
        assert report.client_order_id is None
        assert str(report.instrument_id) == "AAPL.NYSE"

    def test_cancel_reason_on_rejected(self):
        report = parse_futu_order_to_report(self._order(order_status=3, last_err_msg="bad price"), AccountId("FUTU-1"), US)
        assert report.order_status == OrderStatus.REJECTED
        assert report.cancel_reason == "bad price"

    def test_trailing_report(self):
        order = self._order(order_type=FUTU_ORDER_TYPE_TRAILING_STOP, trail_type=FUTU_TRAIL_TYPE_RATIO,
                            trail_value=1.5, aux_price=None, price=None)
        report = parse_futu_order_to_report(order, AccountId("FUTU-1"), US)
        assert report.order_type == OrderType.TRAILING_STOP_MARKET
        assert report.trailing_offset == Decimal("150.0")
        assert report.trailing_offset_type == TrailingOffsetType.BASIS_POINTS
