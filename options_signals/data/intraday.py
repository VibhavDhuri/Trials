"""
Intraday candle fetching with VWAP and EMA computation.
VWAP uses typical price = (H + L + C) / 3 per candle — the standard convention.
"""
from __future__ import annotations

import datetime
from typing import Optional

import numpy as np
import pandas as pd

from config import INDICES, IST
from data.upstox_client import UpstoxClient, UpstoxAPIError, UpstoxAuthError


def _sample_intraday(symbol: str, interval: str = "1minute") -> pd.DataFrame:
    from config import INDICES
    spot_map = {
        "NIFTY": 22500, "BANKNIFTY": 48200, "SENSEX": 74000,
        "FINNIFTY": 22100, "MIDCPNIFTY": 11800,
    }
    base = float(spot_map.get(symbol, 22500))
    now = datetime.datetime.now(IST).replace(tzinfo=None)
    start = now.replace(hour=9, minute=15, second=0, microsecond=0)
    mins_elapsed = max(int((now - start).total_seconds() / 60), 30)

    if interval == "1minute":
        n = min(mins_elapsed, 375)
    else:
        n = min(mins_elapsed // 5, 75)

    rng = np.random.default_rng(42)
    log_rets = rng.normal(0, 0.0004, n)
    closes = base * np.exp(np.cumsum(log_rets))
    highs  = closes * (1 + np.abs(rng.normal(0, 0.0002, n)))
    lows   = closes * (1 - np.abs(rng.normal(0, 0.0002, n)))
    opens  = np.concatenate([[base], closes[:-1]])
    vols   = rng.integers(30_000, 150_000, n).astype(float)

    freq = "1min" if interval == "1minute" else "5min"
    times = pd.date_range(start=start, periods=n, freq=freq)
    return pd.DataFrame({
        "timestamp": times,
        "open": opens, "high": highs, "low": lows, "close": closes, "volume": vols,
    })


def fetch_intraday(
    symbol: str,
    client: Optional[UpstoxClient],
    interval: str = "1minute",
) -> pd.DataFrame:
    """
    Fetch today's intraday OHLCV and compute VWAP, 9-EMA, 21-EMA.
    Falls back to sample data when client is None or API returns empty.
    """
    cfg = INDICES[symbol]
    today = datetime.date.today().strftime("%Y-%m-%d")

    df = pd.DataFrame()
    if client is not None:
        try:
            candles = client.get_historical_candles(cfg.instrument_key, interval, today, today)
            if candles:
                df = pd.DataFrame(
                    candles,
                    columns=["timestamp", "open", "high", "low", "close", "volume", "oi"],
                )
                df = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df = df.sort_values("timestamp").reset_index(drop=True)
        except (UpstoxAuthError, UpstoxAPIError):
            pass

    if df.empty:
        df = _sample_intraday(symbol, interval)

    # VWAP: cumulative (typical_price × volume) / cumulative volume
    df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3
    cumvol = df["volume"].cumsum()
    df["vwap"] = (df["typical_price"] * df["volume"]).cumsum() / cumvol.replace(0, np.nan)

    df["ema9"]  = df["close"].ewm(span=9,  adjust=False).mean()
    df["ema21"] = df["close"].ewm(span=21, adjust=False).mean()

    return df
