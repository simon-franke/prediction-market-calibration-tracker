from typing import Protocol

from prediction_market_tracker.domain import ForecastSnapshot, Market, Resolution


class TrackerRepository(Protocol):
    """Persistence boundary; implement this with PostgreSQL in production."""

    async def upsert_market(self, market: Market) -> None: ...

    async def add_snapshot(self, snapshot: ForecastSnapshot) -> None: ...

    async def upsert_resolution(self, resolution: Resolution) -> None: ...
