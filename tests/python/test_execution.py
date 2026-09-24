"""Tests for the execution client: funds parsing and the push -> event pipeline.

The execution client is exercised with a real NautilusTrader ``Cache`` and
``MessageBus`` (events sent to ``ExecEngine.process`` are captured and applied
to the cached order, mimicking the execution engine) and a mocked Rust client.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import (
    CancelAllOrders,
    CancelOrder,
    GenerateFillReports,
    GenerateOrderStatusReport,
    GenerateOrderStatusReports,
    ModifyOrder,
    SubmitOrder,
    SubmitOrderList,
)
from nautilus_trader.model.enums import AccountType, ContingencyType, OrderSide, OrderStatus, TimeInForce
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
from nautilus_trader.model.orders import LimitOrder
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
    FUTU_TRD_SEC_MARKET_US,
    FUTU_TRD_SIDE_BUY,
)
from nautilus_futu.execution import (
    FutuLiveExecutionClient,
    history_query_range,
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
        self.account_states: list = []
        self.msgbus.register(endpoint="ExecEngine.process", handler=self._on_event)
        self.msgbus.register(endpoint="Portfolio.update_account", handler=self.account_states.append)

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

    def close(self):
        """Cancel leftover background tasks (debounced account refreshes) and close the loop."""
        pending = asyncio.all_tasks(self.loop)
        for task in pending:
            task.cancel()
        if pending:
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self.loop.close()

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
    harness.close()


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

    def test_ack_push_during_pending_update_is_silent(self, h):
        """The modify request path emits OrderUpdated; the venue ack must not duplicate it."""
        order = h.add_limit_order()
        h.accept(order)
        h.pending_update(order)
        h.client._handle_push_order(h.order_push(price=310.0))
        assert h.events_of(OrderUpdated) == []
        assert order.status == OrderStatus.PENDING_UPDATE

    def test_submit_failed_reason_never_leaks_remark(self, h):
        order = h.add_limit_order()
        h.cache.add_venue_order_id(order.client_order_id, VenueOrderId("555"))
        h.client._handle_push_order(h.order_push(status=FUTU_ORDER_STATUS_SUBMIT_FAILED, remark="O-1", last_err_msg=""))
        rejected = h.events_of(OrderRejected)
        assert len(rejected) == 1
        assert "O-1" not in rejected[0].reason
        assert "status" in rejected[0].reason

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


class TestAccountRefresh:
    def test_refresh_failure_keeps_last_state(self, h):
        h.rust.get_funds.return_value = {"cash": 1000.0, "frozen_cash": 0.0, "currency": 1}
        h.run(h.client._update_account_state(initial=True))
        assert len(h.account_states) == 1
        h.rust.get_funds.side_effect = RuntimeError("Get funds failed: timeout")
        h.run(h.client._update_account_state())
        assert len(h.account_states) == 1  # no zero-balance state pushed on a transient failure

    def test_initial_failure_registers_zero_balance(self, h):
        h.rust.get_funds.side_effect = RuntimeError("Get funds failed: timeout")
        h.run(h.client._update_account_state(initial=True))
        assert len(h.account_states) == 1
        assert float(h.account_states[0].balances[0].total) == 0.0

    def test_account_discovery_treats_missing_status_as_active(self, h):
        h.client._acc_id = 0
        h.rust.get_acc_list.return_value = [
            {"acc_id": 777, "trd_env": 0, "acc_status": None, "trd_market_auth_list": [FUTU_TRD_MARKET_HK], "acc_type": 1},
        ]
        h.run(h.client._discover_account())
        assert h.client._acc_id == 777


class TestAccountType:
    def test_margin_config_sets_margin_account(self):
        harness = Harness(account_type="MARGIN")
        try:
            assert harness.client.account_type == AccountType.MARGIN
        finally:
            harness.close()

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


# ─────────────────────────────────────────────────────────
# Reports / reconciliation lookback
# ─────────────────────────────────────────────────────────

# 2024-06-14 13:20:00 UTC = 21:20 in Hong Kong, 09:20 in New York
NOW_NS = 1_718_371_200 * 1_000_000_000


class TestHistoryQueryRange:
    def test_no_start_means_today_only(self):
        assert history_query_range(None, None, NOW_NS, FUTU_TRD_MARKET_HK) is None

    def test_start_within_today_needs_no_history(self):
        start = datetime(2024, 6, 14, 2, 0, tzinfo=UTC)  # 10:00 HKT, same trading day
        assert history_query_range(start, None, NOW_NS, FUTU_TRD_MARKET_HK) is None

    def test_start_before_today_uses_market_local_time(self):
        start = datetime(2024, 6, 11, 1, 30, tzinfo=UTC)
        assert history_query_range(start, None, NOW_NS, FUTU_TRD_MARKET_HK) == (
            "2024-06-11 09:30:00",
            "2024-06-14 21:20:00",
        )

    def test_us_market_uses_eastern_time_and_explicit_end(self):
        start = datetime(2024, 6, 13, 13, 30, tzinfo=UTC)  # 09:30 EDT the previous day
        end = datetime(2024, 6, 13, 20, 0, tzinfo=UTC)
        assert history_query_range(start, end, NOW_NS, FUTU_TRD_MARKET_US) == (
            "2024-06-13 09:30:00",
            "2024-06-13 16:00:00",
        )

    def test_naive_start_is_utc(self):
        start = datetime(2024, 6, 11, 1, 30)
        assert history_query_range(start, None, NOW_NS, FUTU_TRD_MARKET_HK)[0] == "2024-06-11 09:30:00"


def _order_dict(order_id, code="00700", sec_market=FUTU_TRD_SEC_MARKET_HK, status=FUTU_ORDER_STATUS_FILLED_ALL, remark=""):
    return {
        "trd_side": FUTU_TRD_SIDE_BUY,
        "order_type": FUTU_ORDER_TYPE_NORMAL,
        "order_status": status,
        "order_id": order_id,
        "code": code,
        "qty": 100.0,
        "price": 300.0,
        "fill_qty": 100.0,
        "fill_avg_price": 300.0,
        "sec_market": sec_market,
        "create_timestamp": 1718000000.0,
        "update_timestamp": 1718000001.0,
        "time_in_force": FUTU_TIF_DAY,
        "remark": remark,
        "last_err_msg": "",
    }


def _fill_dict(fill_id, order_id, code="00700", sec_market=FUTU_TRD_SEC_MARKET_HK):
    return {
        "trd_side": FUTU_TRD_SIDE_BUY,
        "fill_id": fill_id,
        "order_id": order_id,
        "code": code,
        "qty": 100.0,
        "price": 300.0,
        "sec_market": sec_market,
        "create_timestamp": 1718000002.0,
        "status": 0,
    }


def _three_days_ago():
    return datetime.now(UTC) - timedelta(days=3)


class TestReconciliationReports:
    def test_fill_reports_today_only_without_start(self, h):
        h.rust.get_order_fill_list.return_value = [_fill_dict(1, 555)]
        cmd = GenerateFillReports(instrument_id=None, venue_order_id=None, start=None, end=None, command_id=UUID4(), ts_init=0)
        reports = h.run(h.client.generate_fill_reports(cmd))
        assert [r.trade_id.value for r in reports] == ["1"]  # same fill from both markets reported once
        assert h.rust.get_order_fill_list.call_count == 2  # HK and US queried
        assert not h.rust.get_history_order_fill_list.called

    def test_fill_reports_merge_history_for_lookback(self, h):
        h.client._trd_market_auth_list = [FUTU_TRD_MARKET_HK]
        h.rust.get_order_fill_list.return_value = [_fill_dict(2, 556)]
        h.rust.get_history_order_fill_list.return_value = [_fill_dict(1, 555), _fill_dict(2, 556)]
        cmd = GenerateFillReports(
            instrument_id=None, venue_order_id=None, start=_three_days_ago(), end=None, command_id=UUID4(), ts_init=0,
        )
        reports = h.run(h.client.generate_fill_reports(cmd))
        assert sorted(r.trade_id.value for r in reports) == ["1", "2"]  # deduplicated
        args = h.rust.get_history_order_fill_list.call_args.args
        assert args[0:3] == (0, ACC_ID, FUTU_TRD_MARKET_HK)
        assert len(args[3]) == len("YYYY-MM-DD HH:MM:SS")
        assert args[5] is None  # no code filter without an instrument

    def test_history_fill_failure_still_reports_today(self, h):
        h.client._trd_market_auth_list = [FUTU_TRD_MARKET_HK]
        h.rust.get_order_fill_list.return_value = [_fill_dict(2, 556)]
        h.rust.get_history_order_fill_list.side_effect = RuntimeError("not supported in simulate")
        cmd = GenerateFillReports(
            instrument_id=None, venue_order_id=None, start=_three_days_ago(), end=None, command_id=UUID4(), ts_init=0,
        )
        reports = h.run(h.client.generate_fill_reports(cmd))
        assert [r.trade_id.value for r in reports] == ["2"]

    def test_fill_reports_filter_by_instrument(self, h):
        h.rust.get_order_fill_list.return_value = [
            _fill_dict(1, 555),
            _fill_dict(2, 556, code="AAPL", sec_market=FUTU_TRD_SEC_MARKET_US),
        ]
        cmd = GenerateFillReports(
            instrument_id=HK_INSTRUMENT.id, venue_order_id=None, start=_three_days_ago(), end=None,
            command_id=UUID4(), ts_init=0,
        )
        reports = h.run(h.client.generate_fill_reports(cmd))
        assert [r.trade_id.value for r in reports] == ["1"]
        assert reports[0].instrument_id == HK_INSTRUMENT.id
        assert h.rust.get_history_order_fill_list.call_args.args[5] == ["00700"]

    def test_instrument_filter_tolerates_missing_sec_market(self, h):
        fill = _fill_dict(1, 555)
        fill["sec_market"] = None
        assert FutuLiveExecutionClient._matches_instrument(fill, HK_INSTRUMENT.id)
        assert not FutuLiveExecutionClient._matches_instrument(fill, US_INSTRUMENT.id)

    def test_order_reports_merge_history_today_wins(self, h):
        h.client._trd_market_auth_list = [FUTU_TRD_MARKET_HK]
        h.rust.get_order_list.return_value = [_order_dict(555, status=FUTU_ORDER_STATUS_SUBMITTED)]
        h.rust.get_history_order_list.return_value = [
            _order_dict(555, status=FUTU_ORDER_STATUS_CANCELLED_ALL),  # stale copy of today's order
            _order_dict(554),
        ]
        cmd = GenerateOrderStatusReports(
            instrument_id=None, start=_three_days_ago(), end=None, open_only=False, command_id=UUID4(), ts_init=0,
        )
        reports = h.run(h.client.generate_order_status_reports(cmd))
        by_id = {r.venue_order_id.value: r for r in reports}
        assert set(by_id) == {"554", "555"}
        assert by_id["555"].order_status == OrderStatus.ACCEPTED
        assert by_id["554"].order_status == OrderStatus.FILLED

    def test_open_only_never_queries_history(self, h):
        h.rust.get_order_list.return_value = [
            _order_dict(555, status=FUTU_ORDER_STATUS_SUBMITTED),
            _order_dict(554),
        ]
        cmd = GenerateOrderStatusReports(
            instrument_id=None, start=_three_days_ago(), end=None, open_only=True, command_id=UUID4(), ts_init=0,
        )
        reports = h.run(h.client.generate_order_status_reports(cmd))
        assert {r.venue_order_id.value for r in reports} == {"555"}
        assert not h.rust.get_history_order_list.called

    def test_order_reports_filter_by_instrument(self, h):
        h.rust.get_order_list.return_value = [
            _order_dict(555),
            _order_dict(556, code="AAPL", sec_market=FUTU_TRD_SEC_MARKET_US),
        ]
        cmd = GenerateOrderStatusReports(
            instrument_id=US_INSTRUMENT.id, start=None, end=None, open_only=False, command_id=UUID4(), ts_init=0,
        )
        reports = h.run(h.client.generate_order_status_reports(cmd))
        assert [r.venue_order_id.value for r in reports] == ["556"]

    def test_single_report_from_today(self, h):
        order = h.add_limit_order()
        h.accept(order)
        h.rust.get_order_list.return_value = [_order_dict(555, status=FUTU_ORDER_STATUS_SUBMITTED)]
        cmd = GenerateOrderStatusReport(
            instrument_id=order.instrument_id, client_order_id=order.client_order_id, venue_order_id=None,
            command_id=UUID4(), ts_init=0,
        )
        report = h.run(h.client.generate_order_status_report(cmd))
        assert report is not None
        assert report.venue_order_id == VenueOrderId("555")
        assert not h.rust.get_history_order_list.called  # found in today's list

    def test_single_report_falls_back_to_history_for_old_order(self, h):
        """A cached order created days ago that is not in today's list is looked up in the history."""
        created = datetime.now(UTC) - timedelta(days=5)
        order = LimitOrder(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            instrument_id=HK_INSTRUMENT.id,
            client_order_id=ClientOrderId("O-OLD"),
            order_side=OrderSide.BUY,
            quantity=Quantity.from_int(100),
            price=Price.from_str("300.000"),
            init_id=UUID4(),
            ts_init=int(created.timestamp() * 1_000_000_000),
        )
        h.cache.add_order(order)
        h.rust.get_order_list.return_value = []
        h.rust.get_history_order_list.return_value = [_order_dict(555, remark="O-OLD")]
        cmd = GenerateOrderStatusReport(
            instrument_id=HK_INSTRUMENT.id, client_order_id=ClientOrderId("O-OLD"), venue_order_id=None,
            command_id=UUID4(), ts_init=0,
        )
        report = h.run(h.client.generate_order_status_report(cmd))
        assert report is not None
        assert report.client_order_id == ClientOrderId("O-OLD")
        assert report.venue_order_id == VenueOrderId("555")
        args = h.rust.get_history_order_list.call_args.args
        assert args[4] == (created - timedelta(days=1)).astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M:%S")
        assert args[6] == ["00700"]

    def test_single_report_unknown_order_skips_history(self, h):
        h.rust.get_order_list.return_value = []
        cmd = GenerateOrderStatusReport(
            instrument_id=HK_INSTRUMENT.id, client_order_id=ClientOrderId("O-NONE"), venue_order_id=None,
            command_id=UUID4(), ts_init=0,
        )
        assert h.run(h.client.generate_order_status_report(cmd)) is None
        assert not h.rust.get_history_order_list.called


# ─────────────────────────────────────────────────────────
# Order lists
# ─────────────────────────────────────────────────────────


def _order_factory(h):
    return OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=h.clock)


def _submit_list(h, order_list):
    for order in order_list.orders:
        h.cache.add_order(order)
    cmd = SubmitOrderList(
        trader_id=TRADER_ID, strategy_id=STRATEGY_ID, order_list=order_list, command_id=UUID4(), ts_init=0,
    )
    h.run(h.client._submit_order_list(cmd))


class TestSubmitOrderList:
    def test_independent_orders_are_placed_one_by_one(self, h):
        factory = _order_factory(h)
        orders = [
            factory.limit(HK_INSTRUMENT.id, OrderSide.BUY, Quantity.from_int(100), Price.from_str("300.000")),
            factory.limit(HK_INSTRUMENT.id, OrderSide.BUY, Quantity.from_int(100), Price.from_str("299.000")),
        ]
        h.rust.place_order.side_effect = [{"order_id": 1}, {"order_id": 2}]
        _submit_list(h, factory.create_list(orders))
        assert h.rust.place_order.call_count == 2
        assert [c.args[7] for c in h.rust.place_order.call_args_list] == [300.0, 299.0]
        assert len(h.events_of(OrderSubmitted)) == 2
        assert not h.events_of(OrderRejected)
        assert h.cache.client_order_id(VenueOrderId("2")) == orders[1].client_order_id

    def test_bracket_is_rejected_without_placing_anything(self, h):
        factory = _order_factory(h)
        bracket = factory.bracket(
            instrument_id=HK_INSTRUMENT.id,
            order_side=OrderSide.BUY,
            quantity=Quantity.from_int(100),
            sl_trigger_price=Price.from_str("290.000"),
            tp_price=Price.from_str("320.000"),
        )
        _submit_list(h, bracket)
        assert not h.rust.place_order.called
        rejected = h.events_of(OrderRejected)
        assert len(rejected) == 3
        assert "emulation_trigger" in rejected[0].reason
        assert all(o.status == OrderStatus.REJECTED for o in bracket.orders)

    def test_oco_orders_are_placed(self, h):
        factory = _order_factory(h)
        tp_id, sl_id = ClientOrderId("O-TP"), ClientOrderId("O-SL")

        def leg(client_order_id, price, linked):
            return LimitOrder(
                trader_id=TRADER_ID,
                strategy_id=STRATEGY_ID,
                instrument_id=HK_INSTRUMENT.id,
                client_order_id=client_order_id,
                order_side=OrderSide.SELL,
                quantity=Quantity.from_int(100),
                price=Price.from_str(price),
                init_id=UUID4(),
                ts_init=0,
                contingency_type=ContingencyType.OCO,
                linked_order_ids=[linked],
            )

        orders = [leg(tp_id, "320.000", sl_id), leg(sl_id, "290.000", tp_id)]
        h.rust.place_order.side_effect = [{"order_id": 1}, {"order_id": 2}]
        _submit_list(h, factory.create_list(orders))
        assert h.rust.place_order.call_count == 2
        assert not h.events_of(OrderRejected)


# ─────────────────────────────────────────────────────────
# Review follow-ups: cancelled fills, fallback gating, placement races
# ─────────────────────────────────────────────────────────


class TestCancelledFillsInReports:
    def test_venue_cancelled_fills_are_not_reported(self, h):
        h.client._trd_market_auth_list = [FUTU_TRD_MARKET_HK]
        cancelled_today = dict(_fill_dict(3, 557), status=1)
        cancelled_history = dict(_fill_dict(1, 555), status=1)
        h.rust.get_order_fill_list.return_value = [cancelled_today, _fill_dict(2, 556)]
        h.rust.get_history_order_fill_list.return_value = [cancelled_history]
        cmd = GenerateFillReports(
            instrument_id=None, venue_order_id=None, start=_three_days_ago(), end=None, command_id=UUID4(), ts_init=0,
        )
        reports = h.run(h.client.generate_fill_reports(cmd))
        assert [r.trade_id.value for r in reports] == ["2"]


class TestSingleReportHistoryGating:
    def test_order_created_today_never_hits_history(self, h):
        today = LimitOrder(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            instrument_id=HK_INSTRUMENT.id,
            client_order_id=ClientOrderId("O-TODAY"),
            order_side=OrderSide.BUY,
            quantity=Quantity.from_int(100),
            price=Price.from_str("300.000"),
            init_id=UUID4(),
            ts_init=h.clock.timestamp_ns(),
        )
        h.cache.add_order(today)
        h.rust.get_order_list.return_value = []
        cmd = GenerateOrderStatusReport(
            instrument_id=HK_INSTRUMENT.id, client_order_id=today.client_order_id, venue_order_id=None,
            command_id=UUID4(), ts_init=0,
        )
        assert h.run(h.client.generate_order_status_report(cmd)) is None
        assert not h.rust.get_history_order_list.called
        assert h.rust.get_order_list.call_count == 1

    def test_old_order_fallback_does_not_refetch_today(self, h):
        created = datetime.now(UTC) - timedelta(days=5)
        old = LimitOrder(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            instrument_id=HK_INSTRUMENT.id,
            client_order_id=ClientOrderId("O-OLD2"),
            order_side=OrderSide.BUY,
            quantity=Quantity.from_int(100),
            price=Price.from_str("300.000"),
            init_id=UUID4(),
            ts_init=int(created.timestamp() * 1_000_000_000),
        )
        h.cache.add_order(old)
        h.rust.get_order_list.return_value = []
        h.rust.get_history_order_list.return_value = [_order_dict(555, remark="O-OLD2")]
        cmd = GenerateOrderStatusReport(
            instrument_id=HK_INSTRUMENT.id, client_order_id=old.client_order_id, venue_order_id=None,
            command_id=UUID4(), ts_init=0,
        )
        assert h.run(h.client.generate_order_status_report(cmd)) is not None
        assert h.rust.get_order_list.call_count == 1
        assert h.rust.get_history_order_list.call_count == 1


def _oco_pair(tp_price="320.000", sl_price="290.000", tp_kwargs=None):
    tp_id, sl_id = ClientOrderId("O-TP"), ClientOrderId("O-SL")

    def leg(client_order_id, price, linked, **kwargs):
        return LimitOrder(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            instrument_id=HK_INSTRUMENT.id,
            client_order_id=client_order_id,
            order_side=OrderSide.SELL,
            quantity=Quantity.from_int(100),
            price=Price.from_str(price),
            init_id=UUID4(),
            ts_init=0,
            contingency_type=ContingencyType.OCO,
            linked_order_ids=[linked],
            **kwargs,
        )

    return [leg(tp_id, tp_price, sl_id, **(tp_kwargs or {})), leg(sl_id, sl_price, tp_id)]


def _cancel_cmd(order):
    return CancelOrder(
        trader_id=TRADER_ID, strategy_id=STRATEGY_ID, instrument_id=order.instrument_id,
        client_order_id=order.client_order_id, venue_order_id=None, command_id=UUID4(), ts_init=0,
    )


class TestOrderListPlacementRaces:
    def test_all_legs_submitted_before_any_is_placed(self, h):
        tp, sl = _oco_pair()
        seen_status = []

        def place(*args):
            seen_status.append(sl.status)  # SL must already be SUBMITTED while TP is placed
            return {"order_id": 100 + len(seen_status)}

        h.rust.place_order.side_effect = place
        _submit_list(h, _order_factory(h).create_list([tp, sl]))
        assert seen_status[0] == OrderStatus.SUBMITTED
        assert h.rust.place_order.call_count == 2

    def test_failed_oco_leg_cancels_remaining_legs(self, h):
        tp, sl = _oco_pair()
        h.rust.place_order.side_effect = RuntimeError("Place order failed: insufficient position")
        _submit_list(h, _order_factory(h).create_list([tp, sl]))
        assert h.rust.place_order.call_count == 1  # SL never reaches OpenD
        assert tp.status == OrderStatus.REJECTED
        assert sl.status == OrderStatus.CANCELED

    def test_independent_list_keeps_placing_after_a_failure(self, h):
        factory = _order_factory(h)
        orders = [
            factory.limit(HK_INSTRUMENT.id, OrderSide.BUY, Quantity.from_int(100), Price.from_str("300.000")),
            factory.limit(HK_INSTRUMENT.id, OrderSide.BUY, Quantity.from_int(100), Price.from_str("299.000")),
        ]
        h.rust.place_order.side_effect = [RuntimeError("rejected"), {"order_id": 2}]
        _submit_list(h, factory.create_list(orders))
        assert h.rust.place_order.call_count == 2
        assert orders[0].status == OrderStatus.REJECTED
        assert orders[1].status == OrderStatus.SUBMITTED

    def test_invalid_leg_rejects_whole_list_before_placing(self, h):
        tp, sl = _oco_pair(tp_kwargs={"time_in_force": TimeInForce.IOC})
        _submit_list(h, _order_factory(h).create_list([tp, sl]))
        assert not h.rust.place_order.called
        assert tp.status == OrderStatus.REJECTED
        assert sl.status == OrderStatus.REJECTED

    def test_cancel_for_queued_leg_skips_placing_it(self, h):
        """The contingency manager cancels SL while TP is being placed (e.g. TP filled)."""
        tp, sl = _oco_pair()

        def place(*args):
            fut = asyncio.run_coroutine_threadsafe(h.client._cancel_order(_cancel_cmd(sl)), h.loop)
            fut.result(timeout=5)
            return {"order_id": 101}

        h.rust.place_order.side_effect = place
        _submit_list(h, _order_factory(h).create_list([tp, sl]))
        assert h.rust.place_order.call_count == 1
        assert not h.rust.modify_order.called
        assert sl.status == OrderStatus.CANCELED
        assert not h.events_of(OrderCancelRejected)

    def test_cancel_during_inflight_place_is_applied_after_placement(self, h):
        order = h.add_limit_order(submitted=False)

        def place(*args):
            fut = asyncio.run_coroutine_threadsafe(h.client._cancel_order(_cancel_cmd(order)), h.loop)
            fut.result(timeout=5)
            assert not h.rust.modify_order.called  # deferred, not rejected
            return {"order_id": 555}

        h.rust.place_order.side_effect = place
        cmd = SubmitOrder(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, order=order, command_id=UUID4(), ts_init=0)
        h.run(h.client._submit_order(cmd))
        args = h.rust.modify_order.call_args.args
        assert args[3] == 555
        assert args[4] == FUTU_MODIFY_ORDER_OP_CANCEL
        assert not h.events_of(OrderCancelRejected)
        assert not h.client._unplaced and not h.client._deferred_cancels

    def test_modify_during_inflight_place_is_applied_after_placement(self, h):
        order = h.add_limit_order(submitted=False)
        modify = ModifyOrder(
            trader_id=TRADER_ID, strategy_id=STRATEGY_ID, instrument_id=order.instrument_id,
            client_order_id=order.client_order_id, venue_order_id=None,
            quantity=None, price=Price.from_str("305.000"), trigger_price=None,
            command_id=UUID4(), ts_init=0,
        )

        def place(*args):
            asyncio.run_coroutine_threadsafe(h.client._modify_order(modify), h.loop).result(timeout=5)
            assert not h.rust.modify_order.called
            return {"order_id": 555}

        h.rust.place_order.side_effect = place
        cmd = SubmitOrder(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, order=order, command_id=UUID4(), ts_init=0)
        h.run(h.client._submit_order(cmd))
        args = h.rust.modify_order.call_args.args
        assert args[3] == 555
        assert args[4] == FUTU_MODIFY_ORDER_OP_NORMAL
        assert args[6] == 305.0
        assert not h.events_of(OrderModifyRejected)

    def test_cancel_before_accept_uses_indexed_venue_id(self, h):
        order = h.add_limit_order(submitted=False)
        cmd = SubmitOrder(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, order=order, command_id=UUID4(), ts_init=0)
        h.run(h.client._submit_order(cmd))
        assert order.status == OrderStatus.SUBMITTED and order.venue_order_id is None
        h.run(h.client._cancel_order(_cancel_cmd(order)))
        assert h.rust.modify_order.call_args.args[3] == 555
        assert not h.events_of(OrderCancelRejected)

    def test_cancel_of_closed_order_is_skipped(self, h):
        order = h.add_limit_order()
        h.accept(order)
        h.client._handle_push_order(h.order_push(status=FUTU_ORDER_STATUS_CANCELLED_ALL))
        assert order.status == OrderStatus.CANCELED
        h.run(h.client._cancel_order(_cancel_cmd(order)))
        assert not h.rust.modify_order.called
        assert not h.events_of(OrderCancelRejected)
