"""Database schema bootstrap command for container deployments."""

import asyncio
import os

from prediction_market_tracker.storage import PostgresRepository


async def bootstrap() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set before bootstrapping the database")

    repository = PostgresRepository.from_url(database_url)
    try:
        await repository.create_schema()
    finally:
        await repository.close()


def main() -> None:
    asyncio.run(bootstrap())
