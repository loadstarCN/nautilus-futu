"""Configuration for Futu OpenD adapter."""

from __future__ import annotations

from nautilus_trader.config import (
    InstrumentProviderConfig,
    LiveDataClientConfig,
    LiveExecClientConfig,
    RoutingConfig,
)

from nautilus_futu.constants import FUTU_ROUTING_VENUES

# Route HKEX/NYSE/NASDAQ/SSE/SZSE/SGX instruments to the FUTU clients by default.
FUTU_DEFAULT_ROUTING = RoutingConfig(venues=FUTU_ROUTING_VENUES)


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
        Path to the RSA private key shared with OpenD.  When set, the
        handshake is RSA-encrypted and all traffic is AES-encrypted.
    request_timeout : float, default 15.0
        Seconds to wait for an OpenD response before a request fails.
    instrument_provider : InstrumentProviderConfig
        The instrument provider configuration.
    rehab_type : int, default 1
        Rehabilitation type for K-line data: 0=None, 1=Forward, 2=Backward.
    reconnect : bool, default True
        Whether to auto-reconnect on connection loss.
    reconnect_interval : float, default 5.0
        Seconds to wait between reconnection attempts.
    order_book_depth : int, default 10
        Maximum number of levels emitted per side for order book subscriptions
        (OpenD pushes up to 10 for HK/US, 5 for CN).
    routing : RoutingConfig
        Venue routing; defaults to all Futu venues so ``00700.HKEX`` etc.
        are routed to this client without extra configuration.
    handle_revised_bars : bool, default False
        When True, every K-line push for the *current* (unfinished) bar is
        forwarded with ``is_revision=True``.  When False only completed bars
        are emitted.
    """

    host: str = "127.0.0.1"
    port: int = 11111
    client_id: str = "nautilus_futu"
    client_ver: int = 100
    rsa_key_path: str | None = None
    request_timeout: float = 15.0
    instrument_provider: InstrumentProviderConfig = InstrumentProviderConfig()
    rehab_type: int = 1
    reconnect: bool = True
    reconnect_interval: float = 5.0
    order_book_depth: int = 10
    routing: RoutingConfig = FUTU_DEFAULT_ROUTING


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
        Path to the RSA private key shared with OpenD (see data config).
    request_timeout : float, default 15.0
        Seconds to wait for an OpenD response before a request fails.
    instrument_provider : InstrumentProviderConfig
        The instrument provider configuration.
    trd_env : int, default 0
        Trading environment: 0=Simulate, 1=Real.
    acc_id : int, default 0
        Trading account ID. 0 means auto-detect.
    trd_market : int, default 1
        Default trading market: 1=HK, 2=US, 3=CN, 4=HKCC, 5=Futures.  Orders
        for other authorized markets are routed by the instrument's venue.
    unlock_pwd_md5 : str, default ""
        MD5 hash of trading unlock password (required for real trading).
    security_firm : int, default 1
        Futu security firm for unlock: 1=FutuSecurities (HK), 2=FutuInc (US),
        3=FutuSG, 4=FutuAU.
    account_type : str, default "CASH"
        "CASH" or "MARGIN".  Must match the Futu account type (a warning is
        logged on mismatch).  Margin accounts also publish margin balances.
    fill_outside_rth : bool, default False
        Default for US limit orders: allow fills in pre/after market.  Can be
        overridden per order with the tag ``FUTU_RTH:1`` / ``FUTU_RTH:0``.
    set_specific_venue : bool, default True
        Register the FUTU account as the account for every venue in the
        cache, so ``Portfolio`` can resolve balances for ``HKEX``/``NYSE``
        instruments.  Disable when running other adapters in the same node.
    account_refresh_interval : float, default 0.0
        Seconds between periodic account balance refreshes (0 disables).
        Balances are always refreshed after order/fill pushes.
    reconnect : bool, default True
        Whether to auto-reconnect on connection loss.
    reconnect_interval : float, default 5.0
        Seconds to wait between reconnection attempts.
    routing : RoutingConfig
        Venue routing; defaults to all Futu venues.
    """

    host: str = "127.0.0.1"
    port: int = 11111
    client_id: str = "nautilus_futu"
    client_ver: int = 100
    rsa_key_path: str | None = None
    request_timeout: float = 15.0
    instrument_provider: InstrumentProviderConfig = InstrumentProviderConfig()
    trd_env: int = 0
    acc_id: int = 0
    trd_market: int = 1
    unlock_pwd_md5: str = ""
    security_firm: int = 1
    account_type: str = "CASH"
    fill_outside_rth: bool = False
    set_specific_venue: bool = True
    account_refresh_interval: float = 0.0
    reconnect: bool = True
    reconnect_interval: float = 5.0
    routing: RoutingConfig = FUTU_DEFAULT_ROUTING
