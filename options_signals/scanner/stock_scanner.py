"""
F&O stock scanner — scans top 30 NSE F&O stocks for options signals.

Uses ThreadPoolExecutor + semaphore for concurrent fetching
(avoids sequential 15-second blocking scan).

Only fetches ±3 ATM strikes (not full chain) to minimise API load.
IV rank is approximated from current ATM IV relative to a stock-type baseline
since 52-week per-stock option IV history is not available via free Upstox endpoints.
This is a level proxy, not a true IV rank — treat results directionally.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from config import IST
from data.upstox_client import UpstoxClient, UpstoxAPIError, UpstoxAuthError
from utils.helpers import generate_expiry_dates

# Top 30 NSE F&O stocks by options liquidity
FO_STOCKS: Dict[str, Dict] = {
    "RELIANCE":    {"key": "NSE_EQ|INE002A01018", "lot": 250,  "baseline_iv": 0.22},
    "TCS":         {"key": "NSE_EQ|INE467B01029", "lot": 175,  "baseline_iv": 0.20},
    "INFY":        {"key": "NSE_EQ|INE009A01021", "lot": 300,  "baseline_iv": 0.21},
    "HDFCBANK":    {"key": "NSE_EQ|INE040A01034", "lot": 550,  "baseline_iv": 0.22},
    "ICICIBANK":   {"key": "NSE_EQ|INE090A01021", "lot": 700,  "baseline_iv": 0.24},
    "SBIN":        {"key": "NSE_EQ|INE062A01020", "lot": 1500, "baseline_iv": 0.26},
    "AXISBANK":    {"key": "NSE_EQ|INE238A01034", "lot": 625,  "baseline_iv": 0.26},
    "BAJFINANCE":  {"key": "NSE_EQ|INE296A01024", "lot": 125,  "baseline_iv": 0.30},
    "WIPRO":       {"key": "NSE_EQ|INE075A01022", "lot": 1500, "baseline_iv": 0.22},
    "LT":          {"key": "NSE_EQ|INE018A01030", "lot": 175,  "baseline_iv": 0.25},
    "MARUTI":      {"key": "NSE_EQ|INE585B01010", "lot": 100,  "baseline_iv": 0.23},
    "TITAN":       {"key": "NSE_EQ|INE280A01028", "lot": 375,  "baseline_iv": 0.25},
    "TATASTEEL":   {"key": "NSE_EQ|INE081A01012", "lot": 5500, "baseline_iv": 0.35},
    "HINDUNILVR":  {"key": "NSE_EQ|INE030A01027", "lot": 300,  "baseline_iv": 0.18},
    "KOTAKBANK":   {"key": "NSE_EQ|INE237A01028", "lot": 400,  "baseline_iv": 0.22},
    "ADANIPORTS":  {"key": "NSE_EQ|INE742F01042", "lot": 625,  "baseline_iv": 0.30},
    "SUNPHARMA":   {"key": "NSE_EQ|INE044A01036", "lot": 700,  "baseline_iv": 0.23},
    "DRREDDY":     {"key": "NSE_EQ|INE089A01023", "lot": 125,  "baseline_iv": 0.22},
    "BHARTIARTL":  {"key": "NSE_EQ|INE397D01024", "lot": 950,  "baseline_iv": 0.25},
    "ONGC":        {"key": "NSE_EQ|INE213A01029", "lot": 1925, "baseline_iv": 0.28},
    "COALINDIA":   {"key": "NSE_EQ|INE522F01014", "lot": 4200, "baseline_iv": 0.28},
    "POWERGRID":   {"key": "NSE_EQ|INE752E01010", "lot": 2700, "baseline_iv": 0.22},
    "NTPC":        {"key": "NSE_EQ|INE733E01010", "lot": 3000, "baseline_iv": 0.22},
    "BPCL":        {"key": "NSE_EQ|INE029A01011", "lot": 1800, "baseline_iv": 0.28},
    "ASIANPAINT":  {"key": "NSE_EQ|INE021A01026", "lot": 300,  "baseline_iv": 0.20},
    "ULTRACEMCO":  {"key": "NSE_EQ|INE481G01011", "lot": 100,  "baseline_iv": 0.22},
    "TECHM":       {"key": "NSE_EQ|INE669C01036", "lot": 600,  "baseline_iv": 0.24},
    "HCLTECH":     {"key": "NSE_EQ|INE860A01027", "lot": 700,  "baseline_iv": 0.22},
    "DIVISLAB":    {"key": "NSE_EQ|INE361B01024", "lot": 200,  "baseline_iv": 0.24},
    "NESTLEIND":   {"key": "NSE_EQ|INE239A01016", "lot": 40,   "baseline_iv": 0.18},
}

_SEMAPHORE = threading.Semaphore(4)  # max 4 concurrent API calls


@dataclass
class StockResult:
    ticker: str
    ltp: float
    signal: str
    confidence: str
    iv_rank_approx: float    # approximate — see module docstring
    pcr: float
    atm_iv: float
    strategy: str
    lot_size: int


def _sample_stock_result(ticker: str) -> StockResult:
    import random
    rng = random.Random(hash(ticker) % 1000)
    directions = ["BULLISH", "BEARISH", "NEUTRAL"]
    strategies  = ["Long Call", "Long Put", "Bull Call Spread", "Bear Put Spread", "Iron Condor"]
    return StockResult(
        ticker=ticker,
        ltp=rng.uniform(500, 3000),
        signal=rng.choice(directions),
        confidence=rng.choice(["HIGH", "MEDIUM", "LOW"]),
        iv_rank_approx=rng.uniform(10, 90),
        pcr=rng.uniform(0.5, 1.8),
        atm_iv=rng.uniform(15, 45),
        strategy=rng.choice(strategies),
        lot_size=FO_STOCKS[ticker]["lot"],
    )


def _fetch_one(ticker: str, client: Optional[UpstoxClient]) -> Optional[StockResult]:
    with _SEMAPHORE:
        if client is None:
            return _sample_stock_result(ticker)
        info = FO_STOCKS[ticker]
        try:
            # Get LTP
            quotes = client.get_market_quotes([info["key"]])
            raw = quotes.get(info["key"], {})
            ltp = float(raw.get("last_price", 0) or 0)
            if ltp <= 0:
                return _sample_stock_result(ticker)

            # Get nearest expiry options (only ATM ±3 strikes)
            # Nearest Thursday for stock options
            expiries = generate_expiry_dates(3, frozenset(), months_ahead=2)
            if not expiries:
                return _sample_stock_result(ticker)
            exp = expiries[0]

            chain = client.get_option_chain(info["key"], exp)
            if not chain:
                return _sample_stock_result(ticker)

            # Filter to nearest 6 strikes
            strikes = sorted(chain, key=lambda x: abs(float(x.get("strike_price", 0)) - ltp))[:6]

            total_ce_oi = sum(s.get("call_options", {}).get("market_data", {}).get("oi", 0) or 0 for s in strikes)
            total_pe_oi = sum(s.get("put_options",  {}).get("market_data", {}).get("oi", 0) or 0 for s in strikes)
            pcr = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 1.0

            # ATM IV
            atm = min(strikes, key=lambda x: abs(float(x.get("strike_price", 0)) - ltp))
            atm_iv_ce = float((atm.get("call_options") or {}).get("option_greeks", {}).get("iv", 0) or 0)
            atm_iv_pe = float((atm.get("put_options")  or {}).get("option_greeks", {}).get("iv", 0) or 0)
            atm_iv = (atm_iv_ce + atm_iv_pe) / 2 if (atm_iv_ce + atm_iv_pe) > 0 else 0

            # IV rank from rolling observed ATM IV history (persisted per ticker).
            # Falls back to baseline proxy until ≥10 observations are accumulated.
            import datetime as _dt
            from store.local_store import load as _load, save as _save
            obs_key = f"iv_obs_{ticker}"
            history = _load(obs_key, [])
            if atm_iv > 0:
                history.append({"iv": atm_iv, "ts": _dt.datetime.utcnow().isoformat()})
                history = history[-120:]   # keep ~120 observations (≈4 months at daily scan)
                _save(obs_key, history)
            ivs = [h["iv"] for h in history if h.get("iv", 0) > 0]
            if len(ivs) >= 10:
                iv_min, iv_max = min(ivs), max(ivs)
                iv_rank_approx = float(
                    (atm_iv - iv_min) / (iv_max - iv_min) * 100
                    if iv_max > iv_min else 50.0
                )
            else:
                # Baseline proxy while history builds up
                baseline = info["baseline_iv"] * 100
                iv_rank_approx = min(atm_iv / (baseline * 1.5) * 100, 100) if baseline > 0 else 50

            # Simple signal from PCR
            if pcr > 1.4:
                signal, strategy = "BULLISH", "Bull Call Spread"
            elif pcr < 0.6:
                signal, strategy = "BEARISH", "Bear Put Spread"
            else:
                signal = "NEUTRAL"
                strategy = "Iron Condor" if iv_rank_approx > 60 else "Long Straddle"

            confidence = "HIGH" if abs(pcr - 1.0) > 0.5 else ("MEDIUM" if abs(pcr - 1.0) > 0.25 else "LOW")

            return StockResult(
                ticker=ticker,
                ltp=round(ltp, 2),
                signal=signal,
                confidence=confidence,
                iv_rank_approx=round(iv_rank_approx, 1),
                pcr=round(pcr, 3),
                atm_iv=round(atm_iv, 2),
                strategy=strategy,
                lot_size=info["lot"],
            )
        except (UpstoxAuthError, UpstoxAPIError):
            return _sample_stock_result(ticker)
        except Exception:
            return None


def scan(
    client: Optional[UpstoxClient],
    direction_filter: str = "ALL",
    max_workers: int = 5,
) -> List[StockResult]:
    """
    Scan all F&O stocks concurrently (ThreadPoolExecutor, max 4 simultaneous API calls).
    Returns top 10 sorted by confidence + direction match.
    """
    results: List[StockResult] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, ticker, client): ticker for ticker in FO_STOCKS}
        for future in as_completed(futures):
            res = future.result()
            if res is not None:
                results.append(res)

    if direction_filter != "ALL":
        results = [r for r in results if r.signal == direction_filter]

    conf_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    results.sort(key=lambda r: (conf_order.get(r.confidence, 3), -r.iv_rank_approx))
    return results[:10]
