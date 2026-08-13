from datetime import UTC, datetime
from decimal import Decimal

import httpx

from prediction_market_tracker.domain import Market, MarketStatus, MarketType, ResolutionOutcome
from prediction_market_tracker.providers.polymarket import PolymarketProvider


def test_market_payload_is_normalized_without_leaking_provider_shape() -> None:
    raw_market = {
        "id": "123",
        "question": "Will the tracker launch?",
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": '["yes-token", "no-token"]',
        "category": "Technology",
        "endDate": "2026-09-01T12:00:00Z",
    }

    market = PolymarketProvider._market_from_payload(raw_market)

    assert market is not None
    assert market.id == "polymarket:123"
    assert market.market_type == MarketType.BINARY
    assert market.yes_outcome_id == "yes-token"
    assert market.topics == ("Technology",)
    assert market.closes_at == datetime(2026, 9, 1, 12, tzinfo=UTC)


async def test_resolution_uses_canonical_yes_no_outcomes() -> None:
    raw_market = {
        "id": "123",
        "question": "Will the tracker launch?",
        "outcomes": ["Yes", "No"],
        "clobTokenIds": ["yes-token", "no-token"],
        "outcomePrices": ["1", "0"],
        "closed": True,
        "closedTime": "2026-09-01T12:00:00Z",
    }
    provider = PolymarketProvider()
    market = provider._market_from_payload(raw_market)
    assert market is not None

    resolution = await provider.resolution(market)
    await provider.aclose()

    assert resolution is not None
    assert resolution.outcome == ResolutionOutcome.YES
    assert resolution.resolved_at == datetime(2026, 9, 1, 12, tzinfo=UTC)


def test_rejects_out_of_range_probability() -> None:
    assert PolymarketProvider._decimal("not-a-number") is None
    assert Decimal("1.2") > Decimal("1")


async def test_recently_resolved_markets_uses_keyset_ordering() -> None:
    raw_market = {
        "id": "newest",
        "question": "Will this have usable history?",
        "outcomes": ["Yes", "No"],
        "clobTokenIds": ["yes-token", "no-token"],
        "closed": True,
        "closedTime": "2026-08-13T12:00:00Z",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/markets/keyset"
        assert request.url.params["closed"] == "true"
        assert request.url.params["order"] == "closedTime"
        assert request.url.params["ascending"] == "false"
        return httpx.Response(200, json={"markets": [raw_market]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = PolymarketProvider(client)
    markets = [
        market async for market in provider.list_recently_resolved_markets(limit=1)
    ]
    await client.aclose()

    assert [market.id for market in markets] == ["polymarket:newest"]


async def test_daily_price_history_requests_daily_fidelity() -> None:
    market = Market(
        provider="polymarket",
        external_id="market-1",
        question="Will this have daily history?",
        market_type=MarketType.BINARY,
        status=MarketStatus.CLOSED,
        yes_outcome_id="yes-token",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/prices-history"
        assert request.url.params["interval"] == "1d"
        assert request.url.params["fidelity"] == "1440"
        return httpx.Response(200, json={"history": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = PolymarketProvider(client)
    snapshots = await provider.price_history(
        market,
        start=datetime(2026, 8, 1, tzinfo=UTC),
        end=datetime(2026, 8, 2, tzinfo=UTC),
        interval="1d",
    )
    await client.aclose()

    assert snapshots == []
