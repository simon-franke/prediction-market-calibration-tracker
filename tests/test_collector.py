from datetime import UTC, datetime
from decimal import Decimal

from prediction_market_tracker.domain import ForecastSnapshot, Market, MarketStatus, MarketType
from prediction_market_tracker.ingestion import SnapshotCollector
from prediction_market_tracker.storage import InMemoryRepository


class FakeProvider:
    name = "fake"

    def __init__(self, market: Market, snapshot: ForecastSnapshot) -> None:
        self.market = market
        self.snapshot = snapshot

    async def list_markets(self, *, active: bool):
        if active:
            yield self.market

    async def current_snapshot(self, market: Market) -> ForecastSnapshot:
        assert market == self.market
        return self.snapshot

    async def price_history(self, market: Market, *, start: datetime, end: datetime):
        return []

    async def resolution(self, market: Market):
        return None


async def test_collector_is_provider_agnostic() -> None:
    market = Market(
        provider="fake",
        external_id="market-123",
        question="Will this test pass?",
        market_type=MarketType.BINARY,
        status=MarketStatus.OPEN,
        yes_outcome_id="yes-token",
    )
    snapshot = ForecastSnapshot(
        market_id=market.id,
        observed_at=datetime(2026, 8, 13, tzinfo=UTC),
        probability_yes=Decimal("0.7"),
    )
    repository = InMemoryRepository()

    report = await SnapshotCollector(FakeProvider(market, snapshot), repository).collect_once()

    assert report.markets_seen == 1
    assert report.snapshots_saved == 1
    assert repository.markets[market.id] == market
    assert repository.snapshots == [snapshot]
