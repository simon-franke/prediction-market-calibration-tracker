"""Supabase Data API persistence for environments without PostgreSQL socket access."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from prediction_market_tracker.domain import ForecastSnapshot, Market, Resolution


class SupabaseRepository:
    """Write tracker data through Supabase's HTTPS PostgREST API.

    A Supabase service-role key is required because the tables are protected with row-level
    security. This avoids a direct PostgreSQL connection, which is unavailable from some
    free CI hosts on IPv4-only networks.
    """

    def __init__(
        self,
        supabase_url: str,
        service_role_key: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not supabase_url.startswith(("https://", "http://")):
            raise ValueError("SUPABASE_URL must be an HTTP(S) URL")
        if not service_role_key:
            raise ValueError("SUPABASE_SERVICE_ROLE_KEY must not be empty")

        self._base_url = f"{supabase_url.rstrip('/')}/rest/v1"
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        }

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def upsert_market(self, market: Market) -> None:
        await self._upsert(
            "markets",
            {
                "id": market.id,
                "provider": market.provider,
                "external_id": market.external_id,
                "question": market.question,
                "market_type": market.market_type.value,
                "status": market.status.value,
                "yes_outcome_id": market.yes_outcome_id,
                "opens_at": self._timestamp(market.opens_at),
                "closes_at": self._timestamp(market.closes_at),
                "topics": list(market.topics),
                "raw_payload": market.raw_payload,
            },
            conflict_columns="id",
            resolution="merge-duplicates",
        )

    async def add_snapshot(self, snapshot: ForecastSnapshot) -> None:
        await self._upsert(
            "forecast_snapshots",
            {
                "market_id": snapshot.market_id,
                "observed_at": self._timestamp(snapshot.observed_at),
                "probability_yes": self._decimal(snapshot.probability_yes),
                "volume": self._decimal(snapshot.volume),
                "open_interest": self._decimal(snapshot.open_interest),
                "liquidity": self._decimal(snapshot.liquidity),
            },
            conflict_columns="market_id,observed_at",
            resolution="ignore-duplicates",
        )

    async def upsert_resolution(self, resolution: Resolution) -> None:
        await self._upsert(
            "resolutions",
            {
                "market_id": resolution.market_id,
                "outcome": resolution.outcome.value,
                "resolved_at": self._timestamp(resolution.resolved_at),
                "source": resolution.source,
                "is_verified": resolution.is_verified,
            },
            conflict_columns="market_id",
            resolution="merge-duplicates",
        )

    async def _upsert(
        self,
        table: str,
        values: Mapping[str, Any],
        *,
        conflict_columns: str,
        resolution: str,
    ) -> None:
        response = await self._client.post(
            f"{self._base_url}/{table}",
            params={"on_conflict": conflict_columns},
            headers={**self._headers, "Prefer": f"resolution={resolution},return=minimal"},
            json=values,
        )
        response.raise_for_status()

    @staticmethod
    def _timestamp(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _decimal(value: Decimal | None) -> str | None:
        return str(value) if value is not None else None
