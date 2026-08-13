"""One-time historical backfill command for hosted deployments."""

import argparse
import asyncio
import logging
import os

from prediction_market_tracker.ingestion.backfill import HistoricalBackfill
from prediction_market_tracker.providers import PolymarketProvider
from prediction_market_tracker.worker import WorkerSettings, _repository_from_settings

logger = logging.getLogger(__name__)


async def run_backfill(settings: WorkerSettings, *, limit: int) -> None:
    repository = _repository_from_settings(settings)
    provider = PolymarketProvider()
    try:
        report = await HistoricalBackfill(provider, repository).run(limit=limit)
        logger.info(
            "backfill complete: markets=%d snapshots=%d resolutions=%d",
            report.markets_seen,
            report.snapshots_saved,
            report.resolutions_saved,
        )
    finally:
        await provider.aclose()
        await repository.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill historical Polymarket prices for recently resolved markets"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="maximum number of closed markets to backfill (default: 25)",
    )
    arguments = parser.parse_args()
    if arguments.limit < 1:
        parser.error("--limit must be at least one")

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
    asyncio.run(run_backfill(WorkerSettings.from_environment(), limit=arguments.limit))
