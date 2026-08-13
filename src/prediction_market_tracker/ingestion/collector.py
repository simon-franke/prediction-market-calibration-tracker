from dataclasses import dataclass

from prediction_market_tracker.providers.base import PredictionMarketProvider
from prediction_market_tracker.storage.repository import TrackerRepository


@dataclass(frozen=True, slots=True)
class CollectionReport:
    markets_seen: int
    snapshots_saved: int
    resolutions_saved: int


class SnapshotCollector:
    """Records active forecasts and final resolutions in separate provider passes."""

    def __init__(self, provider: PredictionMarketProvider, repository: TrackerRepository) -> None:
        self.provider = provider
        self.repository = repository

    async def collect_once(self) -> CollectionReport:
        markets_seen = snapshots_saved = resolutions_saved = 0

        async for market in self.provider.list_markets(active=True):
            markets_seen += 1
            await self.repository.upsert_market(market)

            snapshot = await self.provider.current_snapshot(market)
            if snapshot is not None:
                await self.repository.add_snapshot(snapshot)
                snapshots_saved += 1

        async for market in self.provider.list_markets(active=False):
            await self.repository.upsert_market(market)
            resolution = await self.provider.resolution(market)
            if resolution is not None:
                await self.repository.upsert_resolution(resolution)
                resolutions_saved += 1

        return CollectionReport(markets_seen, snapshots_saved, resolutions_saved)
