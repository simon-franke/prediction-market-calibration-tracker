"""Streamlit application for exploring prediction-market calibration."""

import logging
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from prediction_market_tracker.dashboard.analytics import (
    HORIZON_BINS,
    calibration_metrics,
    filter_forecasts,
    prepare_forecasts,
    reliability_table,
    topic_summary,
)
from prediction_market_tracker.dashboard.data import load_resolved_forecasts

logger = logging.getLogger(__name__)


@st.cache_data(ttl=60, show_spinner="Loading resolved forecasts…")
def _load_forecasts(
    database_url: str | None,
    supabase_url: str | None,
    supabase_service_role_key: str | None,
) -> pd.DataFrame:
    return prepare_forecasts(
        load_resolved_forecasts(
            database_url,
            supabase_url=supabase_url,
            supabase_service_role_key=supabase_service_role_key,
        )
    )


def _setting(name: str) -> str | None:
    """Read a setting from the environment or Streamlit Cloud secrets."""
    if value := os.environ.get(name):
        return value

    try:
        return st.secrets.get(name)
    except FileNotFoundError:
        return None


def render() -> None:
    st.set_page_config(page_title="Market Calibration", page_icon="◎", layout="wide")
    st.title("Prediction Market Calibration")
    st.caption("When the market says 70%, how often does it happen?")

    database_url = _setting("DATABASE_URL")
    supabase_url = _setting("SUPABASE_URL")
    supabase_service_role_key = _setting("SUPABASE_SERVICE_ROLE_KEY")
    if not database_url and not (supabase_url and supabase_service_role_key):
        st.error("Set DATABASE_URL or Supabase API credentials before starting the dashboard.")
        st.stop()

    try:
        forecasts = _load_forecasts(database_url, supabase_url, supabase_service_role_key)
    except Exception as error:
        logger.exception("dashboard data load failed")
        st.error(
            "The dashboard could not load its data. Check its database or Supabase credentials."
        )
        st.caption(f"Error: {error}")
        st.stop()

    if forecasts.empty:
        st.info(
            "No resolved binary forecasts yet. The dashboard will populate after markets resolve."
        )
        return

    filtered = _render_filters(forecasts)
    if filtered.empty:
        st.warning("No forecasts match the selected filters.")
        return

    metrics = calibration_metrics(filtered)
    _render_metrics(metrics)
    _render_reliability_chart(filtered)
    _render_segment_views(filtered)
    _render_market_explorer(filtered)
    _render_methodology()


def _render_filters(forecasts: pd.DataFrame) -> pd.DataFrame:
    all_providers = sorted(forecasts["provider"].dropna().unique().tolist())
    all_topics = sorted(
        {
            topic
            for market_topics in forecasts["topics"]
            for topic in (
                market_topics
                if isinstance(market_topics, list) and market_topics
                else ["Uncategorised"]
            )
        }
    )
    all_horizons = [horizon for horizon in HORIZON_BINS if horizon in forecasts["horizon"].unique()]
    all_liquidity_tiers = [
        tier
        for tier in ("Low", "Medium", "High", "Very high", "Measured", "Unknown")
        if tier in forecasts["liquidity_tier"].unique()
    ]

    with st.sidebar:
        st.header("Filters")
        providers = st.multiselect("Provider", all_providers, default=all_providers)
        topics = st.multiselect("Topic", all_topics)
        horizons = st.multiselect("Time to resolution", all_horizons, default=all_horizons)
        liquidity_tiers = st.multiselect(
            "Liquidity tier", all_liquidity_tiers, default=all_liquidity_tiers
        )
        if st.button("Refresh data", use_container_width=True):
            _load_forecasts.clear()
            st.rerun()

        latest_snapshot = forecasts["observed_at"].max()
        st.caption(f"Latest scored forecast: {latest_snapshot:%Y-%m-%d %H:%M UTC}")

    return filter_forecasts(
        forecasts,
        providers=providers,
        topics=topics,
        horizons=horizons,
        liquidity_tiers=liquidity_tiers,
    )


def _render_metrics(metrics: object) -> None:
    columns = st.columns(4)
    columns[0].metric("Brier score", f"{metrics.brier_score:.3f}", help="Lower is better.")
    columns[1].metric("Calibration error", f"{metrics.expected_calibration_error:.3f}")
    columns[2].metric("Scored forecasts", f"{metrics.forecasts:,}")
    columns[3].metric("Resolved markets", f"{metrics.markets:,}")

    st.caption(
        f"Mean forecast: {metrics.mean_forecast:.1%} · Observed frequency: "
        f"{metrics.observed_frequency:.1%}"
    )


def _render_reliability_chart(forecasts: pd.DataFrame) -> None:
    st.subheader("Reliability")
    reliability = reliability_table(forecasts)
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=[0, 1],
            y=[0, 1],
            mode="lines",
            line={"dash": "dash", "color": "#94a3b8"},
            name="Perfect calibration",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=reliability["mean_forecast"],
            y=reliability["observed_frequency"],
            mode="markers+lines",
            marker={"size": reliability["forecasts"].clip(lower=8) ** 0.5 * 3, "color": "#2563eb"},
            error_y={
                "type": "data",
                "symmetric": False,
                "array": reliability["ci_high"] - reliability["observed_frequency"],
                "arrayminus": reliability["observed_frequency"] - reliability["ci_low"],
            },
            text=[
                f"{row.probability_bin}<br>{row.forecasts:,} forecasts"
                for row in reliability.itertuples()
            ],
            hovertemplate="%{text}<br>Forecast: %{x:.1%}<br>Observed: %{y:.1%}<extra></extra>",
            name="Observed outcome rate",
        )
    )
    figure.update_layout(
        height=440,
        xaxis={"title": "Mean market probability", "tickformat": ".0%", "range": [0, 1]},
        yaxis={"title": "Observed frequency", "tickformat": ".0%", "range": [0, 1]},
        legend={"orientation": "h", "y": 1.12},
        margin={"t": 20, "r": 20, "b": 20, "l": 20},
    )
    st.plotly_chart(figure, use_container_width=True)
    st.caption("Points show 95% Wilson confidence intervals; larger points contain more forecasts.")


def _render_segment_views(forecasts: pd.DataFrame) -> None:
    left, right = st.columns(2)
    with left:
        st.subheader("By time to resolution")
        horizon_summary = (
            forecasts.groupby("horizon", observed=True)
            .agg(forecasts=("market_id", "size"), brier_score=("brier_component", "mean"))
            .reindex(HORIZON_BINS)
            .dropna()
            .reset_index()
        )
        figure = px.bar(
            horizon_summary,
            x="horizon",
            y="brier_score",
            text="forecasts",
            labels={"horizon": "Time remaining", "brier_score": "Brier score"},
            color_discrete_sequence=["#7c3aed"],
        )
        figure.update_traces(texttemplate="%{text:,}", textposition="outside")
        figure.update_layout(
            height=340,
            showlegend=False,
            margin={"t": 20, "r": 20, "b": 20, "l": 20},
        )
        st.plotly_chart(figure, use_container_width=True)

    with right:
        st.subheader("By topic")
        topics = topic_summary(forecasts).head(10)
        figure = px.bar(
            topics.sort_values("brier_score"),
            x="brier_score",
            y="topic",
            orientation="h",
            text="forecasts",
            labels={"brier_score": "Brier score", "topic": "Topic"},
            color_discrete_sequence=["#0f766e"],
        )
        figure.update_traces(texttemplate="%{text:,}", textposition="outside")
        figure.update_layout(
            height=340,
            showlegend=False,
            margin={"t": 20, "r": 20, "b": 20, "l": 20},
        )
        st.plotly_chart(figure, use_container_width=True)


def _render_market_explorer(forecasts: pd.DataFrame) -> None:
    st.subheader("Market explorer")
    market_options = (
        forecasts[["market_id", "question"]]
        .drop_duplicates()
        .sort_values("question")
        .assign(label=lambda table: table["question"] + " · " + table["market_id"])
    )
    selected_label = st.selectbox("Resolved market", market_options["label"].tolist())
    market_id = market_options.loc[market_options["label"] == selected_label, "market_id"].iloc[0]
    market = forecasts.loc[forecasts["market_id"] == market_id].sort_values("observed_at")
    final_outcome = market["outcome_value"].iloc[0]

    figure = px.line(
        market,
        x="observed_at",
        y="probability_yes",
        labels={"observed_at": "Forecast time", "probability_yes": "Yes probability"},
    )
    figure.add_hline(
        y=final_outcome,
        line_dash="dash",
        line_color="#16a34a" if final_outcome else "#dc2626",
        annotation_text="Resolved Yes" if final_outcome else "Resolved No",
    )
    figure.update_yaxes(range=[0, 1], tickformat=".0%")
    figure.update_layout(height=360, margin={"t": 20, "r": 20, "b": 20, "l": 20})
    st.plotly_chart(figure, use_container_width=True)


def _render_methodology() -> None:
    with st.expander("Methodology"):
        st.write(
            "Each point is a stored binary-market snapshot scored against its final resolution. "
            "Brier score is the mean squared forecast error (lower is better). Expected "
            "calibration error is the sample-weighted distance between forecast and observed "
            "frequency across ten probability bins. Liquidity uses the provider-reported "
            "liquidity, then open interest, then volume when liquidity is unavailable."
        )


def main() -> None:
    """Console-script entry point for ``calibration-dashboard``."""
    from streamlit.web import cli as streamlit_cli

    sys.argv = ["streamlit", "run", str(Path(__file__).resolve()), *sys.argv[1:]]
    raise SystemExit(streamlit_cli.main())


if __name__ == "__main__":
    render()
