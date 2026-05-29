"""
Market hours, expiry date generation (with holiday adjustment),
and shared helper utilities.
"""
from __future__ import annotations

import datetime
from typing import List
from config import IST, MARKET_OPEN_HOUR, MARKET_OPEN_MIN, MARKET_CLOSE_HOUR, MARKET_CLOSE_MIN


def now_ist() -> datetime.datetime:
    return datetime.datetime.now(IST)


def is_market_open() -> bool:
    now = now_ist()
    if now.weekday() >= 5:  # Saturday, Sunday
        return False
    open_dt = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MIN, second=0, microsecond=0)
    close_dt = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MIN, second=0, microsecond=0)
    return open_dt <= now <= close_dt


def is_pre_market() -> bool:
    now = now_ist()
    if now.weekday() >= 5:
        return False
    open_dt = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MIN, second=0, microsecond=0)
    pre_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
    return pre_open <= now < open_dt


def market_status() -> str:
    if is_market_open():
        return "LIVE"
    if is_pre_market():
        return "PRE-OPEN"
    return "CLOSED"


def days_to_expiry(expiry_date: str) -> float:
    """Calendar days remaining to expiry as a fraction (for BS T in years)."""
    exp = datetime.datetime.strptime(expiry_date, "%Y-%m-%d").replace(tzinfo=IST)
    exp = exp.replace(hour=15, minute=30)  # options expire at 3:30 PM IST
    now = now_ist()
    diff = (exp - now).total_seconds()
    return max(diff / (365.25 * 24 * 3600), 0.0)


def trading_days_to_expiry(expiry_date: str) -> int:
    """Approximate trading days remaining (used for theta display)."""
    exp = datetime.datetime.strptime(expiry_date, "%Y-%m-%d").date()
    today = now_ist().date()
    count = 0
    cur = today
    while cur < exp:
        if cur.weekday() < 5:
            count += 1
        cur += datetime.timedelta(days=1)
    return count


def _prev_trading_day(d: datetime.date, holidays: frozenset) -> datetime.date:
    """Step back until we land on a non-weekend, non-holiday trading day."""
    d -= datetime.timedelta(days=1)
    while d.weekday() >= 5 or d.strftime("%Y-%m-%d") in holidays:
        d -= datetime.timedelta(days=1)
    return d


def generate_expiry_dates(
    expiry_weekday: int,
    holidays: frozenset,
    months_ahead: int = 13,
) -> List[str]:
    """
    Generate all weekly + monthly expiry dates for the given weekday
    over the next `months_ahead` months, adjusting for holidays.

    expiry_weekday: 0=Mon,1=Tue,2=Wed,3=Thu,4=Fri
    Returns sorted list of 'YYYY-MM-DD' strings (deduplicated).
    """
    today = now_ist().date()
    end_date = today + datetime.timedelta(days=30 * months_ahead)

    expiries: set[str] = set()

    cur = today
    while cur <= end_date:
        if cur.weekday() == expiry_weekday:
            candidate = cur
            # Shift back if it falls on a holiday
            date_str = candidate.strftime("%Y-%m-%d")
            while candidate.weekday() >= 5 or date_str in holidays:
                candidate = _prev_trading_day(candidate, holidays)
                date_str = candidate.strftime("%Y-%m-%d")
            if candidate >= today:
                expiries.add(date_str)
        cur += datetime.timedelta(days=1)

    return sorted(expiries)


def format_change(value: float, prev: float) -> str:
    if prev == 0:
        return "N/A"
    pct = (value - prev) / prev * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"


def format_inr(value: float, decimals: int = 2) -> str:
    return f"₹{value:,.{decimals}f}"


def dte_label(expiry_date: str) -> str:
    """Human-readable DTE label: '0DTE', '3d', '15d', '2m 3d'."""
    tdays = trading_days_to_expiry(expiry_date)
    if tdays == 0:
        return "0DTE"
    if tdays < 5:
        return f"{tdays}d"
    weeks = tdays // 5
    rem_days = tdays % 5
    if weeks < 4:
        return f"{weeks}w {rem_days}d" if rem_days else f"{weeks}w"
    months = weeks // 4
    rem_weeks = weeks % 4
    if rem_weeks:
        return f"{months}m {rem_weeks}w"
    return f"{months}m"
