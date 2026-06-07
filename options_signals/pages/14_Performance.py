"""
Performance Analytics — equity curve, monthly P&L heatmap, Sharpe, drawdown.
"""
from __future__ import annotations

import os
import sys
import datetime
import math
from typing import Optional

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import INDICES, IST
from positions.tracker import get_all_positions, Position, realised_pnl
from utils.helpers import now_ist

# ---------------------------------------------------------------------------
# Optional import from reports.performance (may not exist yet)
# ---------------------------------------------------------------------------
try:
    from reports.performance import (  # type: ignore[import]
        PerformanceAnalytics,
        daily_pnl_series,
        cumulative_pnl,
        monthly_pnl_matrix,
        sharpe_ratio,
        sortino_ratio,
        max_drawdown,
        win_rate_by_strategy,
        avg_hold_hours,
        equity_curve_fig,
        monthly_heatmap_fig,
        pnl_histogram_fig,
    )
    _REPORTS_MODULE_AVAILABLE = True
except ImportError:
    _REPORTS_MODULE_AVAILABLE = False

st.set_page_config(page_title="Performance Analytics", page_icon="📊", layout="wide")

client  = st.session_state.get("client")
offline = st.session_state.get("offline", True)

# ===========================================================================
# Inline analytics helpers (used when reports.performance is not available)
# ===========================================================================

def _daily_pnl_series(closed: list[Position]) -> pd.Series:
    """Returns a daily P&L Series indexed by date."""
    if not closed:
        return pd.Series(dtype=float)
    records: list[dict] = []
    for p in closed:
        pnl = realised_pnl(p)
        date_str = (p.exit_time or p.entry_time or "")[:10]
        try:
            date_obj = datetime.date.fromisoformat(date_str)
        except ValueError:
            date_obj = datetime.date.today()
        records.append({"date": date_obj, "pnl": pnl})
    df = pd.DataFrame(records).groupby("date")["pnl"].sum().sort_index()
    return df


def _cumulative_pnl(daily: pd.Series) -> pd.Series:
    return daily.cumsum()


def _sharpe_ratio(daily: pd.Series, risk_free_daily: float = 0.065 / 252) -> float:
    if daily.empty or daily.std() == 0:
        return 0.0
    excess = daily - risk_free_daily
    return float(excess.mean() / excess.std() * math.sqrt(252))


def _sortino_ratio(daily: pd.Series, risk_free_daily: float = 0.065 / 252) -> float:
    if daily.empty:
        return 0.0
    excess = daily - risk_free_daily
    downside = excess[excess < 0]
    if downside.empty or downside.std() == 0:
        return 0.0
    return float(excess.mean() / downside.std() * math.sqrt(252))


def _max_drawdown(cumulative: pd.Series) -> float:
    if cumulative.empty:
        return 0.0
    roll_max = cumulative.cummax()
    drawdown = cumulative - roll_max
    return float(drawdown.min())


def _win_rate_by_strategy(closed: list[Position]) -> pd.Series:
    if not closed:
        return pd.Series(dtype=float)
    records = [
        {"strategy": p.strategy_tag or "Unknown", "pnl": realised_pnl(p)}
        for p in closed
    ]
    df = pd.DataFrame(records)
    return df.groupby("strategy")["pnl"].sum()


def _avg_hold_hours(closed: list[Position]) -> float:
    durations = []
    for p in closed:
        if p.entry_time and p.exit_time:
            try:
                entry_dt = datetime.datetime.fromisoformat(p.entry_time)
                exit_dt  = datetime.datetime.fromisoformat(p.exit_time)
                diff_h   = (exit_dt - entry_dt).total_seconds() / 3600.0
                if diff_h >= 0:
                    durations.append(diff_h)
            except ValueError:
                pass
    return float(np.mean(durations)) if durations else 0.0


def _equity_curve_fig(cumulative: pd.Series) -> go.Figure:
    fig = go.Figure()
    if cumulative.empty:
        fig.update_layout(title="Equity Curve — No Data", template="plotly_dark")
        return fig
    colour = "#4fc3f7"
    fig.add_trace(go.Scatter(
        x=cumulative.index.astype(str),
        y=cumulative.values,
        mode="lines",
        name="Cumulative P&L",
        line=dict(color=colour, width=2),
        fill="tozeroy",
        fillcolor="rgba(79, 195, 247, 0.1)",
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(
        title="Equity Curve — Cumulative P&L (₹)",
        xaxis_title="Date",
        yaxis_title="Cumulative P&L (₹)",
        template="plotly_dark",
        height=380,
    )
    return fig


def _monthly_heatmap_fig(daily: pd.Series) -> go.Figure:
    fig = go.Figure()
    if daily.empty:
        fig.update_layout(title="Monthly P&L Heatmap — No Data", template="plotly_dark")
        return fig
    df = daily.reset_index()
    df.columns = ["date", "pnl"]
    df["year"]  = pd.to_datetime(df["date"]).dt.year
    df["month"] = pd.to_datetime(df["date"]).dt.month
    monthly = df.groupby(["year", "month"])["pnl"].sum().reset_index()
    pivot = monthly.pivot(index="year", columns="month", values="pnl").fillna(0.0)
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    pivot.columns = [month_names[m - 1] for m in pivot.columns]
    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=list(pivot.columns),
        y=[str(y) for y in pivot.index],
        colorscale="RdYlGn",
        showscale=True,
        colorbar=dict(title="P&L (₹)"),
        text=[[f"₹{v:+,.0f}" for v in row] for row in pivot.values],
        texttemplate="%{text}",
    ))
    fig.update_layout(
        title="Monthly P&L Heatmap",
        xaxis_title="Month",
        yaxis_title="Year",
        template="plotly_dark",
        height=280,
    )
    return fig


def _pnl_histogram_fig(closed: list[Position]) -> go.Figure:
    fig = go.Figure()
    if not closed:
        fig.update_layout(title="P&L Distribution — No Data", template="plotly_dark")
        return fig
    pnls = [realised_pnl(p) for p in closed]
    colours = ["#4fc3f7" if v >= 0 else "#ef5350" for v in pnls]
    fig.add_trace(go.Histogram(
        x=pnls,
        nbinsx=20,
        marker_color="#4fc3f7",
        name="P&L",
    ))
    fig.add_vline(x=0, line_dash="dash", line_color="gray")
    fig.update_layout(
        title="P&L Distribution",
        xaxis_title="P&L per Trade (₹)",
        yaxis_title="Frequency",
        template="plotly_dark",
        height=320,
    )
    return fig


# ---------------------------------------------------------------------------
# Sidebar — date range
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("📊 Performance Analytics")
    today = now_ist().date()
    start_date = st.date_input(
        "From Date",
        value=today - datetime.timedelta(days=365),
        key="perf_start_date",
    )
    end_date = st.date_input(
        "To Date",
        value=today,
        key="perf_end_date",
    )
    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
st.title("📊 Performance Analytics")
st.markdown("Equity curve, drawdown, monthly heatmap, and trade statistics.")
st.divider()

# ---------------------------------------------------------------------------
# Load positions and filter
# ---------------------------------------------------------------------------
all_positions = get_all_positions()
closed_positions = [
    p for p in all_positions
    if p.status == "CLOSED" and p.exit_price is not None
]

# Filter by date range
def _exit_date(p: Position) -> Optional[datetime.date]:
    raw = p.exit_time or p.entry_time or ""
    try:
        return datetime.date.fromisoformat(raw[:10])
    except ValueError:
        return None


closed_in_range = [
    p for p in closed_positions
    if (d := _exit_date(p)) is not None
    and start_date <= d <= end_date
]

if len(closed_in_range) < 2:
    st.info(
        "No trade history yet (or fewer than 2 closed positions in the selected range). "
        "Close some positions to see performance analytics."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Compute metrics
# ---------------------------------------------------------------------------
if _REPORTS_MODULE_AVAILABLE:
    # Use module functions if available
    daily_s   = daily_pnl_series(closed_in_range)          # type: ignore[call-arg]
    cum_s     = cumulative_pnl(daily_s)                     # type: ignore[call-arg]
    sharpe    = sharpe_ratio(daily_s)                        # type: ignore[call-arg]
    sortino   = sortino_ratio(daily_s)                       # type: ignore[call-arg]
    drawdown  = max_drawdown(cum_s)                          # type: ignore[call-arg]
    strat_pnl = win_rate_by_strategy(closed_in_range)       # type: ignore[call-arg]
    hold_h    = avg_hold_hours(closed_in_range)              # type: ignore[call-arg]
    fig_eq    = equity_curve_fig(cum_s)                      # type: ignore[call-arg]
    fig_mh    = monthly_heatmap_fig(daily_s)                 # type: ignore[call-arg]
    fig_hist  = pnl_histogram_fig(closed_in_range)           # type: ignore[call-arg]
else:
    daily_s   = _daily_pnl_series(closed_in_range)
    cum_s     = _cumulative_pnl(daily_s)
    sharpe    = _sharpe_ratio(daily_s)
    sortino   = _sortino_ratio(daily_s)
    drawdown  = _max_drawdown(cum_s)
    strat_pnl = _win_rate_by_strategy(closed_in_range)
    hold_h    = _avg_hold_hours(closed_in_range)
    fig_eq    = _equity_curve_fig(cum_s)
    fig_mh    = _monthly_heatmap_fig(daily_s)
    fig_hist  = _pnl_histogram_fig(closed_in_range)

total_pnl  = float(cum_s.iloc[-1]) if not cum_s.empty else 0.0
winners    = [p for p in closed_in_range if realised_pnl(p) > 0]
losers     = [p for p in closed_in_range if realised_pnl(p) <= 0]
win_rate   = len(winners) / len(closed_in_range) * 100 if closed_in_range else 0.0

# ---------------------------------------------------------------------------
# Key metrics strip
# ---------------------------------------------------------------------------
st.subheader("Key Metrics")
m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Total P&L ₹", f"₹{total_pnl:+,.2f}",
          delta_color="normal" if total_pnl >= 0 else "inverse")
m2.metric("Sharpe Ratio",  f"{sharpe:.2f}")
m3.metric("Sortino Ratio", f"{sortino:.2f}")
m4.metric("Max Drawdown",  f"₹{drawdown:,.2f}")
m5.metric("Win Rate",      f"{win_rate:.1f}%")
m6.metric("Avg Hold (hrs)", f"{hold_h:.1f}h")

st.divider()

# ---------------------------------------------------------------------------
# Equity Curve
# ---------------------------------------------------------------------------
st.subheader("Equity Curve")
st.plotly_chart(fig_eq, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Monthly P&L Heatmap
# ---------------------------------------------------------------------------
st.subheader("Monthly P&L Heatmap")
st.plotly_chart(fig_mh, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Strategy P&L bar chart + P&L Distribution histogram
# ---------------------------------------------------------------------------
left_col, right_col = st.columns(2)

with left_col:
    st.subheader("Strategy P&L")
    if strat_pnl.empty:
        st.info("No strategy-tagged trades yet.")
    else:
        colours_bar = [
            "#4caf50" if v >= 0 else "#ef5350"
            for v in strat_pnl.values
        ]
        fig_bar = go.Figure(go.Bar(
            x=strat_pnl.index.tolist(),
            y=strat_pnl.values.tolist(),
            marker_color=colours_bar,
            name="Strategy P&L",
        ))
        fig_bar.add_hline(y=0, line_dash="dash", line_color="gray")
        fig_bar.update_layout(
            title="Realised P&L by Strategy",
            xaxis_title="Strategy Tag",
            yaxis_title="Total P&L (₹)",
            template="plotly_dark",
            height=320,
        )
        st.plotly_chart(fig_bar, use_container_width=True)

with right_col:
    st.subheader("P&L Distribution")
    st.plotly_chart(fig_hist, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Best 3 / Worst 3 Trades
# ---------------------------------------------------------------------------
best_col, worst_col = st.columns(2)

sorted_by_pnl = sorted(
    closed_in_range,
    key=lambda p: realised_pnl(p),
    reverse=True,
)

def _trade_label(p: Position) -> str:
    tag = f" [{p.strategy_tag}]" if p.strategy_tag else ""
    return f"{p.symbol} {p.opt_type} {p.strike}{tag}"


with best_col:
    st.subheader("Best 3 Trades")
    best_3 = sorted_by_pnl[:3]
    if not best_3:
        st.info("No closed trades.")
    for p in best_3:
        pnl_val = realised_pnl(p)
        st.markdown(
            f'<div style="padding:6px 12px; border-left:3px solid #4caf50; margin:4px 0;">'
            f'<b>{_trade_label(p)}</b><br>'
            f'<span style="color:#4caf50; font-size:1.1em; font-weight:bold;">'
            f'₹{pnl_val:+,.2f}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

with worst_col:
    st.subheader("Worst 3 Trades")
    worst_3 = sorted_by_pnl[-3:][::-1]
    if not worst_3:
        st.info("No closed trades.")
    for p in worst_3:
        pnl_val = realised_pnl(p)
        st.markdown(
            f'<div style="padding:6px 12px; border-left:3px solid #ef5350; margin:4px 0;">'
            f'<b>{_trade_label(p)}</b><br>'
            f'<span style="color:#ef5350; font-size:1.1em; font-weight:bold;">'
            f'₹{pnl_val:+,.2f}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

st.divider()
st.caption(
    f"Showing {len(closed_in_range)} closed position(s) from "
    f"{start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')}. "
    "All P&L figures are gross (before brokerage/taxes)."
)
