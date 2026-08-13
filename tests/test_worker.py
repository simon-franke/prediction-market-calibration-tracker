import asyncio

import pytest

from prediction_market_tracker.ingestion import CollectionReport
from prediction_market_tracker.worker import ScheduledWorker, WorkerSettings


class StoppingCollector:
    def __init__(self, stop_event: asyncio.Event) -> None:
        self.calls = 0
        self.stop_event = stop_event

    async def collect_once(self) -> CollectionReport:
        self.calls += 1
        self.stop_event.set()
        return CollectionReport(markets_seen=3, snapshots_saved=2, resolutions_saved=1)


class FailingCollector:
    def __init__(self, stop_event: asyncio.Event) -> None:
        self.calls = 0
        self.stop_event = stop_event

    async def collect_once(self) -> CollectionReport:
        self.calls += 1
        self.stop_event.set()
        raise RuntimeError("temporary provider outage")


async def test_worker_collects_once_then_stops_cleanly() -> None:
    stop_event = asyncio.Event()
    collector = StoppingCollector(stop_event)

    await ScheduledWorker(collector, interval_seconds=60).run_forever(stop_event)

    assert collector.calls == 1


async def test_worker_logs_and_survives_a_collection_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stop_event = asyncio.Event()
    collector = FailingCollector(stop_event)

    await ScheduledWorker(collector, interval_seconds=60).run_forever(stop_event)

    assert collector.calls == 1
    assert "collection run failed" in caplog.text


def test_worker_settings_read_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@db.example/tracker")
    monkeypatch.setenv("CALIBRATION_INTERVAL_SECONDS", "120")

    settings = WorkerSettings.from_environment(create_schema=True)

    assert settings.interval_seconds == 120
    assert settings.create_schema is True


def test_worker_settings_reject_missing_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        WorkerSettings.from_environment()
