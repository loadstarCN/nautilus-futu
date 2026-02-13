"""Factory classes for Futu OpenD adapter."""

from __future__ import annotations

import asyncio
from typing import Any

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.clock import LiveClock
from nautilus_trader.common.logging import Logger
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
        cache: Cache,
        clock: LiveClock,
        logger: Logger,
    ) -> FutuLiveDataClient:
        """Create a new Futu live data client."""
        try:
            from nautilus_futu._rust import FutuClient
            client = FutuClient()
        except ImportError:
            raise ImportError(
                "Failed to import nautilus_futu._rust. "
                "Make sure the Rust extension is built with 'maturin develop'."
            )

        provider = FutuInstrumentProvider(client=client, config=config)

        return FutuLiveDataClient(
            loop=loop,
            client=client,
            cache=cache,
            clock=clock,
            logger=logger,
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
        cache: Cache,
        clock: LiveClock,
        logger: Logger,
    ) -> FutuLiveExecutionClient:
        """Create a new Futu live execution client."""
        try:
            from nautilus_futu._rust import FutuClient
            client = FutuClient()
        except ImportError:
            raise ImportError(
                "Failed to import nautilus_futu._rust. "
                "Make sure the Rust extension is built with 'maturin develop'."
            )

        return FutuLiveExecutionClient(
            loop=loop,
            client=client,
            cache=cache,
            clock=clock,
            logger=logger,
            config=config,
        )
