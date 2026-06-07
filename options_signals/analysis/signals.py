"""
Signal generation engine.

Confidence is determined by how many independent sources agree:
  3+ sources agree → HIGH
  2 sources agree  → MEDIUM
  1 or disagreement→ LOW (or MIXED)

Sources:
  1. OI/PCR (weight 30%)
  2. Max Pain (weight 20%)
  3. IV Regime (weight 20%)
  4. OI Buildup (weight 30%)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import pandas as pd

from analysis.iv_analysis import IVEnvironment
from analysis.oi_analysis import OIAnalysis
from analysis.greeks import expected_move
from utils.helpers import days_to_expiry


class Direction(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    RANGE_BOUND = "RANGE_BOUND"
    MIXED = "MIXED"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class Signal:
    direction: Direction
    confidence: Confidence
    strategy: str
    strategy_brief: str        # one-line description of the strategy
    reasons: List[str]
    recommended_strikes: List[float]
    expiry_date: str
    atm_strike: float
    spot: float
    expected_move_pts: float   # 1-SD move in index points
    expected_move_pct: float
    max_pain: float
    pcr_oi: float
    iv_rank: float
    atm_iv_pct: float
    source_votes: dict = field(default_factory=dict)  # source → direction


_MAX_PAIN_SIGNAL_THRESHOLD = 0.005   # 0.5% distance from spot for max pain signal


def _vote_oi_pcr(oi: OIAnalysis) -> Direction:
    sig = oi.pcr_oi_signal
    if sig == "BULLISH":
        return Direction.BULLISH
    if sig == "BEARISH":
        return Direction.BEARISH
    return Direction.NEUTRAL


def _vote_max_pain(oi: OIAnalysis, spot: float) -> Optional[Direction]:
    """If spot is far from max pain, market likely drifts toward max pain at expiry."""
    if abs(oi.max_pain_distance_pct) < 0.5:
        return Direction.NEUTRAL
    return Direction.BULLISH if oi.max_pain > spot else Direction.BEARISH


def _vote_iv_regime(iv_env: IVEnvironment) -> Optional[Direction]:
    """IV regime doesn't give a directional vote — it influences strategy only."""
    return None  # IV doesn't tell direction, only premium level


def _vote_oi_buildup(oi: OIAnalysis, spot: float) -> Optional[Direction]:
    """
    Call OI building above spot = resistance forming → bearish.
    Put OI building below spot = support forming → bullish.
    Call OI unwinding above spot = resistance weakening → bullish.
    Put OI unwinding below spot = support weakening → bearish.
    """
    bullish_score = 0
    bearish_score = 0

    for s in oi.pe_buildup_strikes:
        if s < spot:
            bullish_score += 1
    for s in oi.ce_buildup_strikes:
        if s > spot:
            bearish_score += 1
    for s in oi.ce_unwind_strikes:
        if s > spot:
            bullish_score += 1
    for s in oi.pe_unwind_strikes:
        if s < spot:
            bearish_score += 1

    if bullish_score > bearish_score:
        return Direction.BULLISH
    if bearish_score > bullish_score:
        return Direction.BEARISH
    return Direction.NEUTRAL


def _select_strategy(
    direction: Direction, iv_env: IVEnvironment, dte: float
) -> tuple[str, str]:
    """Returns (strategy_name, brief_description)."""
    regime = iv_env.regime
    is_short_dated = dte < 7

    if direction == Direction.RANGE_BOUND or direction == Direction.NEUTRAL:
        if regime == "HIGH_IV":
            if is_short_dated:
                return "Short Straddle", "Sell ATM CE + PE; profit from time decay in high-IV environment"
            return "Iron Condor", "Sell OTM CE + OTM PE, buy further OTM wings; range-bound + high IV"
        if regime == "LOW_IV":
            return "Long Straddle", "Buy ATM CE + PE; anticipate big move in low-IV environment"
        return "Iron Fly", "Sell ATM straddle + buy OTM wings; neutral outlook"

    if direction == Direction.BULLISH:
        if regime == "HIGH_IV":
            return "Bull Put Spread", "Sell OTM PE + buy lower-strike PE; bullish with credit collected"
        if regime == "LOW_IV":
            return "Long Call", "Buy ATM or slightly OTM CE; low-cost directional bet"
        return "Bull Call Spread", "Buy ATM CE + sell OTM CE; defined-risk bullish"

    if direction == Direction.BEARISH:
        if regime == "HIGH_IV":
            return "Bear Call Spread", "Sell OTM CE + buy higher-strike CE; bearish with credit collected"
        if regime == "LOW_IV":
            return "Long Put", "Buy ATM or slightly OTM PE; low-cost directional bet"
        return "Bear Put Spread", "Buy ATM PE + sell OTM PE; defined-risk bearish"

    return "Wait / Observe", "Conflicting signals — no clear edge; avoid new positions"


def _recommended_strikes(
    direction: Direction, spot: float, chain_df: pd.DataFrame, strategy: str
) -> List[float]:
    """Return 1–2 recommended strike(s) for the suggested strategy."""
    if chain_df.empty:
        return []
    ce = chain_df[chain_df["opt_type"] == "CE"].copy()
    pe = chain_df[chain_df["opt_type"] == "PE"].copy()

    atm_ce = ce.iloc[(ce["atm_distance"]).argsort()[:1]]["strike"].values
    atm_pe = pe.iloc[(pe["atm_distance"]).argsort()[:1]]["strike"].values

    atm_strike = float(atm_ce[0]) if len(atm_ce) else spot

    if direction in (Direction.RANGE_BOUND, Direction.NEUTRAL):
        return [atm_strike]
    if direction == Direction.BULLISH:
        otm_ce = ce[ce["strike"] > spot].nsmallest(2, "atm_distance")["strike"].values
        return [float(otm_ce[0])] if len(otm_ce) else [atm_strike]
    if direction == Direction.BEARISH:
        otm_pe = pe[pe["strike"] < spot].nsmallest(2, "atm_distance")["strike"].values
        return [float(otm_pe[0])] if len(otm_pe) else [atm_strike]
    return [atm_strike]


def generate_signals(
    chain_df: pd.DataFrame,
    iv_env: IVEnvironment,
    oi_analysis: OIAnalysis,
    spot: float,
    expiry_date: str,
) -> List[Signal]:
    """
    Generate trading signals for a single expiry.
    Returns a list (may contain one composite signal + optional range signal).
    """
    if chain_df.empty:
        return []

    T = days_to_expiry(expiry_date)
    dte_calendar = T * 365.25

    # Compute ATM strike
    ce = chain_df[chain_df["opt_type"] == "CE"]
    atm_row = ce.iloc[(ce["atm_distance"]).argsort()[:1]] if not ce.empty else pd.DataFrame()
    atm_strike = float(atm_row["strike"].values[0]) if not atm_row.empty else spot
    atm_iv = iv_env.atm_iv  # fraction

    exp_move_pts = expected_move(spot, atm_iv, T)
    exp_move_pct = atm_iv * (T**0.5) * 100  # approximately

    # Gather votes from each source
    votes: dict[str, Direction] = {}
    reasons: List[str] = []

    # 1. PCR vote
    v_pcr = _vote_oi_pcr(oi_analysis)
    votes["PCR"] = v_pcr
    reasons.append(f"[PCR] {oi_analysis.pcr_oi_note}")

    # 2. Max pain vote
    v_mp = _vote_max_pain(oi_analysis, spot)
    if v_mp:
        votes["MaxPain"] = v_mp
        dist_str = f"{oi_analysis.max_pain_distance:+.0f} pts ({oi_analysis.max_pain_distance_pct:+.1f}%)"
        reasons.append(
            f"[Max Pain] Max pain at {oi_analysis.max_pain:.0f} ({dist_str} from spot) → "
            f"price may drift {'up' if v_mp == Direction.BULLISH else 'down'} toward expiry"
        )

    # 3. OI buildup vote
    v_build = _vote_oi_buildup(oi_analysis, spot)
    if v_build:
        votes["OI_Buildup"] = v_build
        if oi_analysis.pe_buildup_strikes:
            reasons.append(
                f"[OI Buildup] Put support building at {', '.join(str(int(s)) for s in oi_analysis.pe_buildup_strikes[:3])}"
            )
        if oi_analysis.ce_buildup_strikes:
            reasons.append(
                f"[OI Buildup] Call resistance forming at {', '.join(str(int(s)) for s in oi_analysis.ce_buildup_strikes[:3])}"
            )

    # 4. IV regime context (strategy only, not directional)
    reasons.append(f"[IV] {iv_env.regime_note}")
    if iv_env.skew > 0.01:
        reasons.append(
            f"[Skew] Put skew = {iv_env.skew*100:.1f}% — put IVs are richer than calls. "
            "Beware asymmetric risk when selling puts."
        )

    # Tally directional votes
    directional_votes = [v for v in votes.values() if v not in (Direction.NEUTRAL, None)]
    bull_count = sum(1 for v in directional_votes if v == Direction.BULLISH)
    bear_count = sum(1 for v in directional_votes if v == Direction.BEARISH)

    # Determine aggregate direction
    if bull_count == 0 and bear_count == 0:
        direction = Direction.NEUTRAL
        strategy, brief = _select_strategy(direction, iv_env, dte_calendar)
    elif bull_count > bear_count:
        direction = Direction.BULLISH
        strategy, brief = _select_strategy(direction, iv_env, dte_calendar)
    elif bear_count > bull_count:
        direction = Direction.BEARISH
        strategy, brief = _select_strategy(direction, iv_env, dte_calendar)
    else:
        direction = Direction.MIXED
        strategy = "Wait / Observe"
        brief = "Bull and bear signals are evenly split — no clear edge"
        reasons.append(
            f"[Conflict] {bull_count} bullish vs {bear_count} bearish signal sources. "
            "Avoid new positions until signals align."
        )

    # Confidence: based on agreement count
    agree_count = max(bull_count, bear_count)
    if agree_count >= 3:
        confidence = Confidence.HIGH
    elif agree_count == 2:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW

    # Check for range-bound condition: PCR neutral + max pain near spot + low atm_iv
    is_rangebound = (
        abs(oi_analysis.max_pain_distance_pct) < 1.0
        and iv_env.iv_rank < 50
        and abs(oi_analysis.pcr_oi - 1.0) < 0.3
    )
    if is_rangebound and direction == Direction.NEUTRAL:
        direction = Direction.RANGE_BOUND
        strategy, brief = _select_strategy(direction, iv_env, dte_calendar)

    rec_strikes = _recommended_strikes(direction, spot, chain_df, strategy)

    return [
        Signal(
            direction=direction,
            confidence=confidence,
            strategy=strategy,
            strategy_brief=brief,
            reasons=reasons,
            recommended_strikes=rec_strikes,
            expiry_date=expiry_date,
            atm_strike=atm_strike,
            spot=spot,
            expected_move_pts=exp_move_pts,
            expected_move_pct=exp_move_pct,
            max_pain=oi_analysis.max_pain,
            pcr_oi=oi_analysis.pcr_oi,
            iv_rank=iv_env.iv_rank,
            atm_iv_pct=atm_iv * 100,
            source_votes={k: v.value for k, v in votes.items()},
        )
    ]
