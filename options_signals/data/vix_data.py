"""
India VIX fetcher via Upstox market quotes.
VIX measures 30-day expected annualised volatility of Nifty 50.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Optional

from data.upstox_client import UpstoxClient

VIX_INSTRUMENT_KEY = "NSE_INDEX|India VIX"


@dataclass
class VIXData:
    current: float
    prev_close: float
    day_change_pct: float
    week_high: float
    week_low: float


_SAMPLE = VIXData(
    current=14.5,
    prev_close=14.2,
    day_change_pct=2.1,
    week_high=16.8,
    week_low=13.2,
)


def get_vix(client: Optional[UpstoxClient]) -> VIXData:
    if client is None:
        return _SAMPLE
    try:
        quotes = client.get_market_quotes([VIX_INSTRUMENT_KEY])
        data = quotes.get(VIX_INSTRUMENT_KEY) or quotes.get(
            VIX_INSTRUMENT_KEY.replace("|", ":"), {}
        )
        if not data:
            for v in quotes.values():
                data = v
                break
        last_price: float = float(data.get("last_price", 0))
        close_price: float = float(data.get("close_price", 1))
        week_high: float = float(data.get("52_week_high", last_price))
        week_low: float = float(data.get("52_week_low", last_price))
        if close_price == 0:
            close_price = 1.0
        day_change_pct = (last_price / close_price - 1) * 100
        return VIXData(
            current=last_price,
            prev_close=close_price,
            day_change_pct=day_change_pct,
            week_high=week_high,
            week_low=week_low,
        )
    except Exception:
        return _SAMPLE


def interpret_vix(vix_val: float) -> tuple[str, str]:
    if vix_val < 12:
        return ("COMPLACENT", "green")
    elif vix_val <= 20:
        return ("NORMAL", "orange")
    else:
        return ("FEAR", "red")


def expected_daily_move_pct(vix_val: float) -> float:
    return vix_val / sqrt(252)
