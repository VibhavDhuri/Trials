"""
Black-Scholes Greeks and implied volatility.

Theta is returned as per-TRADING-day decay (divided by 252).
Vega is returned as per-1%-point change in IV (divided by 100).
IV is solved with Brent's method — robust for 0DTE and deep ITM/OTM options.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm

TRADING_DAYS_PER_YEAR = 252


@dataclass
class GreeksResult:
    delta: float
    gamma: float
    theta: float       # per trading day (negative for long positions)
    vega: float        # per 1 percentage-point move in IV
    rho: float
    theoretical_price: float
    iv: Optional[float] = None


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float):
    sqrt_T = np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return d1, d2


def bs_price(S: float, K: float, T: float, r: float, sigma: float, opt: str) -> float:
    """Theoretical Black-Scholes price. opt = 'CE' or 'PE'."""
    if T <= 0:
        return max(S - K, 0.0) if opt == "CE" else max(K - S, 0.0)
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    if opt == "CE":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def compute_greeks(
    S: float, K: float, T: float, r: float, sigma: float, opt: str
) -> GreeksResult:
    """Compute all BS Greeks for a single option."""
    if T <= 0 or sigma <= 0:
        directional = 1.0 if opt == "CE" else -1.0
        return GreeksResult(
            delta=directional if (opt == "CE" and S > K) or (opt == "PE" and S < K) else 0.0,
            gamma=0.0,
            theta=0.0,
            vega=0.0,
            rho=0.0,
            theoretical_price=bs_price(S, K, 0, r, max(sigma, 0.001), opt),
        )

    d1, d2 = _d1_d2(S, K, T, r, sigma)
    sqrt_T = np.sqrt(T)
    exp_rT = np.exp(-r * T)
    pdf_d1 = norm.pdf(d1)

    price = bs_price(S, K, T, r, sigma, opt)

    delta = norm.cdf(d1) if opt == "CE" else norm.cdf(d1) - 1.0
    gamma = pdf_d1 / (S * sigma * sqrt_T)

    # Theta: annualised raw divided by TRADING_DAYS_PER_YEAR for per-day decay
    raw_theta = -(S * pdf_d1 * sigma) / (2 * sqrt_T)
    if opt == "CE":
        raw_theta -= r * K * exp_rT * norm.cdf(d2)
    else:
        raw_theta += r * K * exp_rT * norm.cdf(-d2)
    theta = raw_theta / TRADING_DAYS_PER_YEAR

    # Vega: per 1 percentage-point move (raw vega / 100)
    vega = S * pdf_d1 * sqrt_T / 100.0

    # Rho: per 1 percentage-point move in risk-free rate
    if opt == "CE":
        rho = K * T * exp_rT * norm.cdf(d2) / 100.0
    else:
        rho = -K * T * exp_rT * norm.cdf(-d2) / 100.0

    return GreeksResult(delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho, theoretical_price=price)


def implied_volatility(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    opt: str,
    lo: float = 0.001,
    hi: float = 20.0,
) -> Optional[float]:
    """
    Solve for IV using Brent's method (robust for 0DTE and deep OTM).
    Returns None if no solution in [lo, hi] or market_price < intrinsic value.
    """
    if T <= 0 or market_price <= 0:
        return None
    intrinsic = max(S - K, 0.0) if opt == "CE" else max(K - S, 0.0)
    if market_price <= intrinsic:
        return None

    def objective(sigma: float) -> float:
        return bs_price(S, K, T, r, sigma, opt) - market_price

    try:
        f_lo, f_hi = objective(lo), objective(hi)
        if f_lo * f_hi > 0:
            return None
        return brentq(objective, lo, hi, xtol=1e-6, maxiter=200)
    except (ValueError, RuntimeError):
        return None


def expected_move(S: float, iv_frac: float, T_years: float) -> float:
    """1-standard-deviation expected move (in index points) over T years."""
    return S * iv_frac * np.sqrt(T_years)
