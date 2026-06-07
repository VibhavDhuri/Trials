"""
WebSocket price client — reads from the shared ws_prices.json cache written by ws_streamer.py.
Pages import this to get real-time prices without connecting to WebSocket directly.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from store.local_store import load

MAX_STALE_SECONDS = 10


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _age_seconds(ts: str) -> float:
    dt = _parse_iso(ts)
    if dt is None:
        return float("inf")
    return (_utcnow() - dt).total_seconds()


class WSPriceClient:
    def get_ltp(self, instrument_key: str) -> float | None:
        prices = load("ws_prices", {})
        entry = prices.get(instrument_key)
        if not entry:
            return None
        updated_at = entry.get("updated_at", "")
        if _age_seconds(updated_at) > MAX_STALE_SECONDS:
            return None
        ltp = entry.get("ltp")
        return float(ltp) if ltp is not None else None

    def get_all_ltps(self) -> dict[str, float]:
        prices = load("ws_prices", {})
        result: dict[str, float] = {}
        for key, entry in prices.items():
            updated_at = entry.get("updated_at", "")
            if _age_seconds(updated_at) <= MAX_STALE_SECONDS:
                ltp = entry.get("ltp")
                if ltp is not None:
                    result[key] = float(ltp)
        return result

    def is_connected(self) -> bool:
        status_data = load("ws_status", {})
        if status_data.get("status") != "CONNECTED":
            return False
        ts = status_data.get("timestamp", "")
        return _age_seconds(ts) <= 30

    def connection_status(self) -> str:
        status_data = load("ws_status", {})
        if not status_data:
            return "NOT_STARTED"
        return status_data.get("status", "NOT_STARTED")

    def get_price_info(self, instrument_key: str) -> dict | None:
        prices = load("ws_prices", {})
        entry = prices.get(instrument_key)
        if not entry:
            return None
        updated_at = entry.get("updated_at", "")
        if _age_seconds(updated_at) > MAX_STALE_SECONDS:
            return None
        return {
            "ltp": entry.get("ltp"),
            "change_pct": entry.get("change_pct"),
            "timestamp": entry.get("timestamp"),
            "updated_at": updated_at,
        }


_ws_client = WSPriceClient()


def get_ltp(instrument_key: str) -> float | None:
    return _ws_client.get_ltp(instrument_key)


def is_streaming() -> bool:
    return _ws_client.is_connected()


def streaming_status() -> str:
    return _ws_client.connection_status()
