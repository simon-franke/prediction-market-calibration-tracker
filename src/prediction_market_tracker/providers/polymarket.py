import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from prediction_market_tracker.domain import (
    ForecastSnapshot,
    Market,
    MarketStatus,
    MarketType,
    Resolution,
    ResolutionOutcome,
)


class PolymarketProvider:
    """Adapter for Polymarket's public Gamma and CLOB market-data APIs."""

    name = "polymarket"
    gamma_url = "https://gamma-api.polymarket.com"
    clob_url = "https://clob.polymarket.com"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=20.0)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def list_markets(self, *, active: bool) -> AsyncIterator[Market]:
        offset = 0
        page_size = 500

        while True:
            response = await self._client.get(
                f"{self.gamma_url}/markets",
                params={
                    "active": str(active).lower(),
                    "closed": str(not active).lower(),
                    "limit": page_size,
                    "offset": offset,
                },
            )
            response.raise_for_status()
            payload = response.json()
            items, has_more = self._items_from_response(payload)

            for item in items:
                market = self._market_from_payload(item)
                if market is not None:
                    yield market

            if not has_more or len(items) < page_size:
                return
            offset += len(items)

    async def current_snapshot(self, market: Market) -> ForecastSnapshot | None:
        if market.yes_outcome_id is None:
            return None

        response = await self._client.get(
            f"{self.clob_url}/midpoint", params={"token_id": market.yes_outcome_id}
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        response.raise_for_status()

        payload = response.json()
        probability = self._decimal(payload.get("mid") or payload.get("midpoint"))
        if probability is None or not Decimal("0") <= probability <= Decimal("1"):
            return None

        raw = market.raw_payload
        return ForecastSnapshot(
            market_id=market.id,
            observed_at=datetime.now(UTC),
            probability_yes=probability,
            volume=self._decimal(raw.get("volumeNum") or raw.get("volume")),
            open_interest=self._decimal(raw.get("openInterest")),
            liquidity=self._decimal(raw.get("liquidityNum") or raw.get("liquidity")),
        )

    async def price_history(
        self, market: Market, *, start: datetime, end: datetime
    ) -> list[ForecastSnapshot]:
        if market.yes_outcome_id is None:
            return []

        response = await self._client.get(
            f"{self.clob_url}/prices-history",
            params={
                "market": market.yes_outcome_id,
                "startTs": int(start.timestamp()),
                "endTs": int(end.timestamp()),
                "interval": "1h",
            },
        )
        response.raise_for_status()

        snapshots: list[ForecastSnapshot] = []
        for point in response.json().get("history", []):
            probability = self._decimal(point.get("p"))
            timestamp = point.get("t")
            is_valid_probability = (
                probability is not None and Decimal("0") <= probability <= Decimal("1")
            )
            if timestamp is None or not is_valid_probability:
                continue
            snapshots.append(
                ForecastSnapshot(
                    market_id=market.id,
                    observed_at=datetime.fromtimestamp(float(timestamp), UTC),
                    probability_yes=probability,
                )
            )
        return snapshots

    async def resolution(self, market: Market) -> Resolution | None:
        raw = market.raw_payload
        if not raw.get("closed") or market.yes_outcome_id is None:
            return None

        outcome_prices = self._as_sequence(raw.get("outcomePrices"))
        token_ids = self._as_sequence(raw.get("clobTokenIds"))
        try:
            yes_index = token_ids.index(market.yes_outcome_id)
            yes_price = self._decimal(outcome_prices[yes_index])
        except (IndexError, ValueError):
            return None

        if yes_price == Decimal("1"):
            outcome = ResolutionOutcome.YES
        elif yes_price == Decimal("0"):
            outcome = ResolutionOutcome.NO
        else:
            return None

        resolved_at = self._datetime_from(raw, "closedTime", "endDate", "end_date_iso")
        if resolved_at is None:
            return None
        return Resolution(
            market_id=market.id,
            outcome=outcome,
            resolved_at=resolved_at,
            source="polymarket",
            is_verified=False,
        )

    @classmethod
    def _market_from_payload(cls, raw: dict[str, Any]) -> Market | None:
        outcomes = cls._as_sequence(raw.get("outcomes"))
        token_ids = cls._as_sequence(raw.get("clobTokenIds"))
        external_id = str(raw.get("conditionId") or raw.get("id") or "")
        question = str(raw.get("question") or raw.get("title") or "")
        if not external_id or not question:
            return None

        outcome_names = [str(outcome).casefold() for outcome in outcomes]
        is_binary = len(outcomes) == 2 and {"yes", "no"}.issubset(outcome_names)
        yes_outcome_id = None
        if is_binary and len(token_ids) == len(outcomes):
            yes_outcome_id = str(token_ids[outcome_names.index("yes")])

        status = MarketStatus.OPEN
        if raw.get("closed"):
            status = MarketStatus.CLOSED

        return Market(
            provider=cls.name,
            external_id=external_id,
            question=question,
            market_type=MarketType.BINARY if is_binary else MarketType.MULTI_OUTCOME,
            status=status,
            yes_outcome_id=yes_outcome_id,
            opens_at=cls._datetime_from(raw, "startDate", "creationDate"),
            closes_at=cls._datetime_from(raw, "endDate", "closeTime"),
            topics=cls._topics_from(raw),
            raw_payload=raw,
        )

    @staticmethod
    def _items_from_response(payload: Any) -> tuple[list[dict[str, Any]], bool]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)], len(payload) == 500
        if isinstance(payload, dict):
            items = payload.get("data", payload.get("markets", []))
            parsed_items: list[dict[str, Any]] = []
            if isinstance(items, list):
                parsed_items = [item for item in items if isinstance(item, dict)]
            return parsed_items, bool(payload.get("has_more"))
        return [], False

    @staticmethod
    def _as_sequence(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return []
            return decoded if isinstance(decoded, list) else []
        return []

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    @classmethod
    def _datetime_from(cls, raw: dict[str, Any], *keys: str) -> datetime | None:
        for key in keys:
            value = raw.get(key)
            if not value:
                continue
            try:
                return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                continue
        return None

    @classmethod
    def _topics_from(cls, raw: dict[str, Any]) -> tuple[str, ...]:
        topics: list[str] = []
        category = raw.get("category")
        if isinstance(category, str) and category:
            topics.append(category)
        for tag in cls._as_sequence(raw.get("tags")):
            if isinstance(tag, str):
                topics.append(tag)
            elif isinstance(tag, dict) and isinstance(tag.get("label") or tag.get("slug"), str):
                topics.append(str(tag.get("label") or tag["slug"]))
        return tuple(dict.fromkeys(topic.strip() for topic in topics if topic.strip()))
