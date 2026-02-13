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
            from nautilus_futu._rust import PyFutuClient
            client = PyFutuClient()
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
            from nautilus_futu._rust import PyFutuClient
            client = PyFutuClient()
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
