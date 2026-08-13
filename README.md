# Prediction Market Calibration Tracker

A provider-neutral research tool for measuring whether prediction-market probabilities
match observed outcomes.

The project starts with a Polymarket adapter, but all ingestion and analytics code uses
canonical domain models so other sources can be added without rewriting the tracker.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
uvicorn prediction_market_tracker.api:app --reload
```

The API is then available at `http://127.0.0.1:8000`, with a health endpoint at
`/health`.

## Architecture

```text
providers -> ingestion -> repository -> analytics/dashboard
```

- `domain`: provider-independent market, snapshot, and resolution models.
- `providers`: adapters that translate an external API into the domain interface.
- `ingestion`: orchestration that records periodic market snapshots.
- `storage`: persistence boundary, with in-memory and PostgreSQL implementations.
- `analytics`: provider-independent calibration calculations (next milestone).

## First production milestone

Run `SnapshotCollector` every 15 minutes with a PostgreSQL-backed repository. Historical
price data is available separately through `PredictionMarketProvider.price_history` for
backfills.

## PostgreSQL

Set `DATABASE_URL` to a standard PostgreSQL connection URL, for example
`postgresql://user:password@host:5432/calibration_tracker`. The repository converts it
to the async driver automatically.

Create the initial schema once during local setup or deployment bootstrap:

```python
import asyncio
import os

from prediction_market_tracker.storage import PostgresRepository


async def bootstrap() -> None:
    repository = PostgresRepository.from_url(os.environ["DATABASE_URL"])
    try:
        await repository.create_schema()
    finally:
        await repository.close()


asyncio.run(bootstrap())
```

`PostgresRepository` implements the same interface as `InMemoryRepository`, so pass it
directly to `SnapshotCollector`. Its writes are idempotent: market metadata and
resolutions are upserted, while duplicate market/timestamp snapshots are ignored.

## Scheduled worker

The worker is a separate process from the web API, so it can run continuously as a
single worker service alongside the web service. It serializes runs—there is never more
than one collection in flight—and logs a failed run before retrying on the next interval.

```bash
export DATABASE_URL='postgresql://user:password@host:5432/calibration_tracker'
export CALIBRATION_INTERVAL_SECONDS=900  # optional; defaults to 15 minutes
calibration-worker --create-schema
```

Use `--create-schema` only when bootstrapping a fresh database. For a one-off manual
collection, use `calibration-worker --once`. The worker handles `SIGTERM` and `SIGINT`
so a host can stop it cleanly after the current collection completes.

## Dashboard

The Streamlit dashboard is a separate, read-only service over the same PostgreSQL
database. It provides calibration reliability plots, topic/time/liquidity filters, and
individual market forecast paths.

```bash
export DATABASE_URL='postgresql://user:password@host:5432/calibration_tracker'
calibration-dashboard
```

It listens on Streamlit's default port (`8501`). Set `LOG_LEVEL` for the worker and use
the dashboard's **Refresh data** button to clear its 60-second data cache. Deploy it as a
third process next to the API and scheduled worker.

## Free student deployment

This repository can be deployed without an always-on server using GitHub Actions,
Supabase, and Streamlit Community Cloud:

```text
GitHub Actions (every 15 minutes) -> Supabase Postgres <- Streamlit Community Cloud
```

The scheduled collector is defined in `.github/workflows/collect.yml`. It runs
`calibration-worker --create-schema --once`, so schema creation is safe on a first run and
later executions collect a single snapshot batch without overlapping another workflow run.

1. Create a Supabase project and, in **Connect**, copy the **Session pooler** PostgreSQL
   connection string (port `5432`). Replace `[YOUR-PASSWORD]` with the database password.
   Do not use the direct connection string: on Supabase Free it is IPv6-only, whereas
   GitHub Actions needs the IPv4-compatible session pooler.
2. In the GitHub repository, create an Actions secret named `DATABASE_URL` containing that
   connection string. Run **Collect market snapshots** manually once from the Actions tab to
   initialize the schema and verify the collector.
3. In Streamlit Community Cloud, deploy
   `src/prediction_market_tracker/dashboard/app.py` from this repository. In **Advanced
   settings -> Secrets**, add:

   ```toml
   DATABASE_URL = "postgresql://..."
   ```

   The dashboard reads this secret directly in Community Cloud and continues to use the
   `DATABASE_URL` environment variable in Docker and local development.

Keep the database URL only in GitHub Actions secrets and Streamlit secrets—never commit it
to `.env.example`, source code, or the repository. This is intended for a hobby/student
deployment: GitHub Actions schedules can be delayed, and Supabase Free has a 500 MB database
limit with no managed backups.

## Docker Compose

Docker Compose starts PostgreSQL, a one-shot schema bootstrap, the scheduled worker, the
dashboard, and the health API. PostgreSQL data lives in the named `postgres_data` volume.

```bash
cp .env.example .env
# Edit .env and replace POSTGRES_PASSWORD.
docker compose up --build -d
```

Open the dashboard at `http://localhost:8501`; the API health endpoint is at
`http://localhost:8000/health`. Check all services with `docker compose ps` and worker
activity with `docker compose logs -f worker`.

Use `docker compose down` to stop the stack while retaining database data. `docker compose
down --volumes` also removes the PostgreSQL volume and therefore all collected forecasts.
