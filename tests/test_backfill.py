from datetime import UTC, datetime
from decimal import Decimal

from prediction_market_tracker.domain import (
    ForecastSnapshot,
    Market,
    MarketStatus,
    MarketType,
    Resolution,
    ResolutionOutcome,
)
from prediction_market_tracker.ingestion.backfill import HistoricalBackfill
from prediction_market_tracker.storage import InMemoryRepository


class FakeHistoricalProvider:
    def __init__(
        self, market: Market, resolution: Resolution, snapshots: list[ForecastSnapshot]
    ) -> None:
        self.market = market
        self.resolution_value = resolution
        self.snapshots = snapshots
        self.history_interval: str | None = None

    async def list_markets(self, *, active: bool):
        if not active:
            yield self.market

    async def price_history(self, market: Market, *, start, end, interval: str):
        assert market == self.market
        assert start < end
        self.history_interval = interval
        return self.snapshots

    async def resolution(self, market: Market):
        assert market == self.market
        return self.resolution_value


async def test_backfill_stores_daily_history_for_resolved_binary_markets() -> None:
    market = Market(
        provider="fake",
        external_id="market-1",
        question="Will the backfill work?",
        market_type=MarketType.BINARY,
        status=MarketStatus.CLOSED,
        yes_outcome_id="yes-token",
        opens_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    resolution = Resolution(
        market_id=market.id,
        outcome=ResolutionOutcome.YES,
        resolved_at=datetime(2026, 8, 10, tzinfo=UTC),
        source="fake",
    )
    snapshots = [
        ForecastSnapshot(
            market_id=market.id,
            observed_at=datetime(2026, 8, 5, tzinfo=UTC),
            probability_yes=Decimal("0.6"),
        )
    ]
    provider = FakeHistoricalProvider(market, resolution, snapshots)
    repository = InMemoryRepository()

    report = await HistoricalBackfill(provider, repository).run(limit=1)

    assert report.markets_seen == 1
    assert report.resolutions_saved == 1
    assert report.snapshots_saved == 1
    assert repository.snapshots == snapshots
    assert provider.history_interval == "1d"
