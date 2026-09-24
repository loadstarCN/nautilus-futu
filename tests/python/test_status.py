"""Tests for instrument status (market state) mapping and polling."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
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
    follows_futures_session,
    market_state_field,
    parse_futu_instrument_status,
)
from nautilus_futu.providers import FutuInstrumentProvider

HK = parse_futu_instrument({"market": 1, "code": "00700", "lot_size": 100, "sec_type": 3})
HK_FUT = parse_futu_instrument(
    {"market": 1, "code": "HSImain", "lot_size": 50, "sec_type": 10, "last_trade_timestamp": 1790000000.0},
)
US = parse_futu_instrument({"market": 11, "code": "AAPL", "lot_size": 1, "sec_type": 3})
EXPIRY_TS = 1_900_000_000.0  # 2030-03-17
STOCK_OPT = parse_futu_instrument({
    "market": 1, "code": "TCH300328C400000", "sec_type": 8, "lot_size": 100, "option_type": 1,
    "strike_price": 400.0, "strike_timestamp": EXPIRY_TS, "option_owner_code": "00700",
})
INDEX_OPT = parse_futu_instrument({
    "market": 1, "code": "HSI300328C20000", "sec_type": 8, "lot_size": 50, "option_type": 1,
    "strike_price": 20000.0, "strike_timestamp": EXPIRY_TS, "option_owner_code": "800000",
})
PROTO = Path(__file__).resolve().parents[2] / "crates" / "futu" / "proto" / "Qot_Common.proto"

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
        enum = re.search(r"enum QotMarketState\s*\{(.*?)\}", PROTO.read_text(encoding="utf-8"), re.S).group(1)
        proto_states = {int(v) for v in re.findall(r"QotMarketState_\w+\s*=\s*(\d+)", enum)}
        assert 37 in proto_states
        assert set(FUTU_MARKET_STATES) == proto_states

    def test_us_overnight_is_post_close(self):
        assert parse_futu_instrument_status(US.id, 37, 0, 0).action == MarketStatusAction.POST_CLOSE

    def test_option_daily_close_is_not_expiry(self):
        """NautilusTrader expires option-chain instruments on CLOSE; a daily close must not look like that."""
        before_expiry = int(EXPIRY_TS * 1e9) - 1
        status = parse_futu_instrument_status(STOCK_OPT.id, CLOSED, 0, before_expiry, instrument=STOCK_OPT)
        assert status.action == MarketStatusAction.POST_CLOSE
        assert status.trading_event == "CLOSED"
        expired = parse_futu_instrument_status(STOCK_OPT.id, CLOSED, 0, int(EXPIRY_TS * 1e9), instrument=STOCK_OPT)
        assert expired.action == MarketStatusAction.CLOSE
        # other instruments keep CLOSE
        assert parse_futu_instrument_status(HK.id, CLOSED, 0, 0, instrument=HK).action == MarketStatusAction.CLOSE

    def test_hkfe_derivatives_follow_futures_sessions(self):
        assert follows_futures_session(HK_FUT)
        assert follows_futures_session(INDEX_OPT)
        assert not follows_futures_session(STOCK_OPT)
        assert not follows_futures_session(HK)
        assert not follows_futures_session(None)

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
        for instrument_id in list(self.client._subscribed_status):
            self.run(self.client._unsubscribe_instrument_status(instrument_id))
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

    def test_index_option_reads_futures_state(self, h):
        h.cache.add_instrument(INDEX_OPT)
        h.run(h.client._subscribe_instrument_status(INDEX_OPT.id))
        h.settle()
        assert h.data[0].trading_event == "FUTURE_DAY_OPEN"

    def test_option_status_never_closes_chain_before_expiry(self, h):
        h.cache.add_instrument(STOCK_OPT)
        h.state["market_hk"] = CLOSED
        h.run(h.client._subscribe_instrument_status(STOCK_OPT.id))
        h.settle()
        assert h.data[0].action == MarketStatusAction.POST_CLOSE

    def test_field_resolved_when_instrument_loaded_later(self, h):
        late_future = InstrumentId.from_str("MHImain.HKEX")
        h.run(h.client._subscribe_instrument_status(late_future))
        h.settle()
        assert h.data[-1].trading_event == "MORNING"  # not cached yet: securities market
        h.cache.add_instrument(parse_futu_instrument(
            {"market": 1, "code": "MHImain", "lot_size": 10, "sec_type": 10, "last_trade_timestamp": 1790000000.0},
        ))
        h.settle()
        assert h.data[-1].instrument_id == late_future
        assert h.data[-1].trading_event == "FUTURE_DAY_OPEN"

    def test_uncached_future_is_loaded_on_subscribe(self, h):
        hhi = InstrumentId.from_str("HHImain.HKEX")
        h.rust.get_static_info.return_value = [
            {"market": 1, "code": "HHImain", "lot_size": 50, "sec_type": 10, "last_trade_timestamp": 1790000000.0},
        ]
        h.run(h.client._subscribe_instrument_status(hhi))
        h.settle()
        h.rust.get_static_info.assert_called_once_with([(1, "HHImain")])
        published = [d for d in h.data if not isinstance(d, InstrumentStatus)]
        assert [i.id for i in published] == [hhi]  # published so the DataEngine caches it
        statuses = [d for d in h.data if isinstance(d, InstrumentStatus)]
        assert statuses[0].trading_event == "FUTURE_DAY_OPEN"

    def test_unknown_venue_rejected(self, h):
        h.run(h.client._subscribe_instrument_status(InstrumentId.from_str("X.XNAS")))
        assert h.client._status_task is None
        assert h.data == []
