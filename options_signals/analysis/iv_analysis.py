"""
IV environment analysis: IV Rank, IV Percentile, HV comparison, volatility skew.
All inputs/outputs use IV as a FRACTION (not percentage) for consistency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class IVEnvironment:
    atm_iv: float            # fraction
    iv_rank: float           # 0–100
    iv_percentile: float     # 0–100
    hv_21d: Optional[float]  # 21-day historical vol, fraction
    iv_vs_hv: Optional[float]  # atm_iv / hv_21d ratio
    regime: str              # "HIGH_IV" | "NEUTRAL_IV" | "LOW_IV"
    regime_note: str
    skew: float              # put_iv_25d - call_iv_25d (positive = put skew)


_IV_HIGH_THRESHOLD = 70.0
_IV_LOW_THRESHOLD = 30.0


def compute_iv_rank(current_iv: float, iv_52w_high: float, iv_52w_low: float) -> float:
    """IV Rank: where current IV sits in the 52-week range."""
    if iv_52w_high <= iv_52w_low:
        return 50.0
    rank = (current_iv - iv_52w_low) / (iv_52w_high - iv_52w_low) * 100
    return float(np.clip(rank, 0.0, 100.0))


def compute_iv_percentile(current_iv: float, historical_ivs: np.ndarray) -> float:
    """IV Percentile: fraction of past IV observations below current."""
    if len(historical_ivs) == 0:
        return 50.0
    pct = np.mean(historical_ivs < current_iv) * 100
    return float(np.clip(pct, 0.0, 100.0))


def _atm_iv(chain_df: pd.DataFrame, spot: float) -> float:
    """Average of the two ATM strike IVs (CE + PE)."""
    if chain_df.empty:
        return 0.20
    atm_strike = (chain_df["strike"] - spot).abs().min()
    atm_rows = chain_df[chain_df["atm_distance"] == atm_strike]
    iv_vals = atm_rows["iv_frac"].values
    return float(np.mean(iv_vals)) if len(iv_vals) > 0 else 0.20


def _skew(chain_df: pd.DataFrame, spot: float) -> float:
    """
    Approximate skew: IV of 25-delta put minus IV of 25-delta call.
    Higher = steeper put skew (typical for Indian indices).
    """
    ce_rows = chain_df[chain_df["opt_type"] == "CE"].copy()
    pe_rows = chain_df[chain_df["opt_type"] == "PE"].copy()
    if ce_rows.empty or pe_rows.empty:
        return 0.0

    ce_25d = ce_rows.iloc[(ce_rows["delta"] - 0.25).abs().argsort()[:1]]
    pe_25d = pe_rows.iloc[(pe_rows["delta"].abs() - 0.25).abs().argsort()[:1]]

    if ce_25d.empty or pe_25d.empty:
        return 0.0

    return float(pe_25d["iv_frac"].values[0]) - float(ce_25d["iv_frac"].values[0])


def _compute_hv(closes: np.ndarray, window: int = 21) -> Optional[float]:
    if len(closes) < window + 1:
        return None
    log_returns = np.diff(np.log(closes[-window - 1:]))
    return float(np.std(log_returns) * np.sqrt(252))


def analyze_iv_environment(
    chain_df: pd.DataFrame,
    spot: float,
    iv_52w_high: float,
    iv_52w_low: float,
    recent_closes: Optional[np.ndarray] = None,
) -> IVEnvironment:
    atm = _atm_iv(chain_df, spot)
    rank = compute_iv_rank(atm, iv_52w_high, iv_52w_low)

    # Build a rough historical distribution from the rank bounds for percentile
    hist = np.linspace(iv_52w_low, iv_52w_high, 252)
    pct = compute_iv_percentile(atm, hist)

    hv = _compute_hv(recent_closes) if recent_closes is not None else None
    iv_hv_ratio = atm / hv if (hv and hv > 0) else None

    skew = _skew(chain_df, spot)

    if rank >= _IV_HIGH_THRESHOLD:
        regime = "HIGH_IV"
        note = (
            f"IV Rank {rank:.0f}/100 — options are EXPENSIVE. "
            "Favour premium-selling strategies (Iron Condor, Short Straddle, Credit Spreads). "
            "Be aware of skew when selling puts."
        )
    elif rank <= _IV_LOW_THRESHOLD:
        regime = "LOW_IV"
        note = (
            f"IV Rank {rank:.0f}/100 — options are CHEAP. "
            "Favour premium-buying strategies (Long Straddle, Long Strangle, Debit Spreads)."
        )
    else:
        regime = "NEUTRAL_IV"
        note = (
            f"IV Rank {rank:.0f}/100 — IV is in the middle of its range. "
            "No strong IV-based edge; rely more on directional signals."
        )

    return IVEnvironment(
        atm_iv=atm,
        iv_rank=rank,
        iv_percentile=pct,
        hv_21d=hv,
        iv_vs_hv=iv_hv_ratio,
        regime=regime,
        regime_note=note,
        skew=skew,
    )
