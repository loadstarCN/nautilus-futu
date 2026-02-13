"""Tests for Phase 4 infrastructure improvements."""

from __future__ import annotations

import pytest


class TestConnectionSharing:
    """Tests for shared PyFutuClient via factories."""

    def test_shared_client_same_host_port(self):
        """Same (host, port) should return the same client instance."""
        from nautilus_futu.factories import _get_shared_client, _shared_clients
        _shared_clients.clear()

        c1 = _get_shared_client("127.0.0.1", 11111)
        c2 = _get_shared_client("127.0.0.1", 11111)
        assert c1 is c2

    def test_shared_client_different_port(self):
        """Different ports should return different client instances."""
        from nautilus_futu.factories import _get_shared_client, _shared_clients
        _shared_clients.clear()

        c1 = _get_shared_client("127.0.0.1", 11111)
        c2 = _get_shared_client("127.0.0.1", 22222)
        assert c1 is not c2

    def test_shared_client_different_host(self):
        """Different hosts should return different client instances."""
        from nautilus_futu.factories import _get_shared_client, _shared_clients
        _shared_clients.clear()

        c1 = _get_shared_client("127.0.0.1", 11111)
        c2 = _get_shared_client("192.168.1.1", 11111)
        assert c1 is not c2

    def test_shared_clients_cache_populated(self):
        """Cache should be populated after calls."""
        from nautilus_futu.factories import _get_shared_client, _shared_clients
        _shared_clients.clear()

        _get_shared_client("10.0.0.1", 9999)
        assert ("10.0.0.1", 9999) in _shared_clients
        assert len(_shared_clients) == 1


class TestPyFutuClientIsConnected:
    """Tests for PyFutuClient.is_connected()."""

    def test_not_connected_initially(self):
        from nautilus_futu._rust import PyFutuClient

        client = PyFutuClient()
        assert client.is_connected() is False

    def test_is_connected_type(self):
        from nautilus_futu._rust import PyFutuClient

        client = PyFutuClient()
        result = client.is_connected()
        assert isinstance(result, bool)


class TestStartPushAppendMode:
    """Tests for start_push append mode."""

    def test_start_push_requires_connection(self):
        """start_push should raise when not connected."""
        from nautilus_futu._rust import PyFutuClient

        client = PyFutuClient()
        with pytest.raises(RuntimeError, match="Not connected"):
            client.start_push([3005])

    def test_poll_push_without_start_returns_none(self):
        """poll_push before start_push should return None."""
        from nautilus_futu._rust import PyFutuClient

        client = PyFutuClient()
        result = client.poll_push(10)
        assert result is None


class TestGetGlobalState:
    """Tests for get_global_state method."""

    def test_get_global_state_requires_connection(self):
        """get_global_state should raise when not connected."""
        from nautilus_futu._rust import PyFutuClient

        client = PyFutuClient()
        with pytest.raises(RuntimeError, match="Not connected"):
            client.get_global_state()


class TestRehabTypeConfig:
    """Tests for rehab_type configuration flow."""

    def test_rehab_type_default_is_forward_adjustment(self):
        """Default rehab_type should be 1 (forward adjustment)."""
        from nautilus_futu.config import FutuDataClientConfig

        config = FutuDataClientConfig()
        assert config.rehab_type == 1

    def test_rehab_type_backward_adjustment(self):
        """rehab_type=2 should be backward adjustment."""
        from nautilus_futu.config import FutuDataClientConfig

        config = FutuDataClientConfig(rehab_type=2)
        assert config.rehab_type == 2

    def test_rehab_type_none(self):
        """rehab_type=0 should be no adjustment."""
        from nautilus_futu.config import FutuDataClientConfig

        config = FutuDataClientConfig(rehab_type=0)
        assert config.rehab_type == 0


class TestReconnectConfig:
    """Tests for reconnect configuration."""

    def test_data_client_reconnect_defaults(self):
        from nautilus_futu.config import FutuDataClientConfig

        config = FutuDataClientConfig()
        assert config.reconnect is True
        assert config.reconnect_interval == 5.0

    def test_exec_client_reconnect_defaults(self):
        from nautilus_futu.config import FutuExecClientConfig

        config = FutuExecClientConfig()
        assert config.reconnect is True
        assert config.reconnect_interval == 5.0

    def test_data_client_reconnect_disabled(self):
        from nautilus_futu.config import FutuDataClientConfig

        config = FutuDataClientConfig(reconnect=False)
        assert config.reconnect is False

    def test_exec_client_reconnect_disabled(self):
        from nautilus_futu.config import FutuExecClientConfig

        config = FutuExecClientConfig(reconnect=False)
        assert config.reconnect is False

    def test_custom_reconnect_interval(self):
        from nautilus_futu.config import FutuDataClientConfig

        config = FutuDataClientConfig(reconnect_interval=15.0)
        assert config.reconnect_interval == 15.0
