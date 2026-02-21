"""Instrument provider for Futu OpenD."""

from __future__ import annotations

import asyncio
from typing import Any

from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_futu.common import futu_security_to_instrument_id
from nautilus_futu.parsing.instruments import parse_futu_instrument


class FutuInstrumentProvider(InstrumentProvider):
    """Provides instrument definitions from Futu OpenD.

    Parameters
    ----------
    client : Any
        The Futu Rust client instance.
    config : InstrumentProviderConfig | None
        The instrument provider configuration.
    """

    def __init__(self, client: Any, config: InstrumentProviderConfig | None = None) -> None:
        super().__init__(config=config)
        self._client = client

    async def load_all_async(self, filters: dict | None = None) -> None:
        """Load all instruments (not supported - use load_ids_async instead)."""
        pass

    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict | None = None,
    ) -> None:
        """Load instruments by their IDs."""
        for instrument_id in instrument_ids:
            await self.load_async(instrument_id, filters)

    async def load_async(
        self,
        instrument_id: InstrumentId,
        filters: dict | None = None,
    ) -> None:
        """Load a single instrument by ID."""
        from nautilus_futu.common import instrument_id_to_futu_security

        market, code = instrument_id_to_futu_security(instrument_id)

        try:
            static_info = await asyncio.to_thread(
                self._client.get_static_info, [(market, code)]
            )

            if static_info:
                for info in static_info:
                    instrument = parse_futu_instrument(info)
                    if instrument is not None:
                        self.add(instrument)
                    else:
                        self._log.warning(f"Failed to parse instrument for {instrument_id}")
        except Exception as e:
            self._log.error(f"Failed to load instrument {instrument_id}: {e}")
