import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from prediction_market_tracker.storage.postgres import (
    PostgresRepository,
    forecast_snapshots,
    markets,
    metadata,
    resolutions,
)


@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        ("postgresql://user:password@db.example/tracker", "postgresql+asyncpg://"),
        ("postgres://user:password@db.example/tracker", "postgresql+asyncpg://"),
        ("postgresql+asyncpg://user:password@db.example/tracker", "postgresql+asyncpg://"),
    ],
)
def test_normalizes_postgresql_urls_for_asyncpg(database_url: str, expected: str) -> None:
    assert PostgresRepository._async_url(database_url).startswith(expected)


def test_rejects_non_postgresql_database_url() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        PostgresRepository._async_url("sqlite:///tracker.db")


def test_schema_has_the_expected_calibration_relationships() -> None:
    assert set(metadata.tables) == {"markets", "forecast_snapshots", "resolutions"}
    assert forecast_snapshots.c.market_id.foreign_keys
    assert resolutions.c.market_id.foreign_keys
    constraint_names = {constraint.name for constraint in forecast_snapshots.constraints}
    assert "uq_forecast_snapshots_market_observed_at" in constraint_names

    ddl = str(CreateTable(markets).compile(dialect=postgresql.dialect()))
    assert "JSONB" in ddl
