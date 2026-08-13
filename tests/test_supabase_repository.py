import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from prediction_market_tracker.domain import ForecastSnapshot
from prediction_market_tracker.storage.supabase import SupabaseRepository


async def test_snapshot_insert_uses_the_supabase_rest_api() -> None:
    received: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(201, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    repository = SupabaseRepository("https://example.supabase.co", "secret", client)

    await repository.add_snapshot(
        ForecastSnapshot(
            market_id="polymarket:1",
            observed_at=datetime(2026, 8, 13, 10, 30, tzinfo=UTC),
            probability_yes=Decimal("0.42"),
        )
    )

    assert received[0].url.path == "/rest/v1/forecast_snapshots"
    assert received[0].url.params["on_conflict"] == "market_id,observed_at"
    assert received[0].headers["apikey"] == "secret"
    assert received[0].headers["prefer"] == "resolution=ignore-duplicates,return=minimal"
    assert json.loads(received[0].content) == {
        "market_id": "polymarket:1",
        "observed_at": "2026-08-13T10:30:00+00:00",
        "probability_yes": "0.42",
        "volume": None,
        "open_interest": None,
        "liquidity": None,
    }

    await client.aclose()
