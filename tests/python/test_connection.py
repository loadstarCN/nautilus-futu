"""Tests for the shared connection manager."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from nautilus_futu.connection import FutuConnectionManager


def _client(connected: bool = False) -> MagicMock:
    client = MagicMock()
    client.is_connected.return_value = connected
    client.connection_generation.return_value = 0

    def connect(*args, **kwargs):
        client.is_connected.return_value = True
        client.connection_generation.return_value += 1

    def disconnect():
        client.is_connected.return_value = False

    client.connect.side_effect = connect
    client.disconnect.side_effect = disconnect
    return client


def test_acquire_connects_once_and_release_disconnects_last():
    client = _client()
    mgr = FutuConnectionManager(client, "127.0.0.1", 11111, "id", 100, rsa_key_path=None, request_timeout=3.0)

    async def run():
        assert await mgr.acquire() is True  # data client
        assert await mgr.acquire() is False  # exec client reuses
        assert mgr.refcount == 2
        assert client.connect.call_count == 1
        kwargs = client.connect.call_args.kwargs
        assert kwargs["request_timeout_secs"] == 3
        assert "rsa_key_path" not in kwargs

        await mgr.release()
        assert client.disconnect.call_count == 0  # other consumer still active
        await mgr.release()
        assert client.disconnect.call_count == 1
        assert mgr.refcount == 0

    asyncio.run(run())


def test_ensure_connected_reconnects_only_when_down():
    client = _client(connected=True)
    mgr = FutuConnectionManager(client, "h", 1)

    async def run():
        assert await mgr.ensure_connected() is False
        client.is_connected.return_value = False
        assert await mgr.ensure_connected() is True
        assert mgr.generation == 1
        assert mgr.is_connected

    asyncio.run(run())


def test_rsa_key_path_forwarded():
    client = _client()
    mgr = FutuConnectionManager(client, "h", 1, rsa_key_path="/tmp/key.pem")
    asyncio.run(mgr.ensure_connected())
    assert client.connect.call_args.kwargs["rsa_key_path"] == "/tmp/key.pem"


def test_connect_falls_back_when_client_lacks_kwargs():
    client = _client()
    calls = []

    def connect(*args, **kwargs):
        calls.append(kwargs)
        if kwargs:
            raise TypeError("unexpected keyword")
        client.is_connected.return_value = True

    client.connect.side_effect = connect
    mgr = FutuConnectionManager(client, "h", 1)
    asyncio.run(mgr.ensure_connected())
    assert calls[-1] == {}
    assert mgr.is_connected
