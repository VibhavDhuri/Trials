"""
Options flow analysis — detects unusual OI activity, large block prints, and institutional signals.
High OI spikes in a single strike often indicate institutional positioning.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import plotly.graph_objects as go


@dataclass
class FlowSignal:
    strike: float
    opt_type: str
    oi: float
    oi_chg: float
    oi_chg_pct: float
    volume: float
    vol_oi_ratio: float
    ltp: float
    signal_type: str
    strength: str
    description: str


def _safe_col(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(default)
    return pd.Series(default, index=df.index)


def _compute_strength(oi_chg_pct: float, vol_oi_ratio: float) -> str:
    if abs(oi_chg_pct) > 30 or vol_oi_ratio > 0.5:
        return "STRONG"
    if abs(oi_chg_pct) > 15 or vol_oi_ratio > 0.3:
        return "MODERATE"
    return "WEAK"


def _build_description(strike: float, opt_type: str, oi_chg: float, oi_chg_pct: float, vol_oi_ratio: float, signal_type: str) -> str:
    chg_sign = "+" if oi_chg >= 0 else ""
    base = f"{opt_type} {strike:.0f}: OI {chg_sign}{oi_chg:,.0f} ({chg_sign}{oi_chg_pct:.1f}%), vol/OI {vol_oi_ratio:.2f}"
    hints = {
        "OI_BUILDUP": "fresh positioning",
        "OI_UNWINDING": "position exit",
        "HIGH_VOLUME": "elevated activity",
        "PUT_WRITING": "put writing (bullish bias)",
        "CALL_WRITING": "call writing (bearish bias)",
        "UNUSUAL_ACTIVITY": "unusual institutional activity",
    }
    hint = hints.get(signal_type, signal_type.lower().replace("_", " "))
    return f"{base} — possible {hint}"


def detect_flow_signals(chain_df: pd.DataFrame, spot: float, top_n: int = 10) -> list[FlowSignal]:
    if chain_df is None or chain_df.empty:
        return []

    df = chain_df.copy()

    strike_col = _safe_col(df, "strike")
    opt_type_col = df["opt_type"] if "opt_type" in df.columns else pd.Series("", index=df.index)
    oi_col = _safe_col(df, "oi")
    oi_chg_col = _safe_col(df, "oi_chg")
    volume_col = _safe_col(df, "volume")
    ltp_col = _safe_col(df, "ltp")

    if "oi_chg_pct" in df.columns:
        oi_chg_pct_col = pd.to_numeric(df["oi_chg_pct"], errors="coerce").fillna(0.0)
    else:
        oi_chg_pct_col = oi_chg_col.copy()
        mask = oi_col != 0
        oi_chg_pct_col[mask] = (oi_chg_col[mask] / (oi_col[mask] - oi_chg_col[mask]).replace(0, np.nan)) * 100
        oi_chg_pct_col = oi_chg_pct_col.fillna(0.0)

    if "vol_oi_ratio" in df.columns:
        vol_oi_ratio_col = pd.to_numeric(df["vol_oi_ratio"], errors="coerce").fillna(0.0)
    else:
        vol_oi_ratio_col = volume_col.copy()
        mask = oi_col != 0
        vol_oi_ratio_col[mask] = volume_col[mask] / oi_col[mask]
        vol_oi_ratio_col[~mask] = 0.0
        vol_oi_ratio_col = vol_oi_ratio_col.fillna(0.0)

    active_mask = ~((oi_col == 0) & (volume_col == 0))
    df = df[active_mask].copy()

    indices = df.index.tolist()
    signals: list[FlowSignal] = []

    for idx in indices:
        strike = float(strike_col[idx])
        opt_type = str(opt_type_col[idx]).upper()
        oi = float(oi_col[idx])
        oi_chg = float(oi_chg_col[idx])
        oi_chg_pct = float(oi_chg_pct_col[idx])
        volume = float(volume_col[idx])
        vol_oi_ratio = float(vol_oi_ratio_col[idx])
        ltp = float(ltp_col[idx])

        signal_type: str | None = None

        if vol_oi_ratio > 0.5 and oi_chg_pct > 20:
            signal_type = "UNUSUAL_ACTIVITY"
        elif opt_type == "PE" and oi_chg > 0 and oi_chg_pct > 10 and strike < spot:
            signal_type = "PUT_WRITING"
        elif opt_type == "CE" and oi_chg > 0 and oi_chg_pct > 10 and strike > spot:
            signal_type = "CALL_WRITING"
        elif oi_chg > 0 and oi_chg_pct > 10:
            signal_type = "OI_BUILDUP"
        elif oi_chg < 0 and abs(oi_chg_pct) > 10:
            signal_type = "OI_UNWINDING"
        elif vol_oi_ratio > 0.3:
            signal_type = "HIGH_VOLUME"

        if signal_type is None:
            continue

        strength = _compute_strength(oi_chg_pct, vol_oi_ratio)
        description = _build_description(strike, opt_type, oi_chg, oi_chg_pct, vol_oi_ratio, signal_type)

        signals.append(FlowSignal(
            strike=strike,
            opt_type=opt_type,
            oi=oi,
            oi_chg=oi_chg,
            oi_chg_pct=oi_chg_pct,
            volume=volume,
            vol_oi_ratio=vol_oi_ratio,
            ltp=ltp,
            signal_type=signal_type,
            strength=strength,
            description=description,
        ))

    signals.sort(key=lambda s: abs(s.oi_chg), reverse=True)
    return signals[:top_n]


def flow_summary(signals: list[FlowSignal]) -> dict:
    bullish = 0
    bearish = 0
    top_strikes: list[str] = []

    for sig in signals:
        if sig.signal_type in ("PUT_WRITING",) or (
            sig.signal_type == "OI_BUILDUP" and sig.opt_type == "PE"
        ):
            bullish += 1
        elif sig.signal_type in ("CALL_WRITING",) or (
            sig.signal_type == "OI_BUILDUP" and sig.opt_type == "CE"
        ):
            bearish += 1
        top_strikes.append(f"{sig.opt_type} {sig.strike:.0f}")

    if bullish > bearish:
        net_bias = "BULLISH"
    elif bearish > bullish:
        net_bias = "BEARISH"
    else:
        net_bias = "NEUTRAL"

    return {
        "bullish_signals": bullish,
        "bearish_signals": bearish,
        "net_bias": net_bias,
        "top_strikes": top_strikes,
    }


_BULLISH_SIGNALS = {"PUT_WRITING"}
_BEARISH_SIGNALS = {"CALL_WRITING"}
_UNUSUAL_SIGNALS = {"UNUSUAL_ACTIVITY"}


def _row_color(signal_type: str) -> str:
    if signal_type in _BULLISH_SIGNALS:
        return "rgba(0, 180, 80, 0.25)"
    if signal_type in _BEARISH_SIGNALS:
        return "rgba(220, 50, 50, 0.25)"
    if signal_type in _UNUSUAL_SIGNALS:
        return "rgba(220, 200, 0, 0.25)"
    return "rgba(60, 60, 80, 0.3)"


def flow_table_fig(signals: list[FlowSignal]) -> go.Figure:
    if not signals:
        fig = go.Figure()
        fig.update_layout(
            template="plotly_dark",
            height=400,
            paper_bgcolor="#1a1a2e",
            annotations=[{
                "text": "No flow signals detected",
                "xref": "paper", "yref": "paper",
                "x": 0.5, "y": 0.5,
                "showarrow": False,
                "font": {"color": "#aaaaaa", "size": 16},
            }],
        )
        return fig

    strikes = [f"{s.strike:.0f}" for s in signals]
    opt_types = [s.opt_type for s in signals]
    oi_chgs = [f"{s.oi_chg:+,.0f}" for s in signals]
    oi_chg_pcts = [f"{s.oi_chg_pct:+.1f}%" for s in signals]
    vol_oi_ratios = [f"{s.vol_oi_ratio:.2f}" for s in signals]
    ltps = [f"{s.ltp:.2f}" for s in signals]
    signal_types = [s.signal_type for s in signals]
    strengths = [s.strength for s in signals]

    fill_colors = [_row_color(s.signal_type) for s in signals]

    header_fill = "rgba(30, 30, 50, 0.95)"
    header_font_color = "#e0e0e0"
    cell_font_color = "#d0d0d0"

    fig = go.Figure(data=[go.Table(
        header=dict(
            values=[
                "<b>Strike</b>",
                "<b>Type</b>",
                "<b>OI Chg</b>",
                "<b>OI Chg%</b>",
                "<b>Vol/OI</b>",
                "<b>LTP</b>",
                "<b>Signal</b>",
                "<b>Strength</b>",
            ],
            fill_color=header_fill,
            font=dict(color=header_font_color, size=13),
            align="center",
            line_color="rgba(80,80,120,0.6)",
        ),
        cells=dict(
            values=[
                strikes,
                opt_types,
                oi_chgs,
                oi_chg_pcts,
                vol_oi_ratios,
                ltps,
                signal_types,
                strengths,
            ],
            fill_color=[fill_colors] * 8,
            font=dict(color=cell_font_color, size=12),
            align="center",
            line_color="rgba(60,60,100,0.4)",
        ),
    )])

    fig.update_layout(
        template="plotly_dark",
        height=400,
        paper_bgcolor="#1a1a2e",
        plot_bgcolor="#1a1a2e",
        margin=dict(l=0, r=0, t=10, b=0),
    )

    return fig
