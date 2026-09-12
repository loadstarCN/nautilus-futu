"""Factory classes for Futu OpenD adapter."""

from __future__ import annotations

import asyncio
from typing import Any

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.live.factories import LiveDataClientFactory, LiveExecClientFactory

from nautilus_futu.config import FutuDataClientConfig, FutuExecClientConfig
from nautilus_futu.connection import FutuConnectionManager
from nautilus_futu.data import FutuLiveDataClient
from nautilus_futu.execution import FutuLiveExecutionClient
from nautilus_futu.providers import FutuInstrumentProvider

# Module-level cache for shared PyFutuClient instances, keyed by (host, port).
# Data + Exec clients connecting to the same OpenD share one TCP connection.
_shared_clients: dict[tuple[str, int], Any] = {}

# Module-level connection managers (one per shared client).
_shared_managers: dict[tuple[str, int], FutuConnectionManager] = {}

# Kept for backwards compatibility with callers that used the raw lock.
_shared_locks: dict[tuple[str, int], asyncio.Lock] = {}


def _get_shared_client(host: str, port: int) -> Any:
    """Get or create a shared PyFutuClient for the given host:port."""
    key = (host, port)
    if key not in _shared_clients:
        from nautilus_futu._rust import PyFutuClient

        _shared_clients[key] = PyFutuClient()
    return _shared_clients[key]


def _get_shared_lock(host: str, port: int) -> asyncio.Lock:
    """Get or create a shared asyncio.Lock for the given host:port."""
    key = (host, port)
    if key not in _shared_locks:
        _shared_locks[key] = asyncio.Lock()
    return _shared_locks[key]


def _get_shared_manager(config: FutuDataClientConfig | FutuExecClientConfig) -> FutuConnectionManager:
    """Get or create the connection manager for the config's host:port."""
    key = (config.host, config.port)
    manager = _shared_managers.get(key)
    if manager is None:
        try:
            client = _get_shared_client(config.host, config.port)
        except ImportError:
            raise ImportError(
                "Failed to import nautilus_futu._rust. "
                "Make sure the Rust extension is built with 'maturin develop'."
            )
        manager = FutuConnectionManager(
            client=client,
            host=config.host,
            port=config.port,
            client_id=config.client_id,
            client_ver=config.client_ver,
            rsa_key_path=config.rsa_key_path,
            request_timeout=config.request_timeout,
        )
        _shared_managers[key] = manager
    return manager


class FutuLiveDataClientFactory(LiveDataClientFactory):
    """Factory for creating Futu live data clients."""

    @staticmethod
    def create(  # type: ignore[override]
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: FutuDataClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> FutuLiveDataClient:
        """Create a new Futu live data client."""
        manager = _get_shared_manager(config)

        provider = FutuInstrumentProvider(
            client=manager.client,
            config=config.instrument_provider,
        )

        return FutuLiveDataClient(
            loop=loop,
            client=manager.client,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=provider,
            config=config,
            connection=manager,
        )


class FutuLiveExecClientFactory(LiveExecClientFactory):
    """Factory for creating Futu live execution clients."""

    @staticmethod
    def create(  # type: ignore[override]
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: FutuExecClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> FutuLiveExecutionClient:
        """Create a new Futu live execution client."""
        manager = _get_shared_manager(config)

        provider = FutuInstrumentProvider(
            client=manager.client,
            config=config.instrument_provider,
        )

        return FutuLiveExecutionClient(
            loop=loop,
            client=manager.client,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=provider,
            config=config,
            connection=manager,
        )
