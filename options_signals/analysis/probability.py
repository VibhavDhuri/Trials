"""
Options probability metrics — ITM probability, Probability of Profit, Expected Value.
Monte Carlo uses vectorised numpy for speed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from config import RISK_FREE_RATE


def prob_itm(
    S: float,
    K: float,
    r: float,
    sigma: float,
    T: float,
    opt_type: str,
) -> float:
    if T <= 0 or sigma <= 0:
        return 0.5
    d2 = (np.log(S / K) + (r - 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    if opt_type == "CE":
        return float(norm.cdf(d2))
    return float(norm.cdf(-d2))


def prob_of_profit(
    legs: list,
    spot: float,
    iv_frac: float,
    dte_days: float,
    lot_size: int = 75,
    n_paths: int = 50_000,
) -> float:
    r = RISK_FREE_RATE
    T = dte_days / 365.0
    rng = np.random.default_rng()
    Z = rng.standard_normal(n_paths)
    ST = spot * np.exp((r - 0.5 * iv_frac**2) * T + iv_frac * np.sqrt(T) * Z)

    payoff = np.zeros(n_paths)
    net_premium = 0.0
    for leg in legs:
        sign = 1 if leg.action == "BUY" else -1
        if leg.opt_type == "CE":
            intrinsic = np.maximum(ST - leg.strike, 0.0)
        else:
            intrinsic = np.maximum(leg.strike - ST, 0.0)
        payoff += sign * intrinsic * leg.quantity * lot_size
        net_premium += (-1 if leg.action == "BUY" else 1) * leg.premium * leg.quantity * lot_size

    total_at_expiry = payoff + net_premium
    return float(np.mean(total_at_expiry > 0))


def expected_value(
    legs: list,
    spot: float,
    iv_frac: float,
    dte_days: float,
    lot_size: int = 75,
    n_paths: int = 50_000,
) -> float:
    r = RISK_FREE_RATE
    T = dte_days / 365.0
    rng = np.random.default_rng()
    Z = rng.standard_normal(n_paths)
    ST = spot * np.exp((r - 0.5 * iv_frac**2) * T + iv_frac * np.sqrt(T) * Z)

    payoff = np.zeros(n_paths)
    net_premium = 0.0
    for leg in legs:
        sign = 1 if leg.action == "BUY" else -1
        if leg.opt_type == "CE":
            intrinsic = np.maximum(ST - leg.strike, 0.0)
        else:
            intrinsic = np.maximum(leg.strike - ST, 0.0)
        payoff += sign * intrinsic * leg.quantity * lot_size
        net_premium += (-1 if leg.action == "BUY" else 1) * leg.premium * leg.quantity * lot_size

    total_at_expiry = payoff + net_premium
    return float(np.mean(total_at_expiry))


def breakeven_table(
    legs: list,
    spot: float,
    n_points: int = 21,
    lot_size: int = 75,
) -> pd.DataFrame:
    price_range = np.linspace(spot * 0.9, spot * 1.1, n_points)
    records: list[dict] = []
    for price in price_range:
        total_pnl = 0.0
        for leg in legs:
            sign = 1 if leg.action == "BUY" else -1
            if leg.opt_type == "CE":
                intrinsic = max(float(price) - leg.strike, 0.0)
            else:
                intrinsic = max(leg.strike - float(price), 0.0)
            net_per_lot = intrinsic - leg.premium
            total_pnl += sign * net_per_lot * leg.quantity * lot_size
        records.append({
            "underlying_price": round(float(price), 2),
            "total_pnl": round(total_pnl, 2),
            "pnl_pct_of_spot": round(total_pnl / spot * 100, 4) if spot != 0 else 0.0,
        })
    return pd.DataFrame(records)
