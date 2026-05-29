"""
Upstox v2 REST API client with retry, rate limiting, and 401 detection.
All public methods return parsed dicts or raise UpstoxAuthError / UpstoxAPIError.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import requests

from config import UPSTOX_API_BASE


class UpstoxAuthError(Exception):
    """Raised when the access token is missing, expired, or invalid."""


class UpstoxAPIError(Exception):
    """Raised for non-auth API errors."""


_DEFAULT_HEADERS = {"Accept": "application/json"}
_MIN_REQUEST_INTERVAL = 0.35  # seconds between requests (~3 req/s)
_last_request_time: float = 0.0


def _throttle() -> None:
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.monotonic()


def _get(path: str, token: str, params: Optional[Dict] = None, retries: int = 3) -> Dict:
    _throttle()
    url = f"{UPSTOX_API_BASE}{path}"
    headers = {**_DEFAULT_HEADERS, "Authorization": f"Bearer {token}"}
    last_exc: Optional[Exception] = None

    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=12)
        except requests.Timeout as e:
            last_exc = e
            time.sleep(2 ** attempt)
            continue
        except requests.RequestException as e:
            raise UpstoxAPIError(f"Request failed: {e}") from e

        if resp.status_code == 401:
            raise UpstoxAuthError(
                "Upstox token is expired or invalid. "
                "Run  python auth/upstox_auth.py  and refresh UPSTOX_ACCESS_TOKEN in .env"
            )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            time.sleep(retry_after)
            continue
        if resp.status_code != 200:
            raise UpstoxAPIError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        payload = resp.json()
        if payload.get("status") != "success":
            raise UpstoxAPIError(f"API error: {payload}")
        return payload.get("data", payload)

    raise UpstoxAPIError(f"All {retries} retries failed: {last_exc}")


class UpstoxClient:
    def __init__(self, access_token: str) -> None:
        self._token = access_token

    def get_market_quotes(self, instrument_keys: List[str]) -> Dict[str, Any]:
        """
        Fetch LTP and OHLC for a list of instrument keys.
        Returns: { instrument_key: { last_price, ohlc, net_change, ... } }
        """
        symbol_param = ",".join(instrument_keys)
        return _get("/market-quote/quotes", self._token, {"symbol": symbol_param})

    def get_option_chain(self, instrument_key: str, expiry_date: str) -> List[Dict]:
        """
        Fetch options chain for one expiry date (YYYY-MM-DD).
        Returns list of strike dicts with call_options, put_options, Greeks.
        Returns [] if this expiry doesn't exist on the exchange.
        """
        try:
            data = _get(
                "/option/chain",
                self._token,
                {"instrument_key": instrument_key, "expiry_date": expiry_date},
            )
            return data if isinstance(data, list) else []
        except UpstoxAPIError as e:
            if "404" in str(e) or "not found" in str(e).lower():
                return []
            raise

    def get_historical_candles(
        self,
        instrument_key: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> List[List]:
        """
        Fetch OHLCV candles.
        interval: '1minute' | '30minute' | 'day' | 'week' | 'month'
        Returns list of [timestamp, open, high, low, close, volume, oi] rows.
        """
        encoded_key = instrument_key.replace("|", "%7C")
        path = f"/historical-candle/{encoded_key}/{interval}/{to_date}/{from_date}"
        data = _get(path, self._token)
        candles = data.get("candles", []) if isinstance(data, dict) else []
        if len(candles) < 5:
            # Upstox returns 200 with empty candles for instruments with no history
            return []
        return candles
