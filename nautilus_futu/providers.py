"""Instrument provider for Futu OpenD."""

from __future__ import annotations

import asyncio
from typing import Any

from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.instruments import Instrument

from nautilus_futu.common import instrument_id_to_futu_security
from nautilus_futu.constants import VENUE_TO_FUTU_MARKET
from nautilus_futu.parsing.instruments import parse_futu_instrument, parse_option_chain

# OpenD accepts at most this many securities per Qot_GetStaticInfo request.
STATIC_INFO_BATCH_SIZE = 100
# Page size for Qot_StockFilter when enumerating a whole market.
STOCK_FILTER_PAGE_SIZE = 200


class FutuInstrumentProvider(InstrumentProvider):
    """Provides instrument definitions from Futu OpenD.

    ``load_all_async`` needs ``filters`` to know what to enumerate, e.g.::

        InstrumentProviderConfig(load_all=True, filters={"venues": ["HKEX"]})
        InstrumentProviderConfig(load_all=True, filters={"markets": [1, 11]})
        InstrumentProviderConfig(load_all=True, filters={"plates": [(1, "HK.BK1001")]})
        InstrumentProviderConfig(load_all=True, filters={
            "option_chains": [{"instrument_id": "00700.HKEX", "begin": "2026-10-01", "end": "2026-12-31"}]
        })

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

    # ------------------------------------------------------------------
    # InstrumentProvider API
    # ------------------------------------------------------------------

    async def load_all_async(self, filters: dict | None = None) -> None:
        """Load instruments described by ``filters`` (see class docstring)."""
        filters = dict(filters or {})
        if not filters:
            self._log.warning(
                "load_all requires filters (venues/markets/plates/option_chains); nothing loaded",
            )
            return

        markets: list[int] = list(filters.get("markets") or [])
        for venue in filters.get("venues") or []:
            venue_obj = venue if isinstance(venue, Venue) else Venue(str(venue))
            market = VENUE_TO_FUTU_MARKET.get(venue_obj)
            if market is None:
                self._log.warning(f"Unknown venue for Futu: {venue}")
            elif market not in markets:
                markets.append(market)

        for market in markets:
            securities = await self._enumerate_market(market)
            self._log.info(f"Market {market}: {len(securities)} securities found via stock filter")
            await self.load_securities_async(securities)

        for plate in filters.get("plates") or []:
            plate_market, plate_code = plate
            await self.load_plate_async(int(plate_market), str(plate_code))

        for chain in filters.get("option_chains") or []:
            instrument_id = chain["instrument_id"]
            if not isinstance(instrument_id, InstrumentId):
                instrument_id = InstrumentId.from_str(str(instrument_id))
            await self.load_option_chain_async(
                instrument_id,
                begin=str(chain.get("begin", "")),
                end=str(chain.get("end", "")),
                option_type=chain.get("option_type"),
            )

    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict | None = None,
    ) -> None:
        """Load instruments by their IDs (batched into single OpenD requests)."""
        securities = [instrument_id_to_futu_security(i) for i in instrument_ids]
        loaded = await self.load_securities_async(securities)
        found = {inst.id for inst in loaded}
        for instrument_id in instrument_ids:
            if instrument_id not in found:
                self._log.warning(f"Instrument not found on Futu: {instrument_id}")

    async def load_async(
        self,
        instrument_id: InstrumentId,
        filters: dict | None = None,
    ) -> None:
        """Load a single instrument by ID."""
        await self.load_ids_async([instrument_id], filters)

    # ------------------------------------------------------------------
    # Futu-specific helpers
    # ------------------------------------------------------------------

    async def load_securities_async(self, securities: list[tuple[int, str]]) -> list[Instrument]:
        """Fetch static info for ``(market, code)`` pairs, add and return the instruments."""
        instruments: list[Instrument] = []
        for start in range(0, len(securities), STATIC_INFO_BATCH_SIZE):
            batch = securities[start : start + STATIC_INFO_BATCH_SIZE]
            try:
                static_info = await asyncio.to_thread(self._client.get_static_info, batch)
            except Exception as e:
                self._log.error(f"Failed to load static info for {len(batch)} securities: {e}")
                continue
            for info in static_info or []:
                instrument = parse_futu_instrument(info)
                if instrument is None:
                    self._log.warning(f"Failed to parse instrument {info.get('market')}:{info.get('code')}")
                    continue
                self.add(instrument)
                instruments.append(instrument)
        return instruments

    async def load_plate_async(self, plate_market: int, plate_code: str) -> list[Instrument]:
        """Load every security in a Futu plate/sector."""
        try:
            static_info = await asyncio.to_thread(self._client.get_plate_security, plate_market, plate_code)
        except Exception as e:
            self._log.error(f"Failed to load plate {plate_market}:{plate_code}: {e}")
            return []
        instruments: list[Instrument] = []
        for info in static_info or []:
            instrument = parse_futu_instrument(info)
            if instrument is not None:
                self.add(instrument)
                instruments.append(instrument)
        self._log.info(f"Plate {plate_code}: loaded {len(instruments)} instruments")
        return instruments

    async def load_option_chain_async(
        self,
        underlying: InstrumentId,
        begin: str,
        end: str,
        option_type: int | None = None,
    ) -> list[Instrument]:
        """Load the option chain of ``underlying`` expiring between ``begin`` and ``end`` (YYYY-MM-DD)."""
        market, code = instrument_id_to_futu_security(underlying)
        try:
            chain = await asyncio.to_thread(
                self._client.get_option_chain, market, code, begin, end, option_type,
            )
        except Exception as e:
            self._log.error(f"Failed to load option chain for {underlying}: {e}")
            return []
        contracts = parse_option_chain(chain or [], market, code)
        for contract in contracts:
            self.add(contract)
        self._log.info(f"Option chain {underlying}: loaded {len(contracts)} contracts")
        return list(contracts)

    async def _enumerate_market(self, market: int) -> list[tuple[int, str]]:
        """List every security of a market through Qot_StockFilter pagination."""
        securities: list[tuple[int, str]] = []
        begin = 0
        while True:
            try:
                page = await asyncio.to_thread(
                    self._client.stock_filter, market, begin, STOCK_FILTER_PAGE_SIZE,
                )
            except Exception as e:
                self._log.error(f"Stock filter failed for market {market} at offset {begin}: {e}")
                break
            data = page.get("data") or []
            for item in data:
                securities.append((int(item["market"]), str(item["code"])))
            if page.get("last_page", True) or not data:
                break
            begin += len(data)
        return securities
