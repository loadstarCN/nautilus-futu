"""Tests for the execution client: funds parsing and the push -> event pipeline.

The execution client is exercised with a real NautilusTrader ``Cache`` and
``MessageBus`` (events sent to ``ExecEngine.process`` are captured and applied
to the cached order, mimicking the execution engine) and a mocked Rust client.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import CancelAllOrders, CancelOrder, ModifyOrder, SubmitOrder
from nautilus_trader.model.enums import AccountType, OrderSide, OrderStatus, TimeInForce
from nautilus_trader.model.events import (
    OrderAccepted,
    OrderCanceled,
    OrderCancelRejected,
    OrderFilled,
    OrderModifyRejected,
    OrderRejected,
    OrderSubmitted,
    OrderUpdated,
)
from nautilus_trader.model.identifiers import AccountId, ClientOrderId, StrategyId, TraderId, VenueOrderId
from nautilus_trader.model.objects import Currency, Price, Quantity
from nautilus_trader.test_kit.stubs.events import TestEventStubs
from nautilus_trader.test_kit.stubs.execution import TestExecStubs

from nautilus_futu.config import FutuExecClientConfig
from nautilus_futu.constants import (
    FUTU_MODIFY_ORDER_OP_CANCEL,
    FUTU_MODIFY_ORDER_OP_NORMAL,
    FUTU_ORDER_STATUS_CANCELLED_ALL,
    FUTU_ORDER_STATUS_FAILED,
    FUTU_ORDER_STATUS_FILLED_ALL,
    FUTU_ORDER_STATUS_SUBMIT_FAILED,
    FUTU_ORDER_STATUS_SUBMITTED,
    FUTU_ORDER_TYPE_NORMAL,
    FUTU_TIF_DAY,
    FUTU_TIF_GTC,
    FUTU_TRD_MARKET_HK,
    FUTU_TRD_MARKET_US,
    FUTU_TRD_SEC_MARKET_HK,
    FUTU_TRD_SIDE_BUY,
)
from nautilus_futu.execution import (
    FutuLiveExecutionClient,
    parse_funds_to_balance,
    parse_funds_to_balances,
    parse_funds_to_margins,
)
from nautilus_futu.parsing.instruments import parse_futu_instrument
from nautilus_futu.providers import FutuInstrumentProvider

USD = Currency.from_str("USD")
HKD = Currency.from_str("HKD")

ACC_ID = 12345
ACCOUNT_ID = AccountId(f"FUTU-{ACC_ID}")
TRADER_ID = TraderId("TESTER-000")
STRATEGY_ID = StrategyId("S-001")


# ─────────────────────────────────────────────────────────
# Funds parsing
# ─────────────────────────────────────────────────────────


class TestParseFundsToBalance:
    """Balances are cash-based: total=cash, locked=frozen_cash, free=cash-frozen."""

    def test_cash_minus_frozen(self):
        funds = {"total_assets": 10000.0, "cash": 8000.0, "frozen_cash": 500.0, "available_funds": None}
        b = parse_funds_to_balance(funds, USD)
        assert float(b.total) == 8000.0
        assert float(b.free) == 7500.0
        assert float(b.locked) == 500.0
        assert str(b.currency) == "USD"

    def test_total_assets_is_ignored(self):
        """Position market value must not be counted as spendable cash."""
        funds = {"total_assets": 50000.0, "market_val": 42000.0, "cash": 8000.0, "frozen_cash": 0.0}
        b = parse_funds_to_balance(funds, USD)
        assert float(b.total) == 8000.0
        assert float(b.free) == 8000.0

    def test_no_frozen(self):
        funds = {"cash": 4173.12, "frozen_cash": 0.0, "available_funds": None, "power": 4173.12}
        b = parse_funds_to_balance(funds, USD)
        assert float(b.free) == 4173.12
        assert float(b.locked) == 0.0

    def test_missing_fields_default_zero(self):
        b = parse_funds_to_balance({}, USD)
        assert float(b.total) == 0.0
        assert float(b.free) == 0.0
        assert float(b.locked) == 0.0

    def test_invariant_total_minus_locked_equals_free(self):
        funds = {"cash": 6000.0, "frozen_cash": 1234.56}
        b = parse_funds_to_balance(funds, HKD)
        assert abs(float(b.total) - float(b.locked) - float(b.free)) < 0.001


class TestParseFundsToBalances:
    def test_single_currency_uses_account_currency(self):
        funds = {"cash": 100.0, "frozen_cash": 10.0, "currency": 1}  # HKD
        balances = parse_funds_to_balances(funds, USD)
        assert len(balances) == 1
        assert str(balances[0].currency) == "HKD"
        assert float(balances[0].free) == 90.0

    def test_multi_currency_cash_info_list(self):
        funds = {
            "cash": 1.0,
            "frozen_cash": 0.0,
            "currency": 1,
            "cash_info_list": [
                {"currency": 1, "cash": 1000.0, "available_balance": 900.0, "net_cash_power": 900.0},
                {"currency": 2, "cash": 500.0, "available_balance": 500.0, "net_cash_power": 500.0},
                {"currency": 3, "cash": 0.0, "available_balance": 0.0, "net_cash_power": 0.0},
                {"currency": 999, "cash": 5.0},  # unknown currency ignored
            ],
        }
        balances = parse_funds_to_balances(funds, USD)
        by_ccy = {str(b.currency): b for b in balances}
        assert set(by_ccy) == {"HKD", "USD", "CNH"}
        assert float(by_ccy["HKD"].total) == 1000.0
        assert float(by_ccy["HKD"].locked) == 100.0
        assert float(by_ccy["HKD"].free) == 900.0
        assert float(by_ccy["USD"].free) == 500.0

    def test_available_above_cash_means_nothing_locked(self):
        funds = {"cash_info_list": [{"currency": 2, "cash": 100.0, "available_balance": 250.0}]}
        balances = parse_funds_to_balances(funds, USD)
        assert float(balances[0].locked) == 0.0
        assert float(balances[0].free) == 100.0


class TestParseFundsToMargins:
    def test_no_margin_fields(self):
        assert parse_funds_to_margins({"cash": 1.0}, USD) == []

    def test_margin_fields(self):
        margins = parse_funds_to_margins({"initial_margin": 100.0, "maintenance_margin": 50.0}, USD)
        assert len(margins) == 1
        assert float(margins[0].initial) == 100.0
        assert float(margins[0].maintenance) == 50.0


# ─────────────────────────────────────────────────────────
# Execution client harness
# ─────────────────────────────────────────────────────────


HK_INSTRUMENT = parse_futu_instrument({"market": 1, "code": "00700", "lot_size": 100, "sec_type": 3})
US_INSTRUMENT = parse_futu_instrument({"market": 11, "code": "AAPL", "lot_size": 1, "sec_type": 3})


class Harness:
    """Real cache/msgbus + mocked Rust client; captured events are applied to orders."""

    def __init__(self, **config_kwargs):
        self.loop = asyncio.new_event_loop()
        self.clock = LiveClock()
        self.msgbus = MessageBus(trader_id=TRADER_ID, clock=self.clock)
        self.cache = Cache()
        self.cache.add_instrument(HK_INSTRUMENT)
        self.cache.add_instrument(US_INSTRUMENT)
        self.rust = MagicMock()
        self.rust.place_order.return_value = {"order_id": 555, "order_id_ex": "EX555"}
        self.rust.modify_order.return_value = None
        self.events: list = []
        self.msgbus.register(endpoint="ExecEngine.process", handler=self._on_event)
        self.msgbus.register(endpoint="Portfolio.update_account", handler=lambda e: None)

        config = FutuExecClientConfig(trd_env=0, acc_id=ACC_ID, trd_market=FUTU_TRD_MARKET_HK, **config_kwargs)
        self.client = FutuLiveExecutionClient(
            loop=self.loop,
            client=self.rust,
            msgbus=self.msgbus,
            cache=self.cache,
            clock=self.clock,
            instrument_provider=FutuInstrumentProvider(self.rust),
            config=config,
        )
        self.client._set_account_id(ACCOUNT_ID)
        self.client._trd_market_auth_list = [FUTU_TRD_MARKET_HK, FUTU_TRD_MARKET_US]

    def _on_event(self, event) -> None:
        self.events.append(event)
        order = self.cache.order(event.client_order_id)
        if order is not None:
            order.apply(event)
            self.cache.update_order(order)

    def events_of(self, cls):
        return [e for e in self.events if isinstance(e, cls)]

    def add_limit_order(self, client_order_id="O-1", instrument=HK_INSTRUMENT, price="300.000", qty=100, submitted=True, **kwargs):
        order = TestExecStubs.limit_order(
            instrument=instrument,
            order_side=OrderSide.BUY,
            price=Price.from_str(price),
            quantity=Quantity.from_int(qty),
            client_order_id=ClientOrderId(client_order_id),
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            **kwargs,
        )
        self.cache.add_order(order)
        if submitted:
            order.apply(TestEventStubs.order_submitted(order, account_id=ACCOUNT_ID))
            self.cache.update_order(order)
        return order

    def accept(self, order, venue_order_id="555"):
        order.apply(TestEventStubs.order_accepted(order, account_id=ACCOUNT_ID, venue_order_id=VenueOrderId(venue_order_id)))
        self.cache.update_order(order)

    def pending_update(self, order):
        """The strategy applies OrderPendingUpdate before sending ModifyOrder."""
        order.apply(TestEventStubs.order_pending_update(order))
        self.cache.update_order(order)

    def pending_cancel(self, order):
        """The strategy applies OrderPendingCancel before sending CancelOrder/CancelAllOrders."""
        order.apply(TestEventStubs.order_pending_cancel(order))
        self.cache.update_order(order)

    def run(self, coro):
        return self.loop.run_until_complete(coro)

    def order_push(self, order_id=555, status=FUTU_ORDER_STATUS_SUBMITTED, remark="", **extra):
        order = {
            "trd_side": FUTU_TRD_SIDE_BUY,
            "order_type": FUTU_ORDER_TYPE_NORMAL,
            "order_status": status,
            "order_id": order_id,
            "order_id_ex": f"EX{order_id}",
            "code": "00700",
            "name": "TENCENT",
            "qty": 100.0,
            "price": 300.0,
            "fill_qty": 0.0,
            "fill_avg_price": 0.0,
            "sec_market": FUTU_TRD_SEC_MARKET_HK,
            "create_timestamp": 1718400000.0,
            "update_timestamp": 1718400001.0,
            "time_in_force": FUTU_TIF_DAY,
            "remark": remark,
            "last_err_msg": "",
        }
        order.update(extra)
        return {"trd_env": 0, "acc_id": ACC_ID, "order": order}

    def fill_push(self, order_id=555, fill_id=9001, qty=100.0, price=299.8):
        return {
            "trd_env": 0,
            "acc_id": ACC_ID,
            "fill": {
                "trd_side": FUTU_TRD_SIDE_BUY,
                "fill_id": fill_id,
                "fill_id_ex": f"FEX{fill_id}",
                "order_id": order_id,
                "order_id_ex": f"EX{order_id}",
                "code": "00700",
                "name": "TENCENT",
                "qty": qty,
                "price": price,
                "sec_market": FUTU_TRD_SEC_MARKET_HK,
                "create_timestamp": 1718400002.0,
                "status": 0,
            },
        }


@pytest.fixture
def h():
    harness = Harness()
    yield harness
    harness.loop.close()


class TestSubmitOrder:
    def test_submit_places_order_with_remark_and_indexes_venue_id(self, h):
        order = h.add_limit_order(submitted=False)
        cmd = SubmitOrder(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, order=order, command_id=UUID4(), ts_init=0)

        h.run(h.client._submit_order(cmd))

        assert h.events_of(OrderSubmitted)
        assert not h.events_of(OrderRejected)
        args = h.rust.place_order.call_args.args
        # (trd_env, acc_id, trd_market, trd_side, order_type, code, qty, price, sec_market, remark, tif, rth, aux, ...)
        assert args[0:3] == (0, ACC_ID, FUTU_TRD_MARKET_HK)
        assert args[3] == FUTU_TRD_SIDE_BUY
        assert args[4] == FUTU_ORDER_TYPE_NORMAL
        assert args[5] == "00700"
        assert args[6] == 100.0
        assert args[7] == 300.0
        assert args[8] == FUTU_TRD_SEC_MARKET_HK
        assert args[9] == "O-1"  # remark carries the client order id
        assert args[10] == FUTU_TIF_GTC  # Nautilus orders default to GTC
        assert h.cache.client_order_id(VenueOrderId("555")) == ClientOrderId("O-1")
        assert h.cache.venue_order_id(ClientOrderId("O-1")) == VenueOrderId("555")

    def test_submit_routes_us_instrument_to_us_market(self, h):
        order = h.add_limit_order(client_order_id="O-US", instrument=US_INSTRUMENT, price="190.00", qty=10, submitted=False)
        cmd = SubmitOrder(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, order=order, command_id=UUID4(), ts_init=0)
        h.run(h.client._submit_order(cmd))
        assert h.rust.place_order.call_args.args[2] == FUTU_TRD_MARKET_US

    def test_submit_day(self, h):
        order = h.add_limit_order(submitted=False, time_in_force=TimeInForce.DAY)
        cmd = SubmitOrder(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, order=order, command_id=UUID4(), ts_init=0)
        h.run(h.client._submit_order(cmd))
        assert h.rust.place_order.call_args.args[10] == FUTU_TIF_DAY

    def test_submit_unsupported_tif_is_rejected_locally(self, h):
        order = h.add_limit_order(submitted=False, time_in_force=TimeInForce.IOC)
        cmd = SubmitOrder(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, order=order, command_id=UUID4(), ts_init=0)
        h.run(h.client._submit_order(cmd))
        assert not h.rust.place_order.called
        rejected = h.events_of(OrderRejected)
        assert len(rejected) == 1
        assert "time-in-force" in rejected[0].reason

    def test_submit_venue_error_is_rejected(self, h):
        h.rust.place_order.side_effect = RuntimeError("Place order failed: insufficient funds")
        order = h.add_limit_order(submitted=False)
        cmd = SubmitOrder(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, order=order, command_id=UUID4(), ts_init=0)
        h.run(h.client._submit_order(cmd))
        rejected = h.events_of(OrderRejected)
        assert len(rejected) == 1
        assert "insufficient funds" in rejected[0].reason
        assert order.status == OrderStatus.REJECTED


class TestOrderPush:
    def test_submitted_push_generates_accepted(self, h):
        order = h.add_limit_order()
        h.cache.add_venue_order_id(order.client_order_id, VenueOrderId("555"))

        h.client._handle_push_order(h.order_push())

        accepted = h.events_of(OrderAccepted)
        assert len(accepted) == 1
        assert accepted[0].venue_order_id == VenueOrderId("555")
        assert accepted[0].ts_event == 1718400001 * 1_000_000_000
        assert order.status == OrderStatus.ACCEPTED

    def test_push_before_place_order_returns_matches_via_remark(self, h):
        """The venue can push before place_order() returns; remark resolves the order."""
        order = h.add_limit_order(client_order_id="O-REMARK")

        h.client._handle_push_order(h.order_push(order_id=777, remark="O-REMARK"))

        assert len(h.events_of(OrderAccepted)) == 1
        assert h.cache.client_order_id(VenueOrderId("777")) == ClientOrderId("O-REMARK")
        assert order.status == OrderStatus.ACCEPTED

    def test_external_order_push_ignored(self, h):
        h.client._handle_push_order(h.order_push(order_id=999, remark="manual"))
        assert h.events == []

    def test_wrong_account_ignored(self, h):
        order = h.add_limit_order()
        h.cache.add_venue_order_id(order.client_order_id, VenueOrderId("555"))
        data = h.order_push()
        data["acc_id"] = 1
        h.client._handle_push_order(data)
        assert h.events == []

    def test_duplicate_accepted_push_is_idempotent(self, h):
        order = h.add_limit_order()
        h.cache.add_venue_order_id(order.client_order_id, VenueOrderId("555"))
        h.client._handle_push_order(h.order_push())
        h.client._handle_push_order(h.order_push())
        assert len(h.events_of(OrderAccepted)) == 1
        assert len(h.events_of(OrderUpdated)) == 0

    def test_accepted_push_with_new_price_generates_updated(self, h):
        order = h.add_limit_order()
        h.accept(order)
        h.client._handle_push_order(h.order_push(price=310.0))
        updated = h.events_of(OrderUpdated)
        assert len(updated) == 1
        assert str(updated[0].price) == "310.000"
        assert order.price == Price.from_str("310.000")

    def test_cancelled_push_generates_canceled(self, h):
        order = h.add_limit_order()
        h.accept(order)
        h.client._handle_push_order(h.order_push(status=FUTU_ORDER_STATUS_CANCELLED_ALL))
        assert len(h.events_of(OrderCanceled)) == 1
        assert order.status == OrderStatus.CANCELED

    def test_submit_failed_push_generates_rejected(self, h):
        order = h.add_limit_order()
        h.cache.add_venue_order_id(order.client_order_id, VenueOrderId("555"))
        h.client._handle_push_order(h.order_push(status=FUTU_ORDER_STATUS_SUBMIT_FAILED, last_err_msg="price out of range"))
        rejected = h.events_of(OrderRejected)
        assert len(rejected) == 1
        assert rejected[0].reason == "price out of range"

    def test_failed_after_accept_becomes_canceled(self, h):
        """FAILED on a working order can't be REJECTED (invalid FSM); it is treated as canceled."""
        order = h.add_limit_order()
        h.accept(order)
        h.client._handle_push_order(h.order_push(status=FUTU_ORDER_STATUS_FAILED, last_err_msg="venue error"))
        assert len(h.events_of(OrderRejected)) == 0
        assert len(h.events_of(OrderCanceled)) == 1
        assert order.status == OrderStatus.CANCELED

    def test_filled_status_before_accept_generates_accepted(self, h):
        order = h.add_limit_order()
        h.cache.add_venue_order_id(order.client_order_id, VenueOrderId("555"))
        h.client._handle_push_order(h.order_push(status=FUTU_ORDER_STATUS_FILLED_ALL, fill_qty=100.0))
        assert len(h.events_of(OrderAccepted)) == 1
        assert len(h.events_of(OrderFilled)) == 0  # fills only come from 2218


class TestFillPush:
    def test_fill_generates_filled(self, h):
        order = h.add_limit_order()
        h.accept(order)

        h.client._handle_push_fill(h.fill_push())

        fills = h.events_of(OrderFilled)
        assert len(fills) == 1
        fill = fills[0]
        assert fill.trade_id.value == "9001"
        assert str(fill.last_px) == "299.800"
        assert int(fill.last_qty) == 100
        assert str(fill.currency) == "HKD"
        assert fill.ts_event == 1718400002 * 1_000_000_000
        assert order.status == OrderStatus.FILLED

    def test_fill_without_prior_accept_emits_accept_first(self, h):
        order = h.add_limit_order()
        h.cache.add_venue_order_id(order.client_order_id, VenueOrderId("555"))
        h.client._handle_push_fill(h.fill_push(qty=40.0))
        assert [type(e) for e in h.events] == [OrderAccepted, OrderFilled]
        assert order.status == OrderStatus.PARTIALLY_FILLED

    def test_duplicate_fill_ignored(self, h):
        order = h.add_limit_order()
        h.accept(order)
        h.client._handle_push_fill(h.fill_push(qty=40.0))
        h.client._handle_push_fill(h.fill_push(qty=40.0))
        assert len(h.events_of(OrderFilled)) == 1

    def test_cancelled_fill_ignored(self, h):
        order = h.add_limit_order()
        h.accept(order)
        data = h.fill_push()
        data["fill"]["status"] = 1
        h.client._handle_push_fill(data)
        assert h.events == []

    def test_fill_for_unknown_order_ignored(self, h):
        h.client._handle_push_fill(h.fill_push(order_id=4242))
        assert h.events == []


class TestModifyCancel:
    def test_modify_success_generates_updated(self, h):
        order = h.add_limit_order()
        h.accept(order)
        h.pending_update(order)
        cmd = ModifyOrder(
            trader_id=TRADER_ID, strategy_id=STRATEGY_ID, instrument_id=order.instrument_id,
            client_order_id=order.client_order_id, venue_order_id=VenueOrderId("555"),
            quantity=Quantity.from_int(200), price=Price.from_str("305.000"), trigger_price=None,
            command_id=UUID4(), ts_init=0,
        )
        h.run(h.client._modify_order(cmd))
        args = h.rust.modify_order.call_args.args
        assert args[3] == 555
        assert args[4] == FUTU_MODIFY_ORDER_OP_NORMAL
        assert args[5] == 200.0
        assert args[6] == 305.0
        assert len(h.events_of(OrderUpdated)) == 1
        assert order.quantity == Quantity.from_int(200)
        assert order.status == OrderStatus.ACCEPTED

    def test_modify_failure_generates_modify_rejected(self, h):
        order = h.add_limit_order()
        h.accept(order)
        h.pending_update(order)
        h.rust.modify_order.side_effect = RuntimeError("Modify order failed: not allowed")
        cmd = ModifyOrder(
            trader_id=TRADER_ID, strategy_id=STRATEGY_ID, instrument_id=order.instrument_id,
            client_order_id=order.client_order_id, venue_order_id=VenueOrderId("555"),
            quantity=None, price=Price.from_str("305.000"), trigger_price=None,
            command_id=UUID4(), ts_init=0,
        )
        h.run(h.client._modify_order(cmd))
        assert len(h.events_of(OrderModifyRejected)) == 1
        assert order.status == OrderStatus.ACCEPTED  # back from PENDING_UPDATE

    def test_cancel_failure_generates_cancel_rejected(self, h):
        order = h.add_limit_order()
        h.accept(order)
        h.pending_cancel(order)
        h.rust.modify_order.side_effect = RuntimeError("Modify order failed: already filled")
        cmd = CancelOrder(
            trader_id=TRADER_ID, strategy_id=STRATEGY_ID, instrument_id=order.instrument_id,
            client_order_id=order.client_order_id, venue_order_id=VenueOrderId("555"),
            command_id=UUID4(), ts_init=0,
        )
        h.run(h.client._cancel_order(cmd))
        assert len(h.events_of(OrderCancelRejected)) == 1
        assert order.status == OrderStatus.ACCEPTED

    def test_cancel_all_only_touches_matching_instrument(self, h):
        hk = h.add_limit_order(client_order_id="O-HK")
        h.accept(hk, "1")
        us = h.add_limit_order(client_order_id="O-US", instrument=US_INSTRUMENT, price="190.00", qty=10)
        h.accept(us, "2")
        h.pending_cancel(hk)  # the strategy marks matching orders before sending the command

        cmd = CancelAllOrders(
            trader_id=TRADER_ID, strategy_id=STRATEGY_ID, instrument_id=HK_INSTRUMENT.id,
            order_side=OrderSide.NO_ORDER_SIDE, command_id=UUID4(), ts_init=0,
        )
        h.run(h.client._cancel_all_orders(cmd))

        assert h.rust.modify_order.call_count == 1
        args = h.rust.modify_order.call_args.args
        assert args[3] == 1  # the HK order only
        assert args[4] == FUTU_MODIFY_ORDER_OP_CANCEL
        assert hk.status == OrderStatus.PENDING_CANCEL
        assert us.status == OrderStatus.ACCEPTED

    def test_cancel_all_respects_side(self, h):
        hk = h.add_limit_order(client_order_id="O-HK")
        h.accept(hk, "1")
        h.pending_cancel(hk)
        cmd = CancelAllOrders(
            trader_id=TRADER_ID, strategy_id=STRATEGY_ID, instrument_id=HK_INSTRUMENT.id,
            order_side=OrderSide.SELL, command_id=UUID4(), ts_init=0,
        )
        h.run(h.client._cancel_all_orders(cmd))
        assert h.rust.modify_order.call_count == 0


class TestAccountType:
    def test_margin_config_sets_margin_account(self):
        harness = Harness(account_type="MARGIN")
        try:
            assert harness.client.account_type == AccountType.MARGIN
        finally:
            harness.loop.close()

    def test_default_is_cash(self, h):
        assert h.client.account_type == AccountType.CASH


class TestPushDefensive:
    """Malformed pushes must never raise out of the handlers."""

    def test_missing_order_key(self, h):
        h.client._handle_push_order({"trd_env": 0, "acc_id": ACC_ID})

    def test_missing_order_status(self, h):
        h.client._handle_push_order({"trd_env": 0, "acc_id": ACC_ID, "order": {"order_id": 1}})

    def test_missing_order_id(self, h):
        h.client._handle_push_order({"trd_env": 0, "acc_id": ACC_ID, "order": {"order_status": 5}})

    def test_empty_data(self, h):
        h.client._handle_push_order({})
        h.client._handle_push_fill({})

    def test_missing_fill_key(self, h):
        h.client._handle_push_fill({"trd_env": 0, "acc_id": ACC_ID})

    def test_fill_missing_order_id(self, h):
        h.client._handle_push_fill({"trd_env": 0, "acc_id": ACC_ID, "fill": {"fill_id": 1}})
        assert h.events == []
