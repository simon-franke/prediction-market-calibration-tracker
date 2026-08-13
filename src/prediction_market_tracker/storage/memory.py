from prediction_market_tracker.domain import ForecastSnapshot, Market, Resolution


class InMemoryRepository:
    """A development implementation that makes the orchestration executable today."""

    def __init__(self) -> None:
        self.markets: dict[str, Market] = {}
        self.snapshots: list[ForecastSnapshot] = []
        self.resolutions: dict[str, Resolution] = {}

    async def upsert_market(self, market: Market) -> None:
        self.markets[market.id] = market

    async def add_snapshot(self, snapshot: ForecastSnapshot) -> None:
        self.snapshots.append(snapshot)

    async def upsert_resolution(self, resolution: Resolution) -> None:
        self.resolutions[resolution.market_id] = resolution
