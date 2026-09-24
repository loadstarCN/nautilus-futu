"""End-to-end tests of the Rust client against an in-process fake OpenD.

These cover the connection lifecycle the unit tests cannot: handshake,
request/response over TCP, push delivery, disconnect detection, reconnect
with push channels kept alive, and request timeouts.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from tests.python.fake_opend import FakeOpenD, basic_qot_push

pytest.importorskip("nautilus_futu._rust", reason="Rust extension not built (run `maturin develop`)")

from nautilus_futu._rust import PyFutuClient  # noqa: E402


@pytest.fixture
def server():
    srv = FakeOpenD().start()
    yield srv
    srv.stop()


def _connect(client: PyFutuClient, server: FakeOpenD, timeout: int = 2) -> None:
    client.connect("127.0.0.1", server.port, "e2e", 100, request_timeout_secs=timeout)


def _wait(predicate, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class TestConnectionLifecycle:
    def test_handshake_request_and_push(self, server):
        client = PyFutuClient()
        _connect(client, server)
        assert client.is_connected()
        assert not client.is_encrypted()
        assert client.connection_generation() == 1

        channel = client.start_push([3005])
        client.subscribe([(1, "00700")], [1], True)  # answered by the fake server
        assert any(p == 3001 for p, _ in server.received)

        server.push(3005, basic_qot_push(cur_price=345.6))
        msg = client.poll_push(channel, 2000)
        assert msg is not None
        assert msg["proto_id"] == 3005
        assert msg["data"][0]["code"] == "00700"
        assert msg["data"][0]["cur_price"] == 345.6

        assert client.poll_push(channel, 50) is None  # timeout -> None, no exception
        client.disconnect()
        assert not client.is_connected()

    def test_peer_close_is_detected_and_channel_survives_reconnect(self, server):
        client = PyFutuClient()
        _connect(client, server)
        channel = client.start_push([3005])

        server.drop_connections()
        with pytest.raises(ConnectionError):
            client.poll_push(channel, 2000)
        assert not client.is_connected()
        with pytest.raises(RuntimeError, match="(?i)disconnected|not connected|timed out"):
            client.subscribe([(1, "00700")], [1], True)

        # Reconnect: same channel id keeps receiving pushes
        _connect(client, server)
        assert client.is_connected()
        assert client.connection_generation() == 2
        assert _wait(lambda: server.connection_count == 1)
        server.push(3005, basic_qot_push(cur_price=1.5))
        msg = client.poll_push(channel, 2000)
        assert msg["data"][0]["cur_price"] == 1.5
        client.disconnect()

    def test_connect_is_idempotent_while_alive(self, server):
        client = PyFutuClient()
        _connect(client, server)
        _connect(client, server)
        assert client.connection_generation() == 1
        client.disconnect()

    def test_request_timeout_does_not_hang(self):
        srv = FakeOpenD(ignore_protos={3001}).start()
        try:
            client = PyFutuClient()
            _connect(client, srv, timeout=1)
            started = time.time()
            with pytest.raises(RuntimeError, match="timed out"):
                client.subscribe([(1, "00700")], [1], True)
            assert time.time() - started < 5
            assert client.is_connected()  # a slow reply is not a dead link
            client.disconnect()
        finally:
            srv.stop()

    def test_poll_push_async(self, server):
        client = PyFutuClient()
        _connect(client, server)
        channel = client.start_push([3005])

        async def run():
            waiter = asyncio.ensure_future(client.poll_push_async(channel))
            await asyncio.sleep(0.1)
            await asyncio.to_thread(server.push, 3005, basic_qot_push(cur_price=9.9))
            msg = await asyncio.wait_for(waiter, 3)
            assert msg["data"][0]["cur_price"] == 9.9

            waiter = asyncio.ensure_future(client.poll_push_async(channel))
            await asyncio.sleep(0.1)
            await asyncio.to_thread(server.drop_connections)
            with pytest.raises(ConnectionError):
                await asyncio.wait_for(waiter, 3)

        asyncio.run(run())
        client.disconnect()


class TestPlaceOrderErrorClassification:
    """``place_order`` errors from the real client must tell "not sent" from "maybe sent"."""

    def test_request_on_dead_link_is_definitive(self, server):
        from nautilus_futu.execution import is_ambiguous_order_error

        client = PyFutuClient()
        _connect(client, server)
        server.drop_connections()
        assert _wait(lambda: not client.is_connected())
        with pytest.raises(Exception) as excinfo:
            client.place_order(0, 1, 1, 1, 1, "00700", 100.0, 300.0)
        assert "not connected" in str(excinfo.value).lower()
        assert not is_ambiguous_order_error(excinfo.value)
        assert not any(p == 2202 for p, _ in server.received)

    def test_timed_out_request_is_ambiguous(self):
        from nautilus_futu.execution import is_ambiguous_order_error

        srv = FakeOpenD(ignore_protos={2202}).start()
        try:
            client = PyFutuClient()
            _connect(client, srv, timeout=1)
            with pytest.raises(Exception) as excinfo:
                client.place_order(0, 1, 1, 1, 1, "00700", 100.0, 300.0)
            assert "timed out" in str(excinfo.value)
            assert is_ambiguous_order_error(excinfo.value)
            assert any(p == 2202 for p, _ in srv.received)  # the request did reach OpenD
            client.disconnect()
        finally:
            srv.stop()
