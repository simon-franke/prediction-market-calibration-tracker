"""Read-only PostgreSQL and Supabase Data API queries used by the dashboard."""

from collections.abc import Iterable

import httpx
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


def load_resolved_forecasts(
    database_url: str | None = None,
    *,
    supabase_url: str | None = None,
    supabase_service_role_key: str | None = None,
) -> pd.DataFrame:
    """Load forecasts with known binary outcomes; this function never mutates data."""
    if supabase_url and supabase_service_role_key:
        return _load_supabase_forecasts(supabase_url, supabase_service_role_key)
    if database_url is None:
        raise ValueError("Set DATABASE_URL or Supabase API credentials")

    engine = create_engine(_sync_url(database_url), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            return pd.read_sql(RESOLVED_FORECASTS_QUERY, connection)
    finally:
        engine.dispose()


def _load_supabase_forecasts(supabase_url: str, service_role_key: str) -> pd.DataFrame:
    """Fetch and join tracker tables through Supabase's IPv4-compatible HTTPS API."""
    base_url = f"{supabase_url.rstrip('/')}/rest/v1"
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
    }
    with httpx.Client(timeout=30.0) as client:
        markets = pd.DataFrame(_fetch_all(client, base_url, "markets", headers))
        snapshots = pd.DataFrame(_fetch_all(client, base_url, "forecast_snapshots", headers))
        resolutions = pd.DataFrame(_fetch_all(client, base_url, "resolutions", headers))

    required_columns = {
        "markets": {"id", "question", "provider", "topics"},
        "snapshots": {
            "market_id",
            "observed_at",
            "probability_yes",
            "volume",
            "open_interest",
            "liquidity",
        },
        "resolutions": {"market_id", "outcome", "resolved_at"},
    }
    tables = {"markets": markets, "snapshots": snapshots, "resolutions": resolutions}
    has_all_required_columns = all(
        columns.issubset(tables[name].columns) for name, columns in required_columns.items()
    )
    if not has_all_required_columns:
        return pd.DataFrame()

    resolved = resolutions.loc[resolutions["outcome"].isin(["yes", "no"])]
    forecasts = snapshots.merge(
        markets[["id", "question", "provider", "topics"]],
        left_on="market_id",
        right_on="id",
        how="inner",
    ).merge(resolved[["market_id", "outcome", "resolved_at"]], on="market_id", how="inner")
    return forecasts.loc[
        pd.to_datetime(forecasts["observed_at"], utc=True)
        < pd.to_datetime(forecasts["resolved_at"], utc=True)
    ].sort_values("observed_at")


def _fetch_all(
    client: httpx.Client,
    base_url: str,
    table: str,
    headers: dict[str, str],
    *,
    page_size: int = 1_000,
) -> Iterable[dict[str, object]]:
    rows: list[dict[str, object]] = []
    start = 0
    while True:
        response = client.get(
            f"{base_url}/{table}",
            params={"select": "*"},
            headers={
                **headers,
                "Range-Unit": "items",
                "Range": f"{start}-{start + page_size - 1}",
            },
        )
        response.raise_for_status()
        page = response.json()
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size


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
