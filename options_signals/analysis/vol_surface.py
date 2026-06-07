"""
Volatility term structure, HV cone, and 3D volatility surface.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from utils.helpers import days_to_expiry


@dataclass
class TermPoint:
    expiry: str
    dte_days: float
    atm_iv_pct: float


def compute_term_structure(
    chains_by_expiry: dict[str, pd.DataFrame],
    spot: float,
) -> list[TermPoint]:
    points: list[TermPoint] = []
    for expiry, chain_df in chains_by_expiry.items():
        if chain_df.empty:
            continue
        dte_days = days_to_expiry(expiry) * 365.0
        if dte_days <= 0:
            continue
        atm_idx = (chain_df["strike"] - spot).abs().idxmin()
        atm_strike = float(chain_df.loc[atm_idx, "strike"])
        atm_rows = chain_df[chain_df["strike"] == atm_strike]
        ce_rows = atm_rows[atm_rows["opt_type"] == "CE"]
        pe_rows = atm_rows[atm_rows["opt_type"] == "PE"]
        ce_iv: Optional[float] = float(ce_rows["iv"].iloc[0]) if not ce_rows.empty else None
        pe_iv: Optional[float] = float(pe_rows["iv"].iloc[0]) if not pe_rows.empty else None
        if ce_iv is not None and pe_iv is not None:
            iv_pct = (ce_iv + pe_iv) / 2.0
        elif ce_iv is not None:
            iv_pct = ce_iv
        elif pe_iv is not None:
            iv_pct = pe_iv
        else:
            continue
        if iv_pct <= 0:
            continue
        points.append(TermPoint(expiry=expiry, dte_days=dte_days, atm_iv_pct=iv_pct))
    return sorted(points, key=lambda p: p.dte_days)


def term_structure_fig(points: list[TermPoint]) -> go.Figure:
    def _short_expiry(exp: str) -> str:
        try:
            d = datetime.datetime.strptime(exp, "%Y-%m-%d")
            return d.strftime("%d-%b")
        except ValueError:
            return exp

    colors: list[str] = []
    for p in points:
        if p.atm_iv_pct < 15:
            colors.append("green")
        elif p.atm_iv_pct <= 25:
            colors.append("orange")
        else:
            colors.append("red")

    x = [p.dte_days for p in points]
    y = [p.atm_iv_pct for p in points]
    texts = [_short_expiry(p.expiry) for p in points]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x,
        y=y,
        mode="lines+markers+text",
        text=texts,
        textposition="top center",
        marker=dict(color=colors, size=10),
        line=dict(color="steelblue", width=2),
    ))
    fig.update_layout(
        title="IV Term Structure",
        xaxis_title="DTE (days)",
        yaxis_title="ATM IV (%)",
        template="plotly_dark",
    )
    return fig


def compute_hv_cone(
    closes: pd.Series,
    lookbacks: list[int] = [10, 21, 30, 63],
) -> dict[int, float]:
    if len(closes) < max(lookbacks) + 1:
        return {}
    log_returns = np.log(closes / closes.shift(1)).dropna()
    result: dict[int, float] = {}
    for lb in lookbacks:
        if len(log_returns) < lb:
            continue
        tail = log_returns.iloc[-lb:]
        hv = float(tail.std() * np.sqrt(252) * 100)
        result[lb] = hv
    return result


def hv_cone_fig(hv_dict: dict[int, float], atm_iv_pct: float) -> go.Figure:
    sorted_items = sorted(hv_dict.items())
    x_labels = [f"{k}d" for k, _ in sorted_items]
    y_values = [v for _, v in sorted_items]
    bar_colors = ["green" if v < atm_iv_pct else "red" for v in y_values]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=x_labels,
        y=y_values,
        marker_color=bar_colors,
        name="Historical Volatility",
    ))
    fig.add_hline(
        y=atm_iv_pct,
        line_dash="dash",
        line_color="yellow",
        annotation_text="ATM IV",
        annotation_position="top right",
    )
    fig.update_layout(
        title="Historical Volatility Cone vs ATM IV",
        xaxis_title="Lookback Period",
        yaxis_title="Volatility (%)",
        template="plotly_dark",
    )
    return fig


def compute_vol_surface(
    chains_by_expiry: dict[str, pd.DataFrame],
    spot: float,
    n_strikes: int = 8,
) -> tuple[list, list, list[list]]:
    valid_expiries = [
        exp for exp, df in chains_by_expiry.items()
        if not df.empty and days_to_expiry(exp) * 365 > 0
    ]
    valid_expiries = sorted(valid_expiries, key=lambda e: days_to_expiry(e))

    if not valid_expiries:
        return [], [], []

    first_exp = valid_expiries[0]
    first_df = chains_by_expiry[first_exp]
    sorted_strikes_in_df = sorted(first_df["strike"].unique().tolist())
    if len(sorted_strikes_in_df) >= 2:
        diffs = [
            sorted_strikes_in_df[i + 1] - sorted_strikes_in_df[i]
            for i in range(len(sorted_strikes_in_df) - 1)
        ]
        strike_gap = float(np.median(diffs))
    else:
        strike_gap = 50.0

    atm_idx = (first_df["strike"] - spot).abs().idxmin()
    atm_strike = float(first_df.loc[atm_idx, "strike"])

    half = n_strikes // 2
    candidate_strikes = [atm_strike + (i - half) * strike_gap for i in range(n_strikes)]

    dte_list = [days_to_expiry(exp) * 365.0 for exp in valid_expiries]

    def _nearest_iv(df: pd.DataFrame, target_strike: float) -> float:
        nearest_idx = (df["strike"] - target_strike).abs().idxmin()
        nearest_strike = float(df.loc[nearest_idx, "strike"])
        rows = df[df["strike"] == nearest_strike]
        ce_rows = rows[rows["opt_type"] == "CE"]
        pe_rows = rows[rows["opt_type"] == "PE"]
        ce_iv: Optional[float] = float(ce_rows["iv"].iloc[0]) if not ce_rows.empty else None
        pe_iv: Optional[float] = float(pe_rows["iv"].iloc[0]) if not pe_rows.empty else None
        if ce_iv is not None and pe_iv is not None:
            return (ce_iv + pe_iv) / 2.0
        if ce_iv is not None:
            return ce_iv
        if pe_iv is not None:
            return pe_iv
        return 0.0

    iv_matrix: list[list] = []
    for strike in candidate_strikes:
        row: list[float] = []
        for exp in valid_expiries:
            df = chains_by_expiry[exp]
            iv = _nearest_iv(df, strike)
            row.append(iv)
        iv_matrix.append(row)

    return candidate_strikes, dte_list, iv_matrix


def vol_surface_fig(
    chains_by_expiry: dict[str, pd.DataFrame],
    spot: float,
) -> go.Figure:
    valid_expiries = [
        exp for exp, df in chains_by_expiry.items()
        if not df.empty and days_to_expiry(exp) * 365 > 0
    ]

    if len(valid_expiries) < 2:
        expiry = valid_expiries[0] if valid_expiries else None
        fig = go.Figure()
        if expiry is not None:
            df = chains_by_expiry[expiry]
            ce_df = df[df["opt_type"] == "CE"].sort_values("strike")
            pe_df = df[df["opt_type"] == "PE"].sort_values("strike")
            if not ce_df.empty:
                fig.add_trace(go.Scatter(
                    x=ce_df["strike"].tolist(),
                    y=ce_df["iv"].tolist(),
                    mode="lines+markers",
                    name="CE IV",
                ))
            if not pe_df.empty:
                fig.add_trace(go.Scatter(
                    x=pe_df["strike"].tolist(),
                    y=pe_df["iv"].tolist(),
                    mode="lines+markers",
                    name="PE IV",
                ))
        fig.update_layout(
            title="IV Smile (insufficient expiries for surface)",
            xaxis_title="Strike",
            yaxis_title="IV (%)",
            template="plotly_dark",
            height=500,
        )
        return fig

    strikes_list, dte_list, iv_matrix = compute_vol_surface(chains_by_expiry, spot)

    if not strikes_list or not dte_list:
        fig = go.Figure()
        fig.update_layout(title="Volatility Surface", template="plotly_dark", height=500)
        return fig

    z = np.array(iv_matrix)

    fig = go.Figure(data=[go.Surface(
        x=strikes_list,
        y=dte_list,
        z=z,
        colorscale="RdYlGn_r",
        colorbar=dict(title="IV (%)"),
    )])
    fig.update_layout(
        title="Volatility Surface",
        scene=dict(
            xaxis_title="Strike",
            yaxis_title="DTE (days)",
            zaxis_title="IV (%)",
        ),
        template="plotly_dark",
        height=500,
    )
    return fig
