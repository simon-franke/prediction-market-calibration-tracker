import pandas as pd

from prediction_market_tracker.dashboard.analytics import (
    calibration_metrics,
    filter_forecasts,
    prepare_forecasts,
    reliability_table,
    topic_summary,
)
from prediction_market_tracker.dashboard.data import _sync_url


def _forecasts() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "market_id": "polymarket:one",
                "question": "Will one happen?",
                "provider": "polymarket",
                "topics": ["Politics"],
                "observed_at": "2026-08-01T00:00:00Z",
                "probability_yes": 0.7,
                "volume": 100.0,
                "open_interest": None,
                "liquidity": 50.0,
                "outcome": "yes",
                "resolved_at": "2026-08-03T00:00:00Z",
            },
            {
                "market_id": "polymarket:two",
                "question": "Will two happen?",
                "provider": "polymarket",
                "topics": [],
                "observed_at": "2026-08-02T00:00:00Z",
                "probability_yes": 1.0,
                "volume": 10.0,
                "open_interest": None,
                "liquidity": None,
                "outcome": "no",
                "resolved_at": "2026-08-02T12:00:00Z",
            },
            {
                "market_id": "kalshi:three",
                "question": "Will three happen?",
                "provider": "kalshi",
                "topics": ["Economy"],
                "observed_at": "2026-07-01T00:00:00Z",
                "probability_yes": 0.2,
                "volume": None,
                "open_interest": 20.0,
                "liquidity": None,
                "outcome": "no",
                "resolved_at": "2026-09-01T00:00:00Z",
            },
        ]
    )


def test_prepare_forecasts_derives_scoreable_segments() -> None:
    prepared = prepare_forecasts(_forecasts())

    assert prepared["probability_bin"].tolist() == ["70–80%", "90–100%", "20–30%"]
    assert prepared["horizon"].tolist() == ["1–7d", "<24h", "30d+"]
    assert prepared["outcome_value"].tolist() == [1.0, 0.0, 0.0]
    assert prepared["liquidity_proxy"].tolist() == [50.0, 10.0, 20.0]


def test_reliability_and_aggregate_metrics_are_calculated() -> None:
    prepared = prepare_forecasts(_forecasts())

    reliability = reliability_table(prepared)
    metrics = calibration_metrics(prepared)

    assert reliability["probability_bin"].tolist() == ["20–30%", "70–80%", "90–100%"]
    assert metrics.forecasts == 3
    assert metrics.markets == 3
    assert round(metrics.brier_score, 3) == 0.377
    assert round(metrics.expected_calibration_error, 3) == 0.5


def test_filters_match_topics_and_selected_dimensions() -> None:
    prepared = prepare_forecasts(_forecasts())

    filtered = filter_forecasts(
        prepared,
        providers=["polymarket"],
        topics=["Politics"],
        horizons=["1–7d"],
        liquidity_tiers=prepared["liquidity_tier"].unique().tolist(),
    )

    assert filtered["market_id"].tolist() == ["polymarket:one"]
    assert topic_summary(prepared)["topic"].tolist() == ["Economy", "Politics", "Uncategorised"]


def test_dashboard_database_url_uses_sync_postgres_driver() -> None:
    assert _sync_url("postgresql://user:password@db.example/tracker").startswith(
        "postgresql+psycopg://"
    )
