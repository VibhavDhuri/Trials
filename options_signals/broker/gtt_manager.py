"""
GTT (Good Till Triggered) order manager — wraps Upstox GTT API.
In paper mode (UPSTOX_ENABLE_TRADING=false), GTT orders are simulated locally.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

import requests

from config import UPSTOX_API_BASE
from store.local_store import load, save

_STORE_KEY = "gtts"


@dataclass
class GTTOrder:
    id: str
    position_id: str
    instrument_key: str
    trigger_price: float
    limit_price: float
    transaction_type: str
    quantity: int
    status: str
    created_at: str
    gtt_id: Optional[str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_live() -> bool:
    return os.getenv("UPSTOX_ENABLE_TRADING", "false").lower() == "true"


def load_gtts() -> list[GTTOrder]:
    raw: list[dict] = load(_STORE_KEY, [])
    result: list[GTTOrder] = []
    for item in raw:
        item.setdefault("gtt_id", None)
        result.append(GTTOrder(**item))
    return result


def save_gtts(gtts: list[GTTOrder]) -> None:
    save(_STORE_KEY, [asdict(g) for g in gtts])


class GTTManager:
    def __init__(self, access_token: str) -> None:
        self._token = access_token
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def place_gtt(
        self,
        instrument_key: str,
        trigger_price: float,
        limit_price: float,
        qty: int,
        transaction_type: str,
        position_id: str = "",
    ) -> GTTOrder:
        gtt_id: Optional[str] = None

        if _is_live():
            body = {
                "type": "SINGLE",
                "condition": {
                    "instrument_token": instrument_key,
                    "trigger_values": [trigger_price],
                    "last_traded_price": limit_price,
                },
                "orders": [
                    {
                        "quantity": qty,
                        "product": "I",
                        "order_type": "LIMIT",
                        "transaction_type": transaction_type,
                        "price": limit_price,
                        "instrument_token": instrument_key,
                    }
                ],
            }
            resp = requests.post(
                f"{UPSTOX_API_BASE}/gtt/place",
                json=body,
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            gtt_id = str(data.get("id", ""))

        order = GTTOrder(
            id=str(uuid.uuid4()),
            position_id=position_id,
            instrument_key=instrument_key,
            trigger_price=trigger_price,
            limit_price=limit_price,
            transaction_type=transaction_type,
            quantity=qty,
            status="PENDING",
            created_at=_now_iso(),
            gtt_id=gtt_id,
        )
        gtts = load_gtts()
        gtts.append(order)
        save_gtts(gtts)
        return order

    def cancel_gtt(self, gtt_id_or_local_id: str) -> bool:
        gtts = load_gtts()
        target: Optional[GTTOrder] = None
        for g in gtts:
            if g.id == gtt_id_or_local_id or g.gtt_id == gtt_id_or_local_id:
                target = g
                break

        if target is None:
            return False

        if _is_live() and target.gtt_id:
            try:
                resp = requests.delete(
                    f"{UPSTOX_API_BASE}/gtt/{target.gtt_id}",
                    headers=self._headers,
                    timeout=10,
                )
                resp.raise_for_status()
            except Exception:
                pass

        target.status = "CANCELLED"
        save_gtts(gtts)
        return True

    def list_gtts(self, position_id: Optional[str] = None) -> list[GTTOrder]:
        gtts = load_gtts()
        if position_id is not None:
            return [g for g in gtts if g.position_id == position_id]
        return gtts

    def check_paper_gtts(self, ltp_map: dict) -> list[GTTOrder]:
        gtts = load_gtts()
        triggered: list[GTTOrder] = []
        changed = False
        for g in gtts:
            if g.status != "PENDING" or _is_live():
                continue
            ltp = ltp_map.get(g.instrument_key)
            if ltp is None:
                continue
            hit = False
            if g.transaction_type == "SELL" and ltp <= g.trigger_price:
                hit = True
            elif g.transaction_type == "BUY" and ltp >= g.trigger_price:
                hit = True
            if hit:
                g.status = "TRIGGERED"
                triggered.append(g)
                changed = True
        if changed:
            save_gtts(gtts)
        return triggered
