"""Configuration for Futu OpenD adapter."""

from __future__ import annotations

from nautilus_trader.config import LiveDataClientConfig, LiveExecClientConfig


class FutuDataClientConfig(LiveDataClientConfig, frozen=True):
    """Configuration for Futu live data client.

    Parameters
    ----------
    host : str, default "127.0.0.1"
        The Futu OpenD gateway host.
    port : int, default 11111
        The Futu OpenD gateway port.
    client_id : str, default "nautilus_futu"
        Client identifier for the connection.
    client_ver : int, default 100
        Client version number.
    rsa_key_path : str | None, default None
        Path to RSA private key for encrypted connections.
    """

    host: str = "127.0.0.1"
    port: int = 11111
    client_id: str = "nautilus_futu"
    client_ver: int = 100
    rsa_key_path: str | None = None


class FutuExecClientConfig(LiveExecClientConfig, frozen=True):
    """Configuration for Futu live execution client.

    Parameters
    ----------
    host : str, default "127.0.0.1"
        The Futu OpenD gateway host.
    port : int, default 11111
        The Futu OpenD gateway port.
    client_id : str, default "nautilus_futu"
        Client identifier for the connection.
    client_ver : int, default 100
        Client version number.
    rsa_key_path : str | None, default None
        Path to RSA private key for encrypted connections.
    trd_env : int, default 0
        Trading environment: 0=Simulate, 1=Real.
    acc_id : int, default 0
        Trading account ID. 0 means auto-detect.
    trd_market : int, default 1
        Trading market: 1=HK, 2=US, 3=CN, etc.
    unlock_pwd_md5 : str, default ""
        MD5 hash of trading unlock password (required for real trading).
    """

    host: str = "127.0.0.1"
    port: int = 11111
    client_id: str = "nautilus_futu"
    client_ver: int = 100
    rsa_key_path: str | None = None
    trd_env: int = 0
    acc_id: int = 0
    trd_market: int = 1
    unlock_pwd_md5: str = ""
