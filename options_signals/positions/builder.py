"""
Multi-leg strategy builder — payoff analysis and breakeven calculation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from config import INDICES


@dataclass
class Leg:
    opt_type: str    # "CE" | "PE"
    strike: float
    action: str      # "BUY" | "SELL"
    quantity: int    # lots
    ltp: float
    iv: float
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0


@dataclass
class StrategyAnalysis:
    legs: List[Leg]
    net_premium: float          # positive = credit, negative = debit (per lot)
    net_premium_inr: float      # × lot_size
    net_delta: float
    net_gamma: float
    net_theta: float
    net_vega: float
    breakevens: List[float]
    max_profit: Optional[float]   # INR, None = unlimited
    max_loss: Optional[float]     # INR, None = unlimited
    margin_estimate: float        # indicative only
    payoff_spots: np.ndarray
    payoff_pnl: np.ndarray        # INR per lot at expiry


def _leg_payoff(leg: Leg, spots: np.ndarray) -> np.ndarray:
    if leg.opt_type == "CE":
        intrinsic = np.maximum(spots - leg.strike, 0.0)
    else:
        intrinsic = np.maximum(leg.strike - spots, 0.0)
    sign = 1 if leg.action == "BUY" else -1
    return sign * (intrinsic - leg.ltp) * leg.quantity


def analyse(legs: List[Leg], symbol: str, spot: float) -> StrategyAnalysis:
    lot = INDICES[symbol].lot_size

    # Payoff across spot ± 15%
    spots = np.linspace(spot * 0.85, spot * 1.15, 300)
    total_payoff = sum(_leg_payoff(l, spots) for l in legs) * lot  # INR

    # Net premium (positive = credit received)
    net_prem = sum(
        (l.ltp if l.action == "SELL" else -l.ltp) * l.quantity
        for l in legs
    )

    # Greeks (signed by direction)
    def _sum(attr: str) -> float:
        return sum(
            getattr(l, attr) * l.quantity * lot * (1 if l.action == "BUY" else -1)
            for l in legs
        )

    n_delta = _sum("delta")
    n_gamma = _sum("gamma")
    n_theta = _sum("theta")
    n_vega  = _sum("vega")

    # Breakevens: zero-crossings of payoff curve
    breakevens: List[float] = []
    for i in range(len(total_payoff) - 1):
        if total_payoff[i] * total_payoff[i + 1] <= 0:
            # Linear interpolation
            x0, x1 = spots[i], spots[i + 1]
            y0, y1 = total_payoff[i], total_payoff[i + 1]
            if y1 != y0:
                be = x0 - y0 * (x1 - x0) / (y1 - y0)
                breakevens.append(round(float(be), 2))

    max_profit = float(total_payoff.max()) if not np.isinf(total_payoff.max()) else None
    max_loss   = float(total_payoff.min()) if not np.isinf(-total_payoff.min()) else None

    # Margin: sum of short-leg premium × lot × 3 (indicative SPAN proxy for index options)
    # NOTE: actual SPAN margin is ~15-20% of notional for naked legs; this is a rough estimate only
    short_premium = sum(l.ltp * l.quantity * lot for l in legs if l.action == "SELL")
    margin_est = short_premium * 3

    return StrategyAnalysis(
        legs=legs,
        net_premium=net_prem,
        net_premium_inr=net_prem * lot,
        net_delta=n_delta,
        net_gamma=n_gamma,
        net_theta=n_theta,
        net_vega=n_vega,
        breakevens=breakevens,
        max_profit=max_profit,
        max_loss=max_loss,
        margin_estimate=margin_est,
        payoff_spots=spots,
        payoff_pnl=total_payoff,
    )
