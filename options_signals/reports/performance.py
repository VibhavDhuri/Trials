"""
Trading performance analytics — Sharpe, Sortino, drawdown, monthly heatmap.
"""
from __future__ import annotations

import datetime
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from positions.tracker import Position, realised_pnl

_MONTH_LABELS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def daily_pnl_series(positions: list[Any]) -> pd.Series:
    records: list[tuple[datetime.date, float]] = []
    for pos in positions:
        if pos.status != "CLOSED" or pos.exit_time is None:
            continue
        try:
            exit_date = datetime.date.fromisoformat(pos.exit_time[:10])
        except ValueError:
            continue
        records.append((exit_date, realised_pnl(pos)))

    if not records:
        return pd.Series(dtype=float)

    df = pd.DataFrame(records, columns=["date", "pnl"])
    series = df.groupby("date")["pnl"].sum()
    series.index = pd.to_datetime(series.index)
    series = series.sort_index()
    return series


def cumulative_pnl(daily: pd.Series) -> pd.Series:
    return daily.cumsum()


def monthly_pnl_matrix(daily: pd.Series) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame()
    df = daily.to_frame(name="pnl")
    df["year"] = df.index.year
    df["month"] = df.index.month
    pivot = df.groupby(["year", "month"])["pnl"].sum().unstack(level=0)
    pivot.index = [_MONTH_LABELS[m - 1] for m in pivot.index]
    return pivot


def sharpe_ratio(daily: pd.Series, rf_daily: float = 0.065 / 252) -> float:
    if daily.empty or daily.std() == 0:
        return 0.0
    return float((daily.mean() - rf_daily) / daily.std())


def sortino_ratio(daily: pd.Series, rf_daily: float = 0.065 / 252) -> float:
    if daily.empty:
        return 0.0
    negative = daily[daily < 0]
    if negative.empty or negative.std() == 0:
        return 0.0
    return float((daily.mean() - rf_daily) / negative.std())


def max_drawdown(cum: pd.Series) -> float:
    if cum.empty:
        return 0.0
    rolling_max = cum.cummax()
    drawdown = cum - rolling_max
    return float(drawdown.min() / rolling_max.max()) if rolling_max.max() != 0 else 0.0


def win_rate_by_strategy(positions: list[Any]) -> dict[str, float]:
    buckets: dict[str, list[float]] = {}
    for pos in positions:
        if pos.status != "CLOSED":
            continue
        tag = pos.strategy_tag or "untagged"
        pnl = realised_pnl(pos)
        buckets.setdefault(tag, []).append(pnl)
    result: dict[str, float] = {}
    for tag, pnls in buckets.items():
        if not pnls:
            result[tag] = 0.0
        else:
            result[tag] = sum(1 for p in pnls if p > 0) / len(pnls)
    return result


def avg_hold_hours(positions: list[Any]) -> float:
    durations: list[float] = []
    for pos in positions:
        if pos.status != "CLOSED" or pos.exit_time is None or pos.entry_time is None:
            continue
        try:
            entry = datetime.datetime.fromisoformat(pos.entry_time)
            exit_ = datetime.datetime.fromisoformat(pos.exit_time)
            delta = (exit_ - entry).total_seconds() / 3600
            if delta >= 0:
                durations.append(delta)
        except ValueError:
            continue
    return float(np.mean(durations)) if durations else 0.0


def equity_curve_fig(cum: pd.Series) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=cum.index,
            y=cum.values,
            mode="lines",
            name="Equity Curve",
            line={"color": "#00d4aa", "width": 2},
        )
    )
    fig.update_layout(
        template="plotly_dark",
        title="Cumulative P&L",
        xaxis_title="Date",
        yaxis_title="P&L (INR)",
        margin={"l": 50, "r": 20, "t": 40, "b": 40},
    )
    return fig


def monthly_heatmap_fig(matrix: pd.DataFrame) -> go.Figure:
    if matrix.empty:
        fig = go.Figure()
        fig.update_layout(template="plotly_dark", title="Monthly P&L Heatmap")
        return fig

    z_vals = matrix.values.tolist()
    years = [str(c) for c in matrix.columns.tolist()]
    months = matrix.index.tolist()

    text_vals = [
        [f"₹{v:,.0f}" if not np.isnan(v) else "" for v in row]
        for row in matrix.values
    ]

    fig = go.Figure(
        data=go.Heatmap(
            z=z_vals,
            x=years,
            y=months,
            colorscale="RdYlGn",
            text=text_vals,
            texttemplate="%{text}",
            showscale=True,
        )
    )
    fig.update_layout(
        template="plotly_dark",
        title="Monthly P&L Heatmap",
        margin={"l": 60, "r": 20, "t": 40, "b": 40},
    )
    return fig


def pnl_histogram_fig(daily: pd.Series) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=daily.values,
            nbinsx=30,
            name="Daily P&L",
            marker_color="#636efa",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        title="Daily P&L Distribution",
        xaxis_title="P&L (INR)",
        yaxis_title="Count",
        margin={"l": 50, "r": 20, "t": 40, "b": 40},
    )
    return fig
