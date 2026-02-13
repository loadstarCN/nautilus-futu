"""Tests for Futu adapter configuration."""

import pytest


class TestFutuDataClientConfig:
    """Tests for FutuDataClientConfig."""

    def test_default_config(self):
        from nautilus_futu.config import FutuDataClientConfig

        config = FutuDataClientConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 11111
        assert config.client_id == "nautilus_futu"
        assert config.client_ver == 100
        assert config.rsa_key_path is None

    def test_custom_config(self):
        from nautilus_futu.config import FutuDataClientConfig

        config = FutuDataClientConfig(
            host="192.168.1.100",
            port=22222,
            client_id="my_client",
            client_ver=200,
        )
        assert config.host == "192.168.1.100"
        assert config.port == 22222
        assert config.client_id == "my_client"
        assert config.client_ver == 200

    def test_default_rehab_type(self):
        from nautilus_futu.config import FutuDataClientConfig

        config = FutuDataClientConfig()
        assert config.rehab_type == 1

    def test_custom_rehab_type(self):
        from nautilus_futu.config import FutuDataClientConfig

        config = FutuDataClientConfig(rehab_type=2)
        assert config.rehab_type == 2

    def test_no_rehab(self):
        from nautilus_futu.config import FutuDataClientConfig

        config = FutuDataClientConfig(rehab_type=0)
        assert config.rehab_type == 0

    def test_default_reconnect(self):
        from nautilus_futu.config import FutuDataClientConfig

        config = FutuDataClientConfig()
        assert config.reconnect is True
        assert config.reconnect_interval == 5.0

    def test_custom_reconnect(self):
        from nautilus_futu.config import FutuDataClientConfig

        config = FutuDataClientConfig(reconnect=False, reconnect_interval=10.0)
        assert config.reconnect is False
        assert config.reconnect_interval == 10.0


class TestFutuExecClientConfig:
    """Tests for FutuExecClientConfig."""

    def test_default_config(self):
        from nautilus_futu.config import FutuExecClientConfig

        config = FutuExecClientConfig()
        assert config.trd_env == 0
        assert config.acc_id == 0
        assert config.trd_market == 1
        assert config.unlock_pwd_md5 == ""

    def test_real_trading_config(self):
        from nautilus_futu.config import FutuExecClientConfig

        config = FutuExecClientConfig(
            trd_env=1,
            acc_id=123456,
            trd_market=1,
            unlock_pwd_md5="abc123",
        )
        assert config.trd_env == 1
        assert config.acc_id == 123456
        assert config.unlock_pwd_md5 == "abc123"

    def test_default_reconnect(self):
        from nautilus_futu.config import FutuExecClientConfig

        config = FutuExecClientConfig()
        assert config.reconnect is True
        assert config.reconnect_interval == 5.0

    def test_custom_reconnect(self):
        from nautilus_futu.config import FutuExecClientConfig

        config = FutuExecClientConfig(reconnect=False, reconnect_interval=2.0)
        assert config.reconnect is False
        assert config.reconnect_interval == 2.0
