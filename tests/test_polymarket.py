from datetime import UTC, datetime
from decimal import Decimal

from prediction_market_tracker.domain import MarketType, ResolutionOutcome
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
