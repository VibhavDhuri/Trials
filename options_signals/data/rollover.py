"""
F&O rollover analysis — how OI is transitioning from current to next expiry.
High rollover (>65%) signals continuation bias; low (<40%) signals position unwind.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class RolloverResult:
    current_expiry: str
    next_expiry: str
    current_oi: float
    next_oi: float
    rollover_pct: float
    iv_cost_pp: float
    interpretation: str


def _get_strike_col(df: pd.DataFrame) -> str:
    for col in ("strike_price", "strike"):
        if col in df.columns:
            return col
    return df.columns[0]


def _atm_strike(df: pd.DataFrame, spot: float, strike_gap: int) -> float:
    rounded = round(spot / strike_gap) * strike_gap
    strike_col = _get_strike_col(df)
    if strike_col in df.columns:
        strikes = df[strike_col].unique()
        if len(strikes) > 0:
            return float(min(strikes, key=lambda s: abs(s - spot)))
    return float(rounded)


def _sum_oi_around_atm(
    df: pd.DataFrame, spot: float, strike_gap: int, n_strikes: int = 3
) -> float:
    strike_col = _get_strike_col(df)
    atm = _atm_strike(df, spot, strike_gap)
    low = atm - n_strikes * strike_gap
    high = atm + n_strikes * strike_gap
    subset = df[(df[strike_col] >= low) & (df[strike_col] <= high)]
    oi_cols = [c for c in subset.columns if "oi" in c.lower()]
    if not oi_cols:
        numeric_cols = subset.select_dtypes(include="number").columns.tolist()
        if strike_col in numeric_cols:
            numeric_cols.remove(strike_col)
        oi_cols = numeric_cols
    if not oi_cols:
        return 0.0
    return float(subset[oi_cols].sum().sum())


def _atm_iv(df: pd.DataFrame, spot: float, strike_gap: int) -> float:
    strike_col = _get_strike_col(df)
    atm = _atm_strike(df, spot, strike_gap)
    subset = df[df[strike_col] == atm]
    for col in ("iv", "implied_volatility", "call_iv", "ce_iv"):
        if col in subset.columns and not subset[col].isna().all():
            return float(subset[col].mean())
    iv_cols = [c for c in subset.columns if "iv" in c.lower()]
    if iv_cols:
        return float(subset[iv_cols[0]].mean())
    return 0.0


def compute_rollover(
    chain_df_curr: pd.DataFrame,
    chain_df_next: pd.DataFrame,
    spot: float,
    strike_gap: int,
) -> RolloverResult:
    current_expiry = (
        str(chain_df_curr["expiry"].iloc[0]) if "expiry" in chain_df_curr.columns else "current"
    )
    next_expiry = (
        str(chain_df_next["expiry"].iloc[0]) if "expiry" in chain_df_next.columns else "next"
    )

    current_oi = _sum_oi_around_atm(chain_df_curr, spot, strike_gap)
    next_oi = _sum_oi_around_atm(chain_df_next, spot, strike_gap)

    total = current_oi + next_oi
    rollover_pct = (next_oi / total * 100) if total > 0 else 0.0

    iv_curr = _atm_iv(chain_df_curr, spot, strike_gap)
    iv_next = _atm_iv(chain_df_next, spot, strike_gap)
    iv_cost_pp = iv_next - iv_curr

    if rollover_pct > 65:
        interpretation = "Well rolled — continuation bias"
    elif rollover_pct >= 40:
        interpretation = "Moderate rollover — neutral"
    else:
        interpretation = "Low rollover — potential unwind"

    return RolloverResult(
        current_expiry=current_expiry,
        next_expiry=next_expiry,
        current_oi=current_oi,
        next_oi=next_oi,
        rollover_pct=rollover_pct,
        iv_cost_pp=iv_cost_pp,
        interpretation=interpretation,
    )


def get_sample_rollover(current_expiry: str, next_expiry: str) -> RolloverResult:
    return RolloverResult(
        current_expiry=current_expiry,
        next_expiry=next_expiry,
        current_oi=285000,
        next_oi=198000,
        rollover_pct=41.0,
        iv_cost_pp=1.2,
        interpretation="Moderate rollover — neutral",
    )
