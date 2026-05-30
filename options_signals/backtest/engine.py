"""
Simplified signal-replay backtest.

IMPORTANT LIMITATIONS — read before using results:
1. No actual historical options prices are used. Option premiums are estimated
   from Black-Scholes using 20-day rolling HV as an IV proxy.
2. HV is structurally LOWER than IV (volatility risk premium averages 3-5% in
   Indian markets). This biases premium-selling backtests optimistically.
3. P&L is gross — no STT, brokerage, or slippage.
4. Entry/exit timing is simulated (open next day / close at expiry).
Results are INDICATIVE ONLY and should not be used to evaluate real strategies.
"""
from __future__ import annotations

import datetime
import random
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from analysis.greeks import bs_price
from config import INDICES, RISK_FREE_RATE


def _rolling_hv(closes: np.ndarray, window: int = 20) -> np.ndarray:
    """Annualised rolling HV as proxy for IV (biased low — see module docstring)."""
    log_rets = np.diff(np.log(np.maximum(closes, 1e-6)))
    hv = np.full(len(closes), np.nan)
    for i in range(window, len(closes)):
        hv[i] = np.std(log_rets[i - window: i]) * np.sqrt(252)
    return hv


def _simple_signal(spot: float, iv: float, prev_spot: float) -> str:
    """Simplified signal: trend-following on 5-day momentum + IV level."""
    if prev_spot <= 0:
        return "NEUTRAL"
    pct_chg = (spot - prev_spot) / prev_spot
    if pct_chg > 0.005 and iv < 0.25:
        return "BULLISH"
    if pct_chg < -0.005 and iv < 0.25:
        return "BEARISH"
    if iv > 0.20:
        return "RANGE_BOUND"
    return "NEUTRAL"


def _sample_candles(days: int, symbol: str) -> list:
    """Generate synthetic daily candles for offline mode."""
    cfg = INDICES.get(symbol, {})
    base = getattr(cfg, "base_spot", None) or 22000.0
    rng = random.Random(42)
    candles = []
    current = float(base)
    today = datetime.date.today()
    for i in range(days, 0, -1):
        date = today - datetime.timedelta(days=i)
        if date.weekday() >= 5:
            continue
        ret = rng.gauss(0.0003, 0.012)
        open_p = current
        close_p = current * (1 + ret)
        high_p  = max(open_p, close_p) * rng.uniform(1.000, 1.015)
        low_p   = min(open_p, close_p) * rng.uniform(0.985, 1.000)
        vol     = int(rng.uniform(1e6, 5e6))
        candles.append([date.isoformat(), open_p, high_p, low_p, close_p, vol, 0])
        current = close_p
    return candles


def run_backtest(
    symbol: str,
    client,
    days_back: int = 90,
    strategy: str = "ATM_CE",
    stop_loss_pct: float = 0.50,
) -> Tuple[pd.DataFrame, dict]:
    """
    Replay signals day by day on historical underlying data.
    Returns (trades_df, summary_dict).

    trades_df columns: entry_date, exit_date, signal, entry_price, exit_price,
                       pnl, exit_reason, cum_pnl
    """
    days_back = min(days_back, 252)

    # Fetch or generate candles
    candles: list = []
    if client is not None:
        try:
            cfg = INDICES.get(symbol, {})
            key = getattr(cfg, "instrument_key", None) or ""
            if key:
                raw = client.get_historical_candles(key, "day", days=days_back + 30)
                candles = raw if raw else []
        except Exception:
            candles = []

    if not candles:
        candles = _sample_candles(days_back + 30, symbol)

    if len(candles) < 25:
        return pd.DataFrame(), {
            "total_trades": 0, "win_rate": 0, "avg_pnl": 0,
            "total_pnl": 0, "max_drawdown": 0, "sharpe": 0,
            "best": 0, "worst": 0,
        }

    cfg  = INDICES.get(symbol, {})
    lot  = getattr(cfg, "lot_size", 75)
    gap  = getattr(cfg, "strike_gap", 50)

    closes = np.array([float(c[4]) for c in candles])
    opens  = np.array([float(c[1]) for c in candles])
    dates  = [str(c[0])[:10] for c in candles]

    hv_arr = _rolling_hv(closes)

    days_to_hold = 7
    trades = []
    in_trade   = False
    entry_price = 0.0
    entry_date  = ""
    entry_strike = 0.0
    entry_type   = "CE"
    entry_idx    = 0
    signal_used  = ""

    for i in range(22, len(closes) - 1):
        spot = closes[i]
        # Apply 25% VRP (volatility risk premium) adjustment: markets price options
        # ~20-30% above realised HV on average. This corrects the systematic bias.
        raw_hv = hv_arr[i] if not np.isnan(hv_arr[i]) else 0.15
        iv     = max(raw_hv * 1.25, 0.06)
        prev_spot = closes[i - 5] if i >= 5 else closes[0]

        direction = _simple_signal(spot, iv, prev_spot)

        if not in_trade:
            # Decide entry based on strategy
            should_enter = False
            if strategy == "ATM_CE" and direction == "BULLISH":
                should_enter = True; opt_type = "CE"
            elif strategy == "ATM_PE" and direction == "BEARISH":
                should_enter = True; opt_type = "PE"
            elif strategy == "STRADDLE" and direction in ("BULLISH", "BEARISH", "RANGE_BOUND"):
                should_enter = True; opt_type = "STRADDLE"

            if should_enter and i + 1 < len(closes):
                next_open = opens[i + 1]
                atm = round(next_open / gap) * gap
                T = days_to_hold / 365.25
                ep_ce = bs_price(next_open, atm, T, RISK_FREE_RATE, iv, "CE")
                ep_pe = bs_price(next_open, atm, T, RISK_FREE_RATE, iv, "PE")
                if opt_type == "CE":
                    ep = ep_ce
                elif opt_type == "PE":
                    ep = ep_pe
                else:
                    ep = ep_ce + ep_pe

                if ep > 0:
                    ep = ep * 1.01   # simulate paying the offer (1% bid-ask half-spread)
                    in_trade     = True
                    entry_price  = ep
                    entry_date   = dates[i + 1]
                    entry_strike = atm
                    entry_type   = opt_type
                    entry_idx    = i + 1
                    signal_used  = direction

        else:
            days_held = i - entry_idx
            T_rem = max(days_to_hold - days_held, 1) / 365.25
            iv_curr = hv_arr[i] if not np.isnan(hv_arr[i]) else 0.15
            iv_curr = max(iv_curr, 0.05)
            curr_spot = closes[i]

            cp_ce = bs_price(curr_spot, entry_strike, T_rem, RISK_FREE_RATE, iv_curr, "CE")
            cp_pe = bs_price(curr_spot, entry_strike, T_rem, RISK_FREE_RATE, iv_curr, "PE")
            if entry_type == "CE":
                curr_p = cp_ce
            elif entry_type == "PE":
                curr_p = cp_pe
            else:
                curr_p = cp_ce + cp_pe

            stop_hit    = curr_p < entry_price * (1 - stop_loss_pct)
            hold_expired = days_held >= days_to_hold

            if stop_hit or hold_expired:
                curr_p = curr_p * 0.99   # simulate receiving the bid (1% half-spread)
                pnl = (curr_p - entry_price) * lot
                trades.append({
                    "entry_date":  entry_date,
                    "exit_date":   dates[i],
                    "signal":      signal_used,
                    "entry_price": round(entry_price, 2),
                    "exit_price":  round(curr_p, 2),
                    "pnl":         round(pnl, 2),
                    "exit_reason": "Stop-Loss" if stop_hit else "Expiry",
                })
                in_trade = False

    df = pd.DataFrame(trades)
    if df.empty:
        return df, {
            "total_trades": 0, "win_rate": 0, "avg_pnl": 0,
            "total_pnl": 0, "max_drawdown": 0, "sharpe": 0,
            "best": 0, "worst": 0,
        }

    df["cum_pnl"] = df["pnl"].cumsum()
    total = len(df)
    wins  = (df["pnl"] > 0).sum()
    pnls  = df["pnl"].values

    equity = np.cumsum(pnls)
    peak   = np.maximum.accumulate(equity)
    dd     = equity - peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0
    sharpe = float(np.mean(pnls) / np.std(pnls)) if np.std(pnls) > 0 else 0.0

    summary = {
        "total_trades": total,
        "win_rate":     round(wins / total * 100, 1),
        "avg_pnl":      round(float(np.mean(pnls)), 2),
        "total_pnl":    round(float(np.sum(pnls)), 2),
        "max_drawdown": round(max_dd, 2),
        "sharpe":       round(sharpe, 3),
        "best":         round(float(np.max(pnls)), 2),
        "worst":        round(float(np.min(pnls)), 2),
    }
    return df, summary
