"""
Order manager — wraps Upstox order API.

Live trading is DISABLED by default (UPSTOX_ENABLE_TRADING=false in .env).
In paper mode, orders are simulated via the PositionTracker without any API call.

To enable live trading: set UPSTOX_ENABLE_TRADING=true in .env.
WARNING: Live orders execute immediately with real money. Test thoroughly in paper mode first.
"""
from __future__ import annotations

import os
from typing import Optional

import requests

from config import UPSTOX_API_BASE
from data.upstox_client import UpstoxAuthError, UpstoxAPIError, _throttle
from positions.tracker import add_position, Position


def is_live_trading_enabled() -> bool:
    return os.getenv("UPSTOX_ENABLE_TRADING", "false").lower() == "true"


class OrderManager:
    def __init__(self, access_token: str) -> None:
        self._token = access_token

    def place_order(
        self,
        instrument_key: str,
        quantity: int,
        price: float,
        order_type: str,        # "MARKET" | "LIMIT"
        transaction_type: str,  # "BUY" | "SELL"
        product: str = "I",     # "I" = intraday, "D" = delivery
        validity: str = "DAY",
    ) -> dict:
        """
        Place a live order via Upstox API.
        Raises UpstoxAuthError / UpstoxAPIError on failure.
        Only called when UPSTOX_ENABLE_TRADING=true.
        """
        _throttle()
        url = f"{UPSTOX_API_BASE}/order/place"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        payload = {
            "quantity": quantity,
            "product": product,
            "validity": validity,
            "price": price if order_type == "LIMIT" else 0,
            "tag": "options_signals_app",
            "instrument_token": instrument_key,
            "order_type": order_type,
            "transaction_type": transaction_type,
            "disclosed_quantity": 0,
            "trigger_price": 0,
            "is_amo": False,
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=12)
        if resp.status_code == 401:
            raise UpstoxAuthError("Token expired — refresh UPSTOX_ACCESS_TOKEN in .env")
        if resp.status_code != 200:
            raise UpstoxAPIError(f"Order failed: HTTP {resp.status_code} — {resp.text[:200]}")
        data = resp.json()
        if data.get("status") != "success":
            raise UpstoxAPIError(f"Order rejected: {data}")
        return data.get("data", {})

    def get_order_status(self, order_id: str) -> dict:
        _throttle()
        url = f"{UPSTOX_API_BASE}/order/details"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        resp = requests.get(url, headers=headers, params={"order_id": order_id}, timeout=10)
        if resp.status_code != 200:
            raise UpstoxAPIError(f"HTTP {resp.status_code}")
        return resp.json().get("data", {})

    def cancel_order(self, order_id: str) -> bool:
        _throttle()
        url = f"{UPSTOX_API_BASE}/order/cancel"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        resp = requests.delete(url, headers=headers, params={"order_id": order_id}, timeout=10)
        return resp.status_code == 200


def execute_paper_or_live(
    manager: Optional[OrderManager],
    instrument_key: str,
    symbol: str,
    expiry: str,
    strike: float,
    opt_type: str,
    action: str,
    quantity: int,
    ltp: float,
    strategy_tag: str = "",
    source: str = "MANUAL",
) -> tuple[str, Optional[Position]]:
    """
    Route to live API or paper simulation depending on env flag.
    Returns (mode_used, position_or_None).
    """
    if is_live_trading_enabled() and manager is not None:
        order = manager.place_order(
            instrument_key=instrument_key,
            quantity=quantity,
            price=ltp,
            order_type="MARKET",
            transaction_type=action,
        )
        # Also add to position tracker for live monitoring
        pos = add_position(symbol, expiry, strike, opt_type, action, quantity,
                           ltp, source=source, strategy_tag=strategy_tag)
        return "LIVE", pos
    else:
        # Paper mode: simulate at current LTP
        pos = add_position(symbol, expiry, strike, opt_type, action, quantity,
                           ltp, source=source, strategy_tag=strategy_tag)
        return "PAPER", pos
