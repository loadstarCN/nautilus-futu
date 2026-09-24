"""Tests for instrument status (market state) mapping and polling."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.model.data import InstrumentStatus
from nautilus_trader.model.enums import MarketStatusAction
from nautilus_trader.model.identifiers import InstrumentId, TraderId

from nautilus_futu.config import FutuDataClientConfig
from nautilus_futu.data import FutuLiveDataClient
from nautilus_futu.parsing.instruments import parse_futu_instrument
from nautilus_futu.parsing.status import (
    FUTU_MARKET_STATES,
    market_state_field,
    parse_futu_instrument_status,
)
from nautilus_futu.providers import FutuInstrumentProvider

HK = parse_futu_instrument({"market": 1, "code": "00700", "lot_size": 100, "sec_type": 3})
HK_FUT = parse_futu_instrument(
    {"market": 1, "code": "HSImain", "lot_size": 50, "sec_type": 10, "last_trade_timestamp": 1790000000.0},
)
US = parse_futu_instrument({"market": 11, "code": "AAPL", "lot_size": 1, "sec_type": 3})

# QotMarketState values
MORNING, REST, AFTERNOON, CLOSED, HK_CAS, PRE_MARKET = 3, 4, 5, 6, 19, 8


class TestMarketStateMapping:
    @pytest.mark.parametrize(
        ("state", "action", "name"),
        [
            (1, MarketStatusAction.PRE_OPEN, "AUCTION"),
            (MORNING, MarketStatusAction.TRADING, "MORNING"),
            (REST, MarketStatusAction.PAUSE, "REST"),
            (AFTERNOON, MarketStatusAction.TRADING, "AFTERNOON"),
            (HK_CAS, MarketStatusAction.PRE_CLOSE, "HK_CAS"),
            (CLOSED, MarketStatusAction.CLOSE, "CLOSED"),
            (PRE_MARKET, MarketStatusAction.PRE_OPEN, "PRE_MARKET_BEGIN"),
            (10, MarketStatusAction.POST_CLOSE, "AFTER_HOURS_BEGIN"),
            (24, MarketStatusAction.PAUSE, "FUTURE_BREAK"),
        ],
    )
    def test_known_states(self, state, action, name):
        status = parse_futu_instrument_status(HK.id, state, 1, 2)
        assert isinstance(status, InstrumentStatus)
        assert status.action == action
        assert status.trading_event == name
        assert status.ts_event == 1
        assert status.ts_init == 2

    def test_unknown_state(self):
        status = parse_futu_instrument_status(HK.id, 99, 0, 0)
        assert status.action == MarketStatusAction.NONE
        assert status.trading_event == "UNKNOWN_99"

    def test_every_proto_state_is_mapped(self):
        # Qot_Common.QotMarketState: 0-6, 8-36 (7 is unused)
        assert set(FUTU_MARKET_STATES) == set(range(0, 7)) | set(range(8, 37))

    def test_state_fields(self):
        assert market_state_field(HK.id) == "market_hk"
        assert market_state_field(HK_FUT.id, is_future=True) == "market_hk_future"
        assert market_state_field(US.id) == "market_us"
        assert market_state_field(InstrumentId.from_str("AAPL.NASDAQ")) == "market_us"
        assert market_state_field(InstrumentId.from_str("600519.SSE")) == "market_sh"
        assert market_state_field(InstrumentId.from_str("000001.SZSE")) == "market_sz"
        assert market_state_field(InstrumentId.from_str("CNmain.SGX")) == "market_sg_future"
        assert market_state_field(InstrumentId.from_str("X.XNAS")) is None


class Harness:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.clock = LiveClock()
        self.msgbus = MessageBus(trader_id=TraderId("T-1"), clock=self.clock)
        self.cache = Cache()
        for inst in (HK, HK_FUT, US):
            self.cache.add_instrument(inst)
        self.rust = MagicMock()
        self.state = {"market_hk": MORNING, "market_hk_future": 15, "market_us": CLOSED, "time": 1718400000}
        self.rust.get_global_state.side_effect = lambda: dict(self.state)
        self.data: list = []
        self.client = FutuLiveDataClient(
            loop=self.loop,
            client=self.rust,
            msgbus=self.msgbus,
            cache=self.cache,
            clock=self.clock,
            instrument_provider=FutuInstrumentProvider(self.rust),
            config=FutuDataClientConfig(market_status_interval=0.01),
        )
        self.client._handle_data = self.data.append

    def run(self, coro):
        return self.loop.run_until_complete(coro)

    def settle(self, secs=0.05):
        self.run(asyncio.sleep(secs))

    def close(self):
        self.run(self.client._unsubscribe_instrument_status(HK.id))
        self.run(self.client._unsubscribe_instrument_status(HK_FUT.id))
        self.run(self.client._unsubscribe_instrument_status(US.id))
        self.settle(0.02)
        self.loop.close()


@pytest.fixture
def h():
    harness = Harness()
    yield harness
    harness.close()


class TestInstrumentStatusSubscription:
    def test_initial_status_emitted_then_only_changes(self, h):
        h.run(h.client._subscribe_instrument_status(HK.id))
        h.settle()
        assert [(s.instrument_id, s.action) for s in h.data] == [(HK.id, MarketStatusAction.TRADING)]
        assert h.data[0].ts_event == 1718400000 * 1_000_000_000

        h.state["market_hk"] = REST  # lunch break
        h.settle()
        assert [s.action for s in h.data] == [MarketStatusAction.TRADING, MarketStatusAction.PAUSE]

    def test_futures_use_futures_market_state(self, h):
        h.run(h.client._subscribe_instrument_status(HK_FUT.id))
        h.settle()
        assert h.data[0].instrument_id == HK_FUT.id
        assert h.data[0].trading_event == "FUTURE_DAY_OPEN"

    def test_second_subscription_gets_immediate_status(self, h):
        h.run(h.client._subscribe_instrument_status(HK.id))
        h.settle()
        captured: list = []
        h.client._handle_data = captured.append
        h.run(h.client._subscribe_instrument_status(US.id))
        assert [(s.instrument_id, s.action) for s in captured] == [(US.id, MarketStatusAction.CLOSE)]

    def test_unsubscribe_last_stops_polling(self, h):
        h.run(h.client._subscribe_instrument_status(HK.id))
        h.settle()
        assert h.client._status_task is not None
        h.run(h.client._unsubscribe_instrument_status(HK.id))
        h.settle()
        assert h.client._status_task is None
        calls = h.rust.get_global_state.call_count
        h.settle()
        assert h.rust.get_global_state.call_count == calls

    def test_resubscribe_after_unsubscribe_keeps_new_task(self, h):
        h.run(h.client._subscribe_instrument_status(HK.id))
        h.run(h.client._unsubscribe_instrument_status(HK.id))
        h.run(h.client._subscribe_instrument_status(HK.id))
        h.settle()
        assert h.client._status_task is not None
        assert not h.client._status_task.done()

    def test_poll_errors_do_not_stop_the_loop(self, h):
        h.rust.get_global_state.side_effect = [RuntimeError("timeout"), dict(h.state), dict(h.state)]
        h.run(h.client._subscribe_instrument_status(HK.id))
        h.settle()
        assert [s.action for s in h.data] == [MarketStatusAction.TRADING]

    def test_unknown_venue_rejected(self, h):
        h.run(h.client._subscribe_instrument_status(InstrumentId.from_str("X.XNAS")))
        assert h.client._status_task is None
        assert h.data == []
