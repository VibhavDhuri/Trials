"""
Underlying market data: spot price, OHLC, historical closes for HV calculation.
Falls back to sample data when offline.
"""
from __future__ import annotations

import datetime
from typing import Dict, Optional, Tuple

import numpy as np

import pandas as pd

from config import INDICES
from data.upstox_client import UpstoxClient, UpstoxAuthError, UpstoxAPIError
from data.sample_data import get_sample_market_quote, get_sample_historical_iv


class MarketDataFetcher:
    def __init__(self, client: Optional[UpstoxClient], offline: bool = False) -> None:
        self._client = client
        self._offline = offline

    def get_spot(self, symbol: str) -> Dict:
        """
        Returns:
            { last_price, ohlc: {open,high,low,close}, net_change, timestamp }
        """
        if self._offline or self._client is None:
            return get_sample_market_quote(symbol)
        cfg = INDICES[symbol]
        try:
            data = self._client.get_market_quotes([cfg.instrument_key])
            raw = data.get(cfg.instrument_key, {})
            return {
                "last_price": raw.get("last_price", 0.0),
                "ohlc": raw.get("ohlc", {}),
                "net_change": raw.get("net_change", 0.0),
                "volume": raw.get("volume", 0),
                "timestamp": raw.get("timestamp", datetime.datetime.now().isoformat()),
            }
        except (UpstoxAuthError, UpstoxAPIError):
            return get_sample_market_quote(symbol)

    def get_historical_iv_range(self, symbol: str) -> Tuple[float, float]:
        """
        Returns (iv_52w_high, iv_52w_low) as annualised fractions (not %).
        Computed from daily close returns over the past 252 trading days.
        Falls back to sample values when candles are insufficient.
        """
        if self._offline or self._client is None:
            return get_sample_historical_iv()

        cfg = INDICES[symbol]
        today = datetime.date.today()
        from_date = (today - datetime.timedelta(days=380)).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")

        try:
            candles = self._client.get_historical_candles(
                cfg.instrument_key, "day", from_date, to_date
            )
        except (UpstoxAuthError, UpstoxAPIError):
            return get_sample_historical_iv()

        if len(candles) < 30:
            return get_sample_historical_iv()

        # Candle format: [timestamp, open, high, low, close, volume, oi]
        closes = np.array([c[4] for c in candles], dtype=float)
        if len(closes) < 30:
            return get_sample_historical_iv()

        # Rolling 21-day HV (annualised) to find 52-week IV range proxy
        log_returns = np.diff(np.log(closes))
        window = 21
        rolling_hvs = [
            np.std(log_returns[i : i + window]) * np.sqrt(252)
            for i in range(len(log_returns) - window + 1)
        ]
        if not rolling_hvs:
            return get_sample_historical_iv()

        return max(rolling_hvs), min(rolling_hvs)

    def get_historical_closes(self, symbol: str, days: int = 80) -> Optional[pd.Series]:
        """
        Return a pd.Series of daily close prices (most recent last) for HV cone computation.
        Returns None on failure or in offline mode.
        """
        if self._offline or self._client is None:
            return None
        cfg = INDICES.get(symbol)
        if cfg is None:
            return None
        today = datetime.date.today()
        from_date = (today - datetime.timedelta(days=days + 30)).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")
        try:
            candles = self._client.get_historical_candles(
                cfg.instrument_key, "day", from_date, to_date
            )
            if len(candles) < 10:
                return None
            closes = pd.Series(
                [float(c[4]) for c in candles],
                index=pd.to_datetime([c[0][:10] for c in candles]),
            ).sort_index()
            return closes
        except (UpstoxAuthError, UpstoxAPIError):
            return None
