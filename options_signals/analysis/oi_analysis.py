"""
Open Interest analysis: max pain, PCR, OI buildup/unwinding, support/resistance.

PCR interpretation uses a CONSISTENT contrarian framework:
  PCR > 1.5  → extreme fear (put-heavy) → contrarian BULLISH
  1.2–1.5    → high put protection → mild bearish tilt
  0.8–1.2    → neutral
  0.5–0.8    → call-heavy → mild bullish complacency
  < 0.5      → extreme complacency → contrarian BEARISH

Max pain formula: argmin_{K_c} Σ [ CE_OI_K × max(K_c-K,0) + PE_OI_K × max(K-K_c,0) ]
i.e. the expiry price that minimises total ITM payout to all option buyers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd


@dataclass
class OIAnalysis:
    max_pain: float
    max_pain_distance: float     # points from spot
    max_pain_distance_pct: float # as % of spot
    pcr_oi: float
    pcr_volume: float
    pcr_oi_signal: str           # "BULLISH" | "NEUTRAL" | "BEARISH"
    pcr_oi_note: str
    total_call_oi: int
    total_put_oi: int
    total_call_volume: int
    total_put_volume: int
    call_oi_by_strike: pd.Series
    put_oi_by_strike: pd.Series
    ce_buildup_strikes: List[float] = field(default_factory=list)
    pe_buildup_strikes: List[float] = field(default_factory=list)
    ce_unwind_strikes: List[float] = field(default_factory=list)
    pe_unwind_strikes: List[float] = field(default_factory=list)
    support_levels: List[float] = field(default_factory=list)
    resistance_levels: List[float] = field(default_factory=list)


_OI_CHANGE_THRESHOLD = 0.15  # 15% OI change is significant


def compute_max_pain(chain_df: pd.DataFrame) -> float:
    """
    For each candidate expiry price K_c, total payout to all option buyers is:
        Σ_K [ CE_OI(K) × max(K_c - K, 0) + PE_OI(K) × max(K - K_c, 0) ]
    Max pain = K_c that minimises this payout.
    """
    ce = chain_df[chain_df["opt_type"] == "CE"].set_index("strike")["oi"]
    pe = chain_df[chain_df["opt_type"] == "PE"].set_index("strike")["oi"]
    strikes = sorted(set(ce.index) | set(pe.index))

    if not strikes:
        return 0.0

    min_payout = float("inf")
    max_pain_strike = strikes[0]

    for kc in strikes:
        call_payout = sum(ce.get(k, 0) * max(kc - k, 0) for k in strikes)
        put_payout = sum(pe.get(k, 0) * max(k - kc, 0) for k in strikes)
        total = call_payout + put_payout
        if total < min_payout:
            min_payout = total
            max_pain_strike = kc

    return float(max_pain_strike)


def _pcr_signal(pcr: float) -> tuple[str, str]:
    if pcr > 1.5:
        return "BULLISH", (
            f"PCR {pcr:.2f} — extreme put-heavy positioning. "
            "Contrarian signal: market may be oversold, potential bounce."
        )
    if pcr > 1.2:
        return "BEARISH", (
            f"PCR {pcr:.2f} — elevated put protection. "
            "Participants are hedging heavily; mild bearish tilt."
        )
    if pcr > 0.8:
        return "NEUTRAL", (
            f"PCR {pcr:.2f} — balanced put/call OI. "
            "No strong directional bias from OI positioning."
        )
    if pcr > 0.5:
        return "BULLISH", (
            f"PCR {pcr:.2f} — call-heavy positioning. "
            "Market participants leaning bullish; moderate complacency."
        )
    return "BEARISH", (
        f"PCR {pcr:.2f} — extreme call-heavy / low put protection. "
        "Contrarian signal: market may be overbought, watch for reversal."
    )


def _oi_buildups(
    chain_df: pd.DataFrame, opt_type: str, spot: float
) -> tuple[List[float], List[float]]:
    """Returns (buildup_strikes, unwind_strikes)."""
    rows = chain_df[chain_df["opt_type"] == opt_type].copy()
    if rows.empty:
        return [], []

    rows = rows[rows["oi"] > 0]
    build = rows[
        (rows["oi_chg_pct"] > _OI_CHANGE_THRESHOLD * 100) & (rows["ltp"] > 0)
    ]["strike"].tolist()
    unwind = rows[
        (rows["oi_chg_pct"] < -_OI_CHANGE_THRESHOLD * 100) & (rows["ltp"] > 0)
    ]["strike"].tolist()
    return sorted(build), sorted(unwind)


def _support_resistance(chain_df: pd.DataFrame, spot: float, top_n: int = 3) -> tuple[List[float], List[float]]:
    """
    Support: strikes with highest PUT OI below spot (put writers defend these levels).
    Resistance: strikes with highest CALL OI above spot (call writers defend these levels).
    """
    pe = chain_df[(chain_df["opt_type"] == "PE") & (chain_df["strike"] < spot)]
    ce = chain_df[(chain_df["opt_type"] == "CE") & (chain_df["strike"] > spot)]

    support = pe.nlargest(top_n, "oi")["strike"].tolist()
    resistance = ce.nlargest(top_n, "oi")["strike"].tolist()
    return sorted(support, reverse=True), sorted(resistance)


def analyze_oi(chain_df: pd.DataFrame, spot: float) -> OIAnalysis:
    if chain_df.empty:
        return OIAnalysis(
            max_pain=spot, max_pain_distance=0, max_pain_distance_pct=0,
            pcr_oi=1.0, pcr_volume=1.0, pcr_oi_signal="NEUTRAL",
            pcr_oi_note="No data", total_call_oi=0, total_put_oi=0,
            total_call_volume=0, total_put_volume=0,
            call_oi_by_strike=pd.Series(dtype=float),
            put_oi_by_strike=pd.Series(dtype=float),
        )

    ce_rows = chain_df[chain_df["opt_type"] == "CE"]
    pe_rows = chain_df[chain_df["opt_type"] == "PE"]

    total_ce_oi = int(ce_rows["oi"].sum())
    total_pe_oi = int(pe_rows["oi"].sum())
    total_ce_vol = int(ce_rows["volume"].sum())
    total_pe_vol = int(pe_rows["volume"].sum())

    pcr_oi = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 1.0
    pcr_vol = total_pe_vol / total_ce_vol if total_ce_vol > 0 else 1.0

    sig, note = _pcr_signal(pcr_oi)

    max_pain = compute_max_pain(chain_df)
    mp_dist = max_pain - spot
    mp_dist_pct = mp_dist / spot * 100

    ce_build, ce_unwind = _oi_buildups(chain_df, "CE", spot)
    pe_build, pe_unwind = _oi_buildups(chain_df, "PE", spot)

    support, resistance = _support_resistance(chain_df, spot)

    call_oi_by_strike = ce_rows.set_index("strike")["oi"].sort_index()
    put_oi_by_strike = pe_rows.set_index("strike")["oi"].sort_index()

    return OIAnalysis(
        max_pain=max_pain,
        max_pain_distance=mp_dist,
        max_pain_distance_pct=mp_dist_pct,
        pcr_oi=pcr_oi,
        pcr_volume=pcr_vol,
        pcr_oi_signal=sig,
        pcr_oi_note=note,
        total_call_oi=total_ce_oi,
        total_put_oi=total_pe_oi,
        total_call_volume=total_ce_vol,
        total_put_volume=total_pe_vol,
        call_oi_by_strike=call_oi_by_strike,
        put_oi_by_strike=put_oi_by_strike,
        ce_buildup_strikes=ce_build[:5],
        pe_buildup_strikes=pe_build[:5],
        ce_unwind_strikes=ce_unwind[:5],
        pe_unwind_strikes=pe_unwind[:5],
        support_levels=support,
        resistance_levels=resistance,
    )
