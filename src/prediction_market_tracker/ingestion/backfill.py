"""Historical forecast backfills for markets that have already resolved."""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from prediction_market_tracker.domain import ForecastSnapshot, Market, Resolution
from prediction_market_tracker.storage.repository import TrackerRepository

logger = logging.getLogger(__name__)


class HistoricalPriceProvider(Protocol):
    async def list_recently_resolved_markets(self, *, limit: int) -> AsyncIterator[Market]: ...

    async def price_history(
        self, market: Market, *, start: datetime, end: datetime, interval: str
    ) -> list[ForecastSnapshot]: ...

    async def resolution(self, market: Market) -> Resolution | None: ...


@dataclass(frozen=True, slots=True)
class BackfillReport:
    markets_seen: int
    resolutions_saved: int
    snapshots_saved: int


class HistoricalBackfill:
    """Store daily historical prices for a bounded number of resolved binary markets."""

    def __init__(self, provider: HistoricalPriceProvider, repository: TrackerRepository) -> None:
        self._provider = provider
        self._repository = repository

    async def run(self, *, limit: int) -> BackfillReport:
        if limit < 1:
            raise ValueError("limit must be at least one")

        markets_seen = resolutions_saved = snapshots_saved = 0
        async for market in self._provider.list_recently_resolved_markets(limit=limit):
            markets_seen += 1
            await self._repository.upsert_market(market)

            resolution = await self._provider.resolution(market)
            if resolution is None or market.yes_outcome_id is None:
                continue
            await self._repository.upsert_resolution(resolution)
            resolutions_saved += 1

            start = market.opens_at or resolution.resolved_at - timedelta(days=365)
            if start >= resolution.resolved_at:
                continue
            try:
                snapshots = await self._provider.price_history(
                    market,
                    start=start,
                    end=resolution.resolved_at,
                    interval="1d",
                )
            except Exception:
                logger.warning("could not fetch historical prices for %s", market.id, exc_info=True)
                continue
            for snapshot in snapshots:
                await self._repository.add_snapshot(snapshot)
                snapshots_saved += 1

        return BackfillReport(
            markets_seen=markets_seen,
            resolutions_saved=resolutions_saved,
            snapshots_saved=snapshots_saved,
        )
