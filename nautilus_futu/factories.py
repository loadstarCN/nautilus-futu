"""Factory classes for Futu OpenD adapter."""

from __future__ import annotations

import asyncio
from typing import Any

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.live.factories import LiveDataClientFactory, LiveExecClientFactory

from nautilus_futu.config import FutuDataClientConfig, FutuExecClientConfig
from nautilus_futu.data import FutuLiveDataClient
from nautilus_futu.execution import FutuLiveExecutionClient
from nautilus_futu.providers import FutuInstrumentProvider

# Module-level cache for shared PyFutuClient instances, keyed by (host, port).
# Data + Exec clients connecting to the same OpenD share one TCP connection.
_shared_clients: dict[tuple[str, int], Any] = {}


def _get_shared_client(host: str, port: int) -> Any:
    """Get or create a shared PyFutuClient for the given host:port."""
    key = (host, port)
    if key not in _shared_clients:
        from nautilus_futu._rust import PyFutuClient
        _shared_clients[key] = PyFutuClient()
    return _shared_clients[key]


class FutuLiveDataClientFactory(LiveDataClientFactory):
    """Factory for creating Futu live data clients."""

    @staticmethod
    def create(
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: FutuDataClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> FutuLiveDataClient:
        """Create a new Futu live data client."""
        try:
            client = _get_shared_client(config.host, config.port)
        except ImportError:
            raise ImportError(
                "Failed to import nautilus_futu._rust. "
                "Make sure the Rust extension is built with 'maturin develop'."
            )

        provider = FutuInstrumentProvider(
            client=client,
            config=config.instrument_provider,
        )

        return FutuLiveDataClient(
            loop=loop,
            client=client,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=provider,
            config=config,
        )


class FutuLiveExecClientFactory(LiveExecClientFactory):
    """Factory for creating Futu live execution clients."""

    @staticmethod
    def create(
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: FutuExecClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> FutuLiveExecutionClient:
        """Create a new Futu live execution client."""
        try:
            client = _get_shared_client(config.host, config.port)
        except ImportError:
            raise ImportError(
                "Failed to import nautilus_futu._rust. "
                "Make sure the Rust extension is built with 'maturin develop'."
            )

        provider = FutuInstrumentProvider(
            client=client,
            config=config.instrument_provider,
        )

        return FutuLiveExecutionClient(
            loop=loop,
            client=client,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=provider,
            config=config,
        )
