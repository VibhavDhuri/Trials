"""
Upstox WebSocket v3 market data streamer.
Connects to wss://api.upstox.com/v3/feeds/market-data-streamer/ws
Writes live prices to data_store/ws_prices.json every ~1 second.

Run standalone: python data/ws_streamer.py [--token TOKEN] [--instruments "NSE_INDEX|Nifty 50,NSE_INDEX|Nifty Bank"]

Requires: pip install websocket-client
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    import websocket
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from store.local_store import load, save
from config import UPSTOX_API_BASE, INDICES

WS_URL = "wss://api.upstox.com/v3/feeds/market-data-streamer/ws"
_PRICE_KEY = "ws_prices"
_STATUS_KEY = "ws_status"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_status(status: str) -> None:
    save(_STATUS_KEY, {"status": status, "timestamp": _now_iso()})


class PriceCache:
    def update(self, instrument_key: str, ltp: float, change_pct: float, timestamp: str) -> None:
        prices = load(_PRICE_KEY, {})
        prices[instrument_key] = {
            "ltp": ltp,
            "change_pct": change_pct,
            "timestamp": timestamp,
            "updated_at": _now_iso(),
        }
        save(_PRICE_KEY, prices)

    def get(self, instrument_key: str) -> dict | None:
        prices = load(_PRICE_KEY, {})
        return prices.get(instrument_key)

    def get_all(self) -> dict:
        return load(_PRICE_KEY, {})


class UpstoxStreamer:
    def __init__(self, access_token: str, instrument_keys: list[str]) -> None:
        self._token = access_token
        self._keys = instrument_keys
        self._cache = PriceCache()

    def _get_ws_auth_url(self) -> str:
        url = f"{UPSTOX_API_BASE}/feed/market-data-feed/authorize"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=10)
        if not resp.ok:
            raise ValueError(f"Auth failed: {resp.status_code} {resp.text}")
        data = resp.json()
        try:
            return data["data"]["authorizedRedirectUri"]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Unexpected auth response: {data}") from exc

    def _on_message(self, ws, message) -> None:
        try:
            if isinstance(message, bytes):
                text = message.decode("utf-8")
            else:
                text = message
            payload = json.loads(text)
            feeds = payload.get("feeds", {})
            for instrument_key, feed_data in feeds.items():
                full_feed = feed_data.get("ff", {}) or feed_data.get("fullFeed", {})
                market_ff = full_feed.get("marketFF", {}) or full_feed.get("market_ff", {})
                ltpc = market_ff.get("ltpc", {})
                ltp = float(ltpc.get("ltp", 0))
                cp = float(ltpc.get("cp", ltp))
                change_pct = ((ltp - cp) / cp * 100) if cp else 0.0
                ts = str(ltpc.get("ltt", _now_iso()))
                self._cache.update(instrument_key, ltp, change_pct, ts)
                print(f"[{_now_iso()}] {instrument_key}: ltp={ltp}, chg%={change_pct:.2f}")
        except Exception as exc:
            print(f"[{_now_iso()}] Message parse error: {exc}")

    def _on_error(self, ws, error) -> None:
        print(f"[{_now_iso()}] WebSocket error: {error}")
        _write_status("ERROR")

    def _on_close(self, ws, close_status, close_msg) -> None:
        print(f"[{_now_iso()}] WebSocket disconnected: {close_status} {close_msg}")
        _write_status("DISCONNECTED")

    def _on_open(self, ws) -> None:
        sub_msg = json.dumps({
            "guid": "stream1",
            "method": "sub",
            "data": {
                "mode": "full",
                "instrumentKeys": self._keys,
            },
        })
        ws.send(sub_msg)
        _write_status("CONNECTED")
        print(f"[{_now_iso()}] WebSocket connected, subscribed to {self._keys}")

    def connect(self) -> None:
        if not HAS_WEBSOCKET:
            raise ImportError("websocket-client is not installed. Run: pip install websocket-client")
        auth_url = self._get_ws_auth_url()
        ws_app = websocket.WebSocketApp(
            auth_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        ws_app.run_forever(ping_interval=30, ping_timeout=10)

    def connect_with_retry(self, max_retries: int = 10) -> None:
        if not HAS_WEBSOCKET:
            raise ImportError("websocket-client is not installed. Run: pip install websocket-client")
        for attempt in range(max_retries):
            try:
                self.connect()
            except Exception as exc:
                print(f"[{_now_iso()}] Connection attempt {attempt + 1} failed: {exc}")
            if attempt < max_retries - 1:
                delay = min(2 ** attempt, 60)
                _write_status("RECONNECTING")
                print(f"[{_now_iso()}] Retrying in {delay}s (attempt {attempt + 2}/{max_retries})")
                time.sleep(delay)
        _write_status("DISCONNECTED")
        print(f"[{_now_iso()}] Max retries ({max_retries}) reached. Giving up.")


if __name__ == "__main__":
    default_keys = [cfg.instrument_key for cfg in INDICES.values()]

    parser = argparse.ArgumentParser(description="Upstox WebSocket market data streamer")
    parser.add_argument(
        "--token",
        default=os.environ.get("UPSTOX_ACCESS_TOKEN", ""),
        help="Upstox access token (or set UPSTOX_ACCESS_TOKEN env var)",
    )
    parser.add_argument(
        "--instruments",
        default=",".join(default_keys),
        help="Comma-separated instrument keys to subscribe to",
    )
    args = parser.parse_args()

    if not args.token:
        print("Error: --token is required or set UPSTOX_ACCESS_TOKEN environment variable")
        sys.exit(1)

    keys = [k.strip() for k in args.instruments.split(",") if k.strip()]
    streamer = UpstoxStreamer(access_token=args.token, instrument_keys=keys)

    try:
        streamer.connect_with_retry()
    except KeyboardInterrupt:
        _write_status("DISCONNECTED")
        print(f"\n[{_now_iso()}] Streamer stopped by user.")
        sys.exit(0)
