"""
Options chain aggregator.
Fetches chains for the nearest N expiries and parses them into a flat DataFrame.
"""
from __future__ import annotations

import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config import INDICES, IST
from data.upstox_client import UpstoxClient, UpstoxAuthError, UpstoxAPIError
from data.sample_data import get_sample_option_chain
from utils.helpers import generate_expiry_dates, days_to_expiry, trading_days_to_expiry

# Fetch at most this many expiries on initial load (nearest → longest dated)
MAX_LIVE_EXPIRIES = 8


class OptionsChainFetcher:
    def __init__(self, client: Optional[UpstoxClient], offline: bool = False) -> None:
        self._client = client
        self._offline = offline
        self._expiry_cache: Dict[str, List[str]] = {}

    def get_expiries(self, symbol: str) -> List[str]:
        """Return sorted list of available expiry date strings for the symbol."""
        if symbol in self._expiry_cache:
            return self._expiry_cache[symbol]
        cfg = INDICES[symbol]
        all_dates = generate_expiry_dates(cfg.expiry_weekday, cfg.holiday_set, months_ahead=13)
        if self._offline or self._client is None:
            # In offline mode, return up to 20 nearest expiries
            self._expiry_cache[symbol] = all_dates[:20]
            return self._expiry_cache[symbol]

        # Validate expiries against live API (batched, respects rate limits)
        valid: List[str] = []
        for date in all_dates[:MAX_LIVE_EXPIRIES]:
            try:
                rows = self._client.get_option_chain(cfg.instrument_key, date)
                if rows:
                    valid.append(date)
            except (UpstoxAuthError, UpstoxAPIError):
                pass  # network blip — skip this expiry for now
        self._expiry_cache[symbol] = valid or all_dates[:6]
        return self._expiry_cache[symbol]

    def get_chain_df(self, symbol: str, expiry_date: str, spot: float) -> pd.DataFrame:
        """
        Returns a flat DataFrame with one row per strike × option_type.
        Columns: strike, opt_type, expiry, dte_calendar, dte_trading,
                 ltp, bid, ask, spread_pct, oi, prev_oi, oi_chg, oi_chg_pct,
                 volume, vol_oi_ratio, iv, delta, gamma, theta, vega,
                 lot_size, margin_est
        """
        raw = self._fetch_raw(symbol, expiry_date)
        if not raw:
            return pd.DataFrame()

        cfg = INDICES[symbol]
        lot_size = cfg.lot_size
        t_cal = days_to_expiry(expiry_date)
        t_trd = trading_days_to_expiry(expiry_date)

        rows: List[Dict] = []
        for entry in raw:
            K = float(entry.get("strike_price", 0))
            for side, key in (("CE", "call_options"), ("PE", "put_options")):
                opt = entry.get(key, {})
                if not opt:
                    continue
                md = opt.get("market_data", {})
                gr = opt.get("option_greeks", {})

                ltp = float(md.get("ltp", 0) or 0)
                bid = float(md.get("bid_price", 0) or 0)
                ask = float(md.get("ask_price", 0) or 0)
                oi = int(md.get("oi", 0) or 0)
                prev_oi = int(md.get("prev_oi", 0) or 0)
                vol = int(md.get("volume", 0) or 0)

                spread_pct = (ask - bid) / ltp * 100 if ltp > 0 else 0.0
                oi_chg = oi - prev_oi
                oi_chg_pct = oi_chg / prev_oi * 100 if prev_oi > 0 else 0.0
                vol_oi = vol / oi if oi > 0 else 0.0

                iv_pct = float(gr.get("iv", 0) or 0)  # API returns as percentage

                rows.append({
                    "strike": K,
                    "opt_type": side,
                    "expiry": expiry_date,
                    "dte_calendar": t_cal * 365.25,   # calendar days as float
                    "dte_trading": t_trd,
                    "ltp": ltp,
                    "bid": bid,
                    "ask": ask,
                    "spread_pct": round(spread_pct, 2),
                    "oi": oi,
                    "prev_oi": prev_oi,
                    "oi_chg": oi_chg,
                    "oi_chg_pct": round(oi_chg_pct, 2),
                    "volume": vol,
                    "vol_oi_ratio": round(vol_oi, 4),
                    "iv": iv_pct,                      # percentage (e.g. 15.5)
                    "iv_frac": iv_pct / 100.0,         # fraction for BS calcs
                    "delta": float(gr.get("delta", 0) or 0),
                    "gamma": float(gr.get("gamma", 0) or 0),
                    "theta": float(gr.get("theta", 0) or 0),
                    "vega": float(gr.get("vega", 0) or 0),
                    "spot": spot,
                    "lot_size": lot_size,
                    "margin_est": ltp * lot_size,  # rough: LTP × lot size for buyer
                    "close_price": float(md.get("close_price", 0) or 0),
                    "high": float(md.get("high", 0) or 0),
                    "low": float(md.get("low", 0) or 0),
                })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["moneyness"] = (df["strike"] - spot) / spot
        df["atm_distance"] = (df["strike"] - spot).abs()
        return df.sort_values(["strike", "opt_type"]).reset_index(drop=True)

    def _fetch_raw(self, symbol: str, expiry_date: str) -> List[Dict]:
        if self._offline or self._client is None:
            return get_sample_option_chain(symbol, expiry_date)
        cfg = INDICES[symbol]
        try:
            return self._client.get_option_chain(cfg.instrument_key, expiry_date)
        except UpstoxAuthError:
            return get_sample_option_chain(symbol, expiry_date)
        except UpstoxAPIError:
            return get_sample_option_chain(symbol, expiry_date)
