"""
Economic and events calendar for options traders.
Hardcoded 2025-2026 key dates with impact levels.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Optional

from config import NSE_HOLIDAYS_2025, INDICES


@dataclass
class Event:
    date: datetime.date
    event_type: str
    description: str
    impact: str
    symbol: Optional[str] = None


_STATIC_EVENTS: list[Event] = [
    Event(datetime.date(2025, 2, 7),  "RBI_MPC", "RBI MPC Decision",     "HIGH"),
    Event(datetime.date(2025, 4, 9),  "RBI_MPC", "RBI MPC Decision",     "HIGH"),
    Event(datetime.date(2025, 6, 6),  "RBI_MPC", "RBI MPC Decision",     "HIGH"),
    Event(datetime.date(2025, 8, 6),  "RBI_MPC", "RBI MPC Decision",     "HIGH"),
    Event(datetime.date(2025, 10, 1), "RBI_MPC", "RBI MPC Decision",     "HIGH"),
    Event(datetime.date(2025, 12, 5), "RBI_MPC", "RBI MPC Decision",     "HIGH"),
    Event(datetime.date(2026, 2, 4),  "RBI_MPC", "RBI MPC Decision",     "HIGH"),
    Event(datetime.date(2026, 4, 8),  "RBI_MPC", "RBI MPC Decision",     "HIGH"),
    Event(datetime.date(2026, 6, 3),  "RBI_MPC", "RBI MPC Decision",     "HIGH"),
    Event(datetime.date(2026, 8, 5),  "RBI_MPC", "RBI MPC Decision",     "HIGH"),
    Event(datetime.date(2025, 1, 29), "US_FED",  "US Fed FOMC Decision", "HIGH"),
    Event(datetime.date(2025, 3, 19), "US_FED",  "US Fed FOMC Decision", "HIGH"),
    Event(datetime.date(2025, 5, 7),  "US_FED",  "US Fed FOMC Decision", "HIGH"),
    Event(datetime.date(2025, 6, 18), "US_FED",  "US Fed FOMC Decision", "HIGH"),
    Event(datetime.date(2025, 7, 30), "US_FED",  "US Fed FOMC Decision", "HIGH"),
    Event(datetime.date(2025, 9, 17), "US_FED",  "US Fed FOMC Decision", "HIGH"),
    Event(datetime.date(2025, 10, 29),"US_FED",  "US Fed FOMC Decision", "HIGH"),
    Event(datetime.date(2025, 12, 10),"US_FED",  "US Fed FOMC Decision", "HIGH"),
    Event(datetime.date(2026, 1, 28), "US_FED",  "US Fed FOMC Decision", "HIGH"),
    Event(datetime.date(2026, 3, 18), "US_FED",  "US Fed FOMC Decision", "HIGH"),
    Event(datetime.date(2026, 5, 6),  "US_FED",  "US Fed FOMC Decision", "HIGH"),
    Event(datetime.date(2026, 6, 17), "US_FED",  "US Fed FOMC Decision", "HIGH"),
    Event(datetime.date(2025, 1, 9),  "EARNINGS", "TCS Q3 Results",           "MEDIUM", "TCS"),
    Event(datetime.date(2025, 4, 10), "EARNINGS", "TCS Q4 Results",           "MEDIUM", "TCS"),
    Event(datetime.date(2025, 7, 10), "EARNINGS", "TCS Q1 Results",           "MEDIUM", "TCS"),
    Event(datetime.date(2025, 10, 9), "EARNINGS", "TCS Q2 Results",           "MEDIUM", "TCS"),
    Event(datetime.date(2025, 1, 16), "EARNINGS", "Infosys Q3 Results",       "MEDIUM", "INFY"),
    Event(datetime.date(2025, 4, 17), "EARNINGS", "Infosys Q4 Results",       "MEDIUM", "INFY"),
    Event(datetime.date(2025, 7, 17), "EARNINGS", "Infosys Q1 Results",       "MEDIUM", "INFY"),
    Event(datetime.date(2025, 10, 16),"EARNINGS", "Infosys Q2 Results",       "MEDIUM", "INFY"),
    Event(datetime.date(2025, 1, 16), "EARNINGS", "Reliance Q3 Results",      "MEDIUM", "RELIANCE"),
    Event(datetime.date(2025, 4, 24), "EARNINGS", "Reliance Q4 Results",      "MEDIUM", "RELIANCE"),
    Event(datetime.date(2025, 7, 18), "EARNINGS", "Reliance Q1 Results",      "MEDIUM", "RELIANCE"),
    Event(datetime.date(2025, 10, 14),"EARNINGS", "Reliance Q2 Results",      "MEDIUM", "RELIANCE"),
    Event(datetime.date(2025, 1, 22), "EARNINGS", "HDFC Bank Q3 Results",     "MEDIUM", "HDFCBANK"),
    Event(datetime.date(2025, 4, 19), "EARNINGS", "HDFC Bank Q4 Results",     "MEDIUM", "HDFCBANK"),
    Event(datetime.date(2025, 7, 19), "EARNINGS", "HDFC Bank Q1 Results",     "MEDIUM", "HDFCBANK"),
    Event(datetime.date(2025, 10, 18),"EARNINGS", "HDFC Bank Q2 Results",     "MEDIUM", "HDFCBANK"),
    Event(datetime.date(2025, 1, 25), "EARNINGS", "ICICI Bank Q3 Results",    "MEDIUM", "ICICIBANK"),
    Event(datetime.date(2025, 4, 26), "EARNINGS", "ICICI Bank Q4 Results",    "MEDIUM", "ICICIBANK"),
    Event(datetime.date(2025, 7, 26), "EARNINGS", "ICICI Bank Q1 Results",    "MEDIUM", "ICICIBANK"),
    Event(datetime.date(2025, 10, 25),"EARNINGS", "ICICI Bank Q2 Results",    "MEDIUM", "ICICIBANK"),
]

for _hdate_str in NSE_HOLIDAYS_2025:
    _hdate = datetime.date.fromisoformat(_hdate_str)
    _STATIC_EVENTS.append(Event(_hdate, "HOLIDAY", "NSE Holiday", "LOW"))


def _generate_expiry_events(days_ahead: int) -> list[Event]:
    today = datetime.date.today()
    end = today + datetime.timedelta(days=days_ahead + 90)
    events: list[Event] = []
    weekday_map = {sym: cfg.expiry_weekday for sym, cfg in INDICES.items()}
    label_map = {sym: cfg.display_name for sym, cfg in INDICES.items()}
    holiday_set = set(NSE_HOLIDAYS_2025)

    current = today
    while current <= end:
        for sym, weekday in weekday_map.items():
            if current.weekday() == weekday:
                expiry_date = current
                while expiry_date.isoformat() in holiday_set:
                    expiry_date -= datetime.timedelta(days=1)
                events.append(
                    Event(
                        date=expiry_date,
                        event_type="FO_EXPIRY",
                        description=f"{label_map[sym]} F&O Expiry",
                        impact="LOW",
                        symbol=sym,
                    )
                )
        current += datetime.timedelta(days=1)
    return events


def get_upcoming_events(days_ahead: int = 30) -> list[Event]:
    today = datetime.date.today()
    end = today + datetime.timedelta(days=days_ahead)
    expiry_events = _generate_expiry_events(days_ahead)
    all_events = _STATIC_EVENTS + expiry_events
    filtered = [e for e in all_events if today <= e.date <= end]
    filtered.sort(key=lambda e: e.date)
    return filtered


def get_events_in_month(year: int, month: int) -> list[Event]:
    start = datetime.date(year, month, 1)
    if month == 12:
        end = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        end = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    expiry_events = _generate_expiry_events(120)
    all_events = _STATIC_EVENTS + expiry_events
    filtered = [e for e in all_events if start <= e.date <= end]
    filtered.sort(key=lambda e: e.date)
    return filtered


def get_next_n_events(n: int = 3) -> list[Event]:
    today = datetime.date.today()
    expiry_events = _generate_expiry_events(180)
    all_events = _STATIC_EVENTS + expiry_events
    future = [e for e in all_events if e.date >= today]
    future.sort(key=lambda e: e.date)
    return future[:n]
