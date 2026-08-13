"""PostgreSQL persistence for canonical prediction-market data."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    MetaData,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from prediction_market_tracker.domain import ForecastSnapshot, Market, Resolution

metadata = MetaData()

markets = Table(
    "markets",
    metadata,
    Column("id", Text, primary_key=True),
    Column("provider", Text, nullable=False),
    Column("external_id", Text, nullable=False),
    Column("question", Text, nullable=False),
    Column("market_type", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("yes_outcome_id", Text),
    Column("opens_at", DateTime(timezone=True)),
    Column("closes_at", DateTime(timezone=True)),
    Column("topics", JSONB, nullable=False, server_default="[]"),
    Column("raw_payload", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("provider", "external_id", name="uq_markets_provider_external_id"),
)

forecast_snapshots = Table(
    "forecast_snapshots",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("market_id", Text, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("probability_yes", Numeric(8, 6), nullable=False),
    Column("volume", Numeric(24, 6)),
    Column("open_interest", Numeric(24, 6)),
    Column("liquidity", Numeric(24, 6)),
    Column("recorded_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "probability_yes >= 0 AND probability_yes <= 1", name="ck_forecast_snapshots_probability"
    ),
    UniqueConstraint("market_id", "observed_at", name="uq_forecast_snapshots_market_observed_at"),
)
Index(
    "ix_forecast_snapshots_market_observed_at",
    forecast_snapshots.c.market_id,
    forecast_snapshots.c.observed_at,
)

resolutions = Table(
    "resolutions",
    metadata,
    Column("market_id", Text, ForeignKey("markets.id", ondelete="CASCADE"), primary_key=True),
    Column("outcome", Text, nullable=False),
    Column("resolved_at", DateTime(timezone=True), nullable=False),
    Column("source", Text, nullable=False),
    Column("is_verified", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


class PostgresRepository:
    """Async PostgreSQL implementation of :class:`TrackerRepository`.

    All writes are idempotent: re-fetching a market updates its metadata, duplicate
    snapshots are ignored, and a later verified resolution can replace an earlier one.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, database_url: str) -> "PostgresRepository":
        """Create a repository from a standard PostgreSQL URL.

        ``postgresql://`` and ``postgres://`` URLs are converted to SQLAlchemy's
        asyncpg dialect. A URL already naming a PostgreSQL dialect is left unchanged.
        """
        return cls(create_async_engine(cls._async_url(database_url), pool_pre_ping=True))

    @staticmethod
    def _async_url(database_url: str) -> str:
        if database_url.startswith("postgresql://"):
            return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if database_url.startswith("postgres://"):
            return database_url.replace("postgres://", "postgresql+asyncpg://", 1)
        if database_url.startswith("postgresql+asyncpg://"):
            return database_url
        raise ValueError("database_url must be a PostgreSQL URL")

    async def create_schema(self) -> None:
        """Create the initial schema for a new database.

        Use this for local/bootstrap environments; production deployments should run
        versioned migrations before starting application workers.
        """
        async with self._engine.begin() as connection:
            await connection.run_sync(metadata.create_all)

    async def close(self) -> None:
        await self._engine.dispose()

    async def upsert_market(self, market: Market) -> None:
        values = {
            "id": market.id,
            "provider": market.provider,
            "external_id": market.external_id,
            "question": market.question,
            "market_type": market.market_type.value,
            "status": market.status.value,
            "yes_outcome_id": market.yes_outcome_id,
            "opens_at": market.opens_at,
            "closes_at": market.closes_at,
            "topics": list(market.topics),
            "raw_payload": market.raw_payload,
        }
        statement = insert(markets).values(**values)
        update_values = {key: statement.excluded[key] for key in values if key != "id"}
        update_values["updated_at"] = func.now()

        async with self._engine.begin() as connection:
            await connection.execute(
                statement.on_conflict_do_update(index_elements=[markets.c.id], set_=update_values)
            )

    async def add_snapshot(self, snapshot: ForecastSnapshot) -> None:
        statement = insert(forecast_snapshots).values(
            market_id=snapshot.market_id,
            observed_at=snapshot.observed_at,
            probability_yes=snapshot.probability_yes,
            volume=snapshot.volume,
            open_interest=snapshot.open_interest,
            liquidity=snapshot.liquidity,
        )

        async with self._engine.begin() as connection:
            await connection.execute(
                statement.on_conflict_do_nothing(
                    constraint="uq_forecast_snapshots_market_observed_at"
                )
            )

    async def upsert_resolution(self, resolution: Resolution) -> None:
        values = {
            "market_id": resolution.market_id,
            "outcome": resolution.outcome.value,
            "resolved_at": resolution.resolved_at,
            "source": resolution.source,
            "is_verified": resolution.is_verified,
        }
        statement = insert(resolutions).values(**values)
        update_values = {key: statement.excluded[key] for key in values if key != "market_id"}
        update_values["updated_at"] = func.now()

        async with self._engine.begin() as connection:
            await connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[resolutions.c.market_id], set_=update_values
                )
            )
