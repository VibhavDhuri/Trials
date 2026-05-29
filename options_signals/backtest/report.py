"""Backtest report helpers — equity curve, summary formatting."""
from __future__ import annotations

import pandas as pd

try:
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False


def equity_curve_fig(trades_df: pd.DataFrame) -> "go.Figure":
    """Return a Plotly figure of the cumulative P&L equity curve."""
    if not HAS_PLOTLY:
        raise ImportError("plotly is required")
    if trades_df.empty:
        return go.Figure()

    pnl_col = "pnl" if "pnl" in trades_df.columns else "pnl_inr"
    date_col = "exit_date" if "exit_date" in trades_df.columns else trades_df.index

    eq    = trades_df[pnl_col].cumsum().values
    dates = trades_df[date_col].values if isinstance(date_col, str) else date_col

    colors = ["#2ecc71" if p >= 0 else "#e74c3c" for p in trades_df[pnl_col].values]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=eq, mode="lines+markers",
        name="Cumulative P&L (₹)",
        line=dict(color="#3498db", width=2),
        fill="tozeroy",
        fillcolor="rgba(52,152,219,0.10)",
        marker=dict(color=colors, size=8),
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.4)
    fig.update_layout(
        template="plotly_dark",
        title="Backtest Equity Curve (indicative — HV-based, no real options prices)",
        xaxis_title="Exit Date",
        yaxis_title="Cumulative P&L (₹ gross)",
        height=360,
        margin=dict(l=40, r=40, t=40, b=40),
    )
    return fig


def format_summary(summary: dict) -> dict:
    """Format summary dict values as display strings for Streamlit metrics."""
    return {
        "total_trades": summary.get("total_trades", 0),
        "win_rate":     f"{summary.get('win_rate', 0):.1f}%",
        "avg_pnl":      f"₹{summary.get('avg_pnl', 0):+,.0f}",
        "sharpe":       f"{summary.get('sharpe', 0):.3f}",
        "total_pnl":    f"₹{summary.get('total_pnl', 0):+,.0f}",
        "max_drawdown": f"₹{summary.get('max_drawdown', 0):,.0f}",
        "best":         f"₹{summary.get('best', 0):+,.0f}",
        "worst":        f"₹{summary.get('worst', 0):+,.0f}",
    }
