"""Provider-independent transformations and calibration metrics for the dashboard."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

PROBABILITY_BINS = tuple(f"{lower * 10}–{(lower + 1) * 10}%" for lower in range(10))
HORIZON_BINS = ("<24h", "1–7d", "7–30d", "30d+")


@dataclass(frozen=True, slots=True)
class CalibrationMetrics:
    forecasts: int
    markets: int
    brier_score: float
    expected_calibration_error: float
    mean_forecast: float
    observed_frequency: float


def prepare_forecasts(forecasts: pd.DataFrame) -> pd.DataFrame:
    """Derive display dimensions while preserving one row per scored forecast."""
    if forecasts.empty:
        return forecasts.copy()

    prepared = forecasts.copy()
    prepared["observed_at"] = pd.to_datetime(prepared["observed_at"], utc=True)
    prepared["resolved_at"] = pd.to_datetime(prepared["resolved_at"], utc=True)
    prepared["probability_yes"] = pd.to_numeric(prepared["probability_yes"], errors="coerce")
    prepared["outcome_value"] = prepared["outcome"].map({"yes": 1.0, "no": 0.0})
    prepared = prepared.dropna(subset=["probability_yes", "outcome_value"])
    prepared = prepared.loc[prepared["probability_yes"].between(0, 1)].copy()

    prepared["hours_to_resolution"] = (
        prepared["resolved_at"] - prepared["observed_at"]
    ).dt.total_seconds() / 3600
    prepared = prepared.loc[prepared["hours_to_resolution"] > 0].copy()
    prepared["horizon"] = pd.cut(
        prepared["hours_to_resolution"],
        bins=[0, 24, 24 * 7, 24 * 30, np.inf],
        labels=HORIZON_BINS,
        include_lowest=False,
    ).astype(str)

    bin_number = np.minimum((prepared["probability_yes"] * 10).astype(int), 9)
    prepared["probability_bin"] = [PROBABILITY_BINS[number] for number in bin_number]
    prepared["liquidity_proxy"] = prepared["liquidity"].combine_first(
        prepared["open_interest"]
    ).combine_first(prepared["volume"])
    prepared["liquidity_tier"] = _liquidity_tiers(prepared["liquidity_proxy"])
    prepared["brier_component"] = (
        prepared["probability_yes"] - prepared["outcome_value"]
    ) ** 2
    return prepared


def filter_forecasts(
    forecasts: pd.DataFrame,
    *,
    providers: list[str],
    topics: list[str],
    horizons: list[str],
    liquidity_tiers: list[str],
) -> pd.DataFrame:
    """Apply dashboard filter selections to prepared forecast data."""
    filtered = forecasts.loc[forecasts["provider"].isin(providers)].copy()
    filtered = filtered.loc[filtered["horizon"].isin(horizons)]
    filtered = filtered.loc[filtered["liquidity_tier"].isin(liquidity_tiers)]
    if topics:
        filtered = filtered.loc[
            filtered["topics"].apply(
                lambda market_topics: bool(set(_topics(market_topics)).intersection(topics))
            )
        ]
    return filtered


def calibration_metrics(forecasts: pd.DataFrame) -> CalibrationMetrics:
    if forecasts.empty:
        return CalibrationMetrics(0, 0, float("nan"), float("nan"), float("nan"), float("nan"))

    reliability = reliability_table(forecasts)
    total = len(forecasts)
    expected_calibration_error = float(
        (reliability["calibration_gap"].abs() * reliability["forecasts"]).sum() / total
    )
    return CalibrationMetrics(
        forecasts=total,
        markets=forecasts["market_id"].nunique(),
        brier_score=float(forecasts["brier_component"].mean()),
        expected_calibration_error=expected_calibration_error,
        mean_forecast=float(forecasts["probability_yes"].mean()),
        observed_frequency=float(forecasts["outcome_value"].mean()),
    )


def reliability_table(forecasts: pd.DataFrame) -> pd.DataFrame:
    """Aggregate forecast bins and attach Wilson 95% confidence intervals."""
    if forecasts.empty:
        return pd.DataFrame(
            columns=[
                "probability_bin",
                "forecasts",
                "mean_forecast",
                "observed_frequency",
                "calibration_gap",
                "ci_low",
                "ci_high",
            ]
        )

    grouped = (
        forecasts.groupby("probability_bin", observed=True)
        .agg(
            forecasts=("outcome_value", "size"),
            mean_forecast=("probability_yes", "mean"),
            observed_frequency=("outcome_value", "mean"),
        )
        .reindex(PROBABILITY_BINS)
        .dropna(subset=["forecasts"])
        .reset_index()
    )
    grouped["forecasts"] = grouped["forecasts"].astype(int)
    grouped["calibration_gap"] = grouped["observed_frequency"] - grouped["mean_forecast"]
    ci_low, ci_high = _wilson_interval(
        grouped["observed_frequency"].to_numpy(), grouped["forecasts"].to_numpy()
    )
    grouped["ci_low"] = ci_low
    grouped["ci_high"] = ci_high
    return grouped


def topic_summary(forecasts: pd.DataFrame) -> pd.DataFrame:
    if forecasts.empty:
        return pd.DataFrame(columns=["topic", "forecasts", "brier_score", "calibration_gap"])

    topics = forecasts.assign(topic=forecasts["topics"].apply(_topics)).explode("topic")
    return (
        topics.groupby("topic", dropna=False)
        .agg(
            forecasts=("outcome_value", "size"),
            brier_score=("brier_component", "mean"),
            calibration_gap=("outcome_value", lambda values: values.mean()),
            mean_forecast=("probability_yes", "mean"),
        )
        .assign(calibration_gap=lambda table: table["calibration_gap"] - table["mean_forecast"])
        .drop(columns="mean_forecast")
        .sort_values("forecasts", ascending=False)
        .reset_index()
    )


def _liquidity_tiers(liquidity: pd.Series) -> pd.Series:
    tiers = pd.Series("Unknown", index=liquidity.index, dtype="object")
    known = liquidity.dropna()
    if known.empty:
        return tiers
    if known.nunique() == 1:
        tiers.loc[known.index] = "Measured"
        return tiers

    quantile_count = min(4, known.nunique())
    quantiles = pd.qcut(known, q=quantile_count, duplicates="drop")
    labels = ("Low", "Medium", "High", "Very high")[: len(quantiles.cat.categories)]
    category_to_label = dict(zip(quantiles.cat.categories, labels, strict=True))
    tiers.loc[known.index] = [category_to_label[value] for value in quantiles]
    return tiers


def _topics(value: object) -> list[str]:
    if isinstance(value, list):
        return value or ["Uncategorised"]
    if isinstance(value, tuple):
        return list(value) or ["Uncategorised"]
    return ["Uncategorised"]


def _wilson_interval(proportions: np.ndarray, counts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    z = 1.959963984540054
    z_squared = z**2
    denominator = 1 + z_squared / counts
    center = (proportions + z_squared / (2 * counts)) / denominator
    margin = z * np.sqrt(
        (proportions * (1 - proportions) / counts) + (z_squared / (4 * counts**2))
    ) / denominator
    return np.maximum(0, center - margin), np.minimum(1, center + margin)
