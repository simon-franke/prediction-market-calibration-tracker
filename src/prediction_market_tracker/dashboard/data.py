"""Read-only PostgreSQL queries used by the dashboard."""

import pandas as pd
from sqlalchemy import create_engine, text

RESOLVED_FORECASTS_QUERY = text("""
    SELECT
        snapshots.market_id,
        markets.question,
        markets.provider,
        markets.topics,
        snapshots.observed_at,
        snapshots.probability_yes::double precision AS probability_yes,
        snapshots.volume::double precision AS volume,
        snapshots.open_interest::double precision AS open_interest,
        snapshots.liquidity::double precision AS liquidity,
        resolutions.outcome,
        resolutions.resolved_at
    FROM forecast_snapshots AS snapshots
    INNER JOIN markets ON markets.id = snapshots.market_id
    INNER JOIN resolutions ON resolutions.market_id = snapshots.market_id
    WHERE resolutions.outcome IN ('yes', 'no')
      AND snapshots.observed_at < resolutions.resolved_at
    ORDER BY snapshots.observed_at ASC
""")


def load_resolved_forecasts(database_url: str) -> pd.DataFrame:
    """Load forecasts with known binary outcomes; this function never mutates data."""
    engine = create_engine(_sync_url(database_url), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            return pd.read_sql(RESOLVED_FORECASTS_QUERY, connection)
    finally:
        engine.dispose()


def _sync_url(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql+psycopg://"):
        return database_url
    raise ValueError("database_url must be a PostgreSQL URL")
