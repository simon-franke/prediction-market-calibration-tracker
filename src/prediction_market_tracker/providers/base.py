from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol

from prediction_market_tracker.domain import ForecastSnapshot, Market, Resolution


class PredictionMarketProvider(Protocol):
    """The small boundary that every external market-data adapter implements."""

    name: str

    async def list_markets(self, *, active: bool) -> AsyncIterator[Market]:
        """Yield markets available from this provider."""

    async def current_snapshot(self, market: Market) -> ForecastSnapshot | None:
        """Return the latest usable Yes-probability forecast, if available."""

    async def price_history(
        self, market: Market, *, start: datetime, end: datetime
    ) -> list[ForecastSnapshot]:
        """Return historical price points for backfills."""

    async def resolution(self, market: Market) -> Resolution | None:
        """Return a final market resolution only when one is available."""
