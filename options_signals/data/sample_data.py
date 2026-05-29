"""
Offline sample data generator.
Produces realistic-looking options chain data for UI testing
when Upstox credentials are absent.

Data is keyed the same way as live API output so all analysis
code runs identically in offline mode.
"""
from __future__ import annotations

import datetime
import random
from typing import Dict, List, Tuple

import numpy as np

from config import INDICES, IST
from analysis.greeks import bs_price, compute_greeks

random.seed(42)
np.random.seed(42)

# Approximate spot prices for each index
_SPOT_PRICES = {
    "NIFTY":      22_500.0,
    "BANKNIFTY":  48_200.0,
    "SENSEX":     74_000.0,
    "FINNIFTY":   22_100.0,
    "MIDCPNIFTY": 11_800.0,
}

_RISK_FREE = 0.065


def _vol_smile(moneyness: float, base_iv: float) -> float:
    """
    Approximate Indian index volatility smile:
    - OTM puts have higher IV (put skew)
    - Slight elevation for far OTM calls
    """
    # moneyness = (K - S) / S
    if moneyness < 0:  # OTM put / ITM call
        skew = -moneyness * 0.8  # steeper downside skew
    else:
        skew = moneyness * 0.3
    return max(base_iv + skew * base_iv, 0.05)


def _generate_expiry_chain(
    symbol: str,
    expiry_date: str,
    spot: float,
    base_iv: float,
    prev_close: float,
) -> List[Dict]:
    cfg = INDICES[symbol]
    gap = cfg.strike_gap

    # Generate strikes: ±10 gaps around ATM
    atm = round(spot / gap) * gap
    strikes = [atm + i * gap for i in range(-10, 11)]

    exp_dt = datetime.datetime.strptime(expiry_date, "%Y-%m-%d")
    T = max((exp_dt.date() - datetime.date.today()).days / 365.25, 1 / 365.25)

    chain = []
    for K in strikes:
        # Both CE and PE at the same strike share the same IV (put-call parity).
        # _vol_smile uses (K-spot)/spot: negative = OTM put territory (higher IV).
        iv_ce = _vol_smile((K - spot) / spot, base_iv)
        iv_pe = iv_ce

        # Theoretical prices
        ce_price = bs_price(spot, K, T, _RISK_FREE, iv_ce, "CE")
        pe_price = bs_price(spot, K, T, _RISK_FREE, iv_pe, "PE")

        # Add bid-ask spread (wider OTM)
        spread_factor = 1 + abs(K - spot) / spot * 5
        ce_bid = max(ce_price * (1 - 0.01 * spread_factor), 0.05)
        ce_ask = ce_price * (1 + 0.01 * spread_factor)
        pe_bid = max(pe_price * (1 - 0.01 * spread_factor), 0.05)
        pe_ask = pe_price * (1 + 0.01 * spread_factor)

        # OI: higher near ATM, skewed put-heavy below spot
        distance_factor = max(1 - abs(K - spot) / (spot * 0.05), 0.02)
        put_skew = 1.3 if K < spot else 1.0
        ce_oi = int(random.uniform(0.5e5, 3e6) * distance_factor)
        pe_oi = int(random.uniform(0.5e5, 3e6) * distance_factor * put_skew)
        ce_oi_prev = int(ce_oi * random.uniform(0.85, 1.15))
        pe_oi_prev = int(pe_oi * random.uniform(0.85, 1.15))

        ce_vol = int(ce_oi * random.uniform(0.02, 0.3))
        pe_vol = int(pe_oi * random.uniform(0.02, 0.3))

        # Greeks from BS
        g_ce = compute_greeks(spot, K, T, _RISK_FREE, iv_ce, "CE")
        g_pe = compute_greeks(spot, K, T, _RISK_FREE, iv_pe, "PE")

        chain.append({
            "strike_price": float(K),
            "expiry": expiry_date,
            "underlying_spot_price": spot,
            "call_options": {
                "instrument_key": f"NSE_FO|CE_{symbol}_{K}_{expiry_date}",
                "market_data": {
                    "ltp": round(ce_price, 2),
                    "bid_price": round(ce_bid, 2),
                    "ask_price": round(ce_ask, 2),
                    "bid_qty": cfg.lot_size,
                    "ask_qty": cfg.lot_size * 2,
                    "oi": ce_oi,
                    "prev_oi": ce_oi_prev,
                    "volume": ce_vol,
                    "close_price": round(ce_price * random.uniform(0.9, 1.1), 2),
                    "high": round(ce_price * 1.15, 2),
                    "low": round(ce_price * 0.85, 2),
                    "open": round(ce_price * random.uniform(0.9, 1.1), 2),
                },
                "option_greeks": {
                    "delta": round(g_ce.delta, 4),
                    "gamma": round(g_ce.gamma, 6),
                    "theta": round(g_ce.theta, 4),
                    "vega": round(g_ce.vega, 4),
                    "iv": round(iv_ce * 100, 2),  # API returns IV as percentage
                },
            },
            "put_options": {
                "instrument_key": f"NSE_FO|PE_{symbol}_{K}_{expiry_date}",
                "market_data": {
                    "ltp": round(pe_price, 2),
                    "bid_price": round(pe_bid, 2),
                    "ask_price": round(pe_ask, 2),
                    "bid_qty": cfg.lot_size,
                    "ask_qty": cfg.lot_size * 2,
                    "oi": pe_oi,
                    "prev_oi": pe_oi_prev,
                    "volume": pe_vol,
                    "close_price": round(pe_price * random.uniform(0.9, 1.1), 2),
                    "high": round(pe_price * 1.15, 2),
                    "low": round(pe_price * 0.85, 2),
                    "open": round(pe_price * random.uniform(0.9, 1.1), 2),
                },
                "option_greeks": {
                    "delta": round(g_pe.delta, 4),
                    "gamma": round(g_pe.gamma, 6),
                    "theta": round(g_pe.theta, 4),
                    "vega": round(g_pe.vega, 4),
                    "iv": round(iv_pe * 100, 2),
                },
            },
        })

    return chain


def get_sample_market_quote(symbol: str) -> Dict:
    spot = _SPOT_PRICES.get(symbol, 20000.0)
    prev = spot * random.uniform(0.98, 1.02)
    return {
        "last_price": spot,
        "ohlc": {
            "open": round(prev * 1.001, 2),
            "high": round(spot * 1.008, 2),
            "low": round(spot * 0.992, 2),
            "close": round(prev, 2),
        },
        "net_change": round((spot - prev) / prev * 100, 2),
        "volume": random.randint(100_000, 500_000),
        "timestamp": datetime.datetime.now(IST).isoformat(),
    }


def get_sample_option_chain(symbol: str, expiry_date: str) -> List[Dict]:
    spot = _SPOT_PRICES.get(symbol, 20000.0)
    # IV varies by DTE: closer = lower IV for index options (typically)
    exp_dt = datetime.datetime.strptime(expiry_date, "%Y-%m-%d").date()
    dte = max((exp_dt - datetime.date.today()).days, 0)
    base_iv = 0.12 + min(dte / 365, 0.5) * 0.06 + random.uniform(-0.01, 0.01)
    return _generate_expiry_chain(symbol, expiry_date, spot, base_iv, spot)


def get_sample_historical_iv() -> Tuple[float, float]:
    """Returns (iv_52w_high, iv_52w_low) as fractions."""
    return 0.28, 0.10
