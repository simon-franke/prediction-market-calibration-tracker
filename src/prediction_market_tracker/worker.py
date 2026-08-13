"""Long-running collection worker for deployed environments."""

import argparse
import asyncio
import logging
import os
import signal
import time
from dataclasses import dataclass
from typing import Protocol

from prediction_market_tracker.ingestion import CollectionReport, SnapshotCollector
from prediction_market_tracker.providers import PolymarketProvider
from prediction_market_tracker.storage import PostgresRepository

logger = logging.getLogger(__name__)


class Collector(Protocol):
    async def collect_once(self) -> CollectionReport: ...


@dataclass(frozen=True, slots=True)
class WorkerSettings:
    database_url: str
    interval_seconds: int = 900
    create_schema: bool = False

    @classmethod
    def from_environment(cls, *, create_schema: bool = False) -> "WorkerSettings":
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL must be set before starting the collection worker")

        raw_interval = os.environ.get("CALIBRATION_INTERVAL_SECONDS", "900")
        try:
            interval_seconds = int(raw_interval)
        except ValueError as error:
            raise RuntimeError("CALIBRATION_INTERVAL_SECONDS must be an integer") from error
        if interval_seconds < 1:
            raise RuntimeError("CALIBRATION_INTERVAL_SECONDS must be at least one second")

        return cls(
            database_url=database_url,
            interval_seconds=interval_seconds,
            create_schema=create_schema,
        )


class ScheduledWorker:
    """Run collection serially at a fixed interval until asked to stop."""

    def __init__(self, collector: Collector, *, interval_seconds: int) -> None:
        if interval_seconds < 1:
            raise ValueError("interval_seconds must be at least one second")
        self._collector = collector
        self._interval_seconds = interval_seconds

    async def collect_once(self) -> CollectionReport:
        report = await self._collector.collect_once()
        logger.info(
            "collection complete: markets=%d snapshots=%d resolutions=%d",
            report.markets_seen,
            report.snapshots_saved,
            report.resolutions_saved,
        )
        return report

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        """Continue after collection errors, with no overlapping collection runs."""
        while not stop_event.is_set():
            started_at = time.monotonic()
            try:
                await self.collect_once()
            except Exception:
                logger.exception(
                    "collection run failed; the worker will retry on its next interval"
                )

            if stop_event.is_set():
                return

            remaining_seconds = max(0, self._interval_seconds - (time.monotonic() - started_at))
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=remaining_seconds)
            except TimeoutError:
                continue


def _install_shutdown_handlers(stop_event: asyncio.Event) -> None:
    """Request a graceful stop when a container or process manager sends a signal."""
    loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(shutdown_signal, stop_event.set)
        except (NotImplementedError, RuntimeError):
            # Signal handlers are unavailable in some local and Windows event loops.
            pass


async def run_worker(
    settings: WorkerSettings,
    *,
    once: bool = False,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Create infrastructure, run collection, and always release network resources."""
    repository = PostgresRepository.from_url(settings.database_url)
    provider = PolymarketProvider()
    try:
        if settings.create_schema:
            await repository.create_schema()

        worker = ScheduledWorker(
            SnapshotCollector(provider, repository), interval_seconds=settings.interval_seconds
        )
        if once:
            await worker.collect_once()
            return

        active_stop_event = stop_event or asyncio.Event()
        if stop_event is None:
            _install_shutdown_handlers(active_stop_event)
        await worker.run_forever(active_stop_event)
    finally:
        await provider.aclose()
        await repository.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect prediction-market forecasts on a schedule"
    )
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="create the initial database schema before collecting",
    )
    parser.add_argument("--once", action="store_true", help="perform one collection run and exit")
    arguments = parser.parse_args()

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
    settings = WorkerSettings.from_environment(create_schema=arguments.create_schema)
    asyncio.run(run_worker(settings, once=arguments.once))
