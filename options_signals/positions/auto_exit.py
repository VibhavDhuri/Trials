"""
Auto-exit rules — per-position target/stop-loss automation.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional, Any

from positions.tracker import Position
from store.local_store import load, save

_STORE_KEY = "auto_exits"


@dataclass
class AutoExitRule:
    id: str
    position_id: str
    target_pct: float
    stop_loss_pct: float
    trailing_stop: bool
    peak_ltp: Optional[float]
    status: str
    created_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_rules() -> list[AutoExitRule]:
    raw: list[dict] = load(_STORE_KEY, [])
    rules: list[AutoExitRule] = []
    for item in raw:
        item.setdefault("peak_ltp", None)
        rules.append(AutoExitRule(**item))
    return rules


def save_rules(rules: list[AutoExitRule]) -> None:
    save(_STORE_KEY, [asdict(r) for r in rules])


def add_rule(
    position_id: str,
    target_pct: float,
    stop_loss_pct: float,
    trailing_stop: bool = False,
) -> AutoExitRule:
    rule = AutoExitRule(
        id=str(uuid.uuid4()),
        position_id=position_id,
        target_pct=target_pct,
        stop_loss_pct=stop_loss_pct,
        trailing_stop=trailing_stop,
        peak_ltp=None,
        status="ACTIVE",
        created_at=_now_iso(),
    )
    rules = load_rules()
    rules.append(rule)
    save_rules(rules)
    return rule


def cancel_rule(rule_id: str) -> bool:
    rules = load_rules()
    for r in rules:
        if r.id == rule_id:
            r.status = "CANCELLED"
            save_rules(rules)
            return True
    return False


def get_active_rules() -> list[AutoExitRule]:
    return [r for r in load_rules() if r.status == "ACTIVE"]


def _sign(action: str) -> int:
    return 1 if action == "BUY" else -1


def check_exits(
    positions: list[Any],
    ltp_map: dict,
) -> list[tuple[AutoExitRule, Any, float]]:
    active_rules = get_active_rules()
    pos_by_id: dict[str, Any] = {p.id: p for p in positions if p.status == "OPEN"}

    triggered_list: list[tuple[AutoExitRule, Any, float]] = []
    rules = load_rules()
    changed = False

    for rule in rules:
        if rule.status != "ACTIVE":
            continue
        pos = pos_by_id.get(rule.position_id)
        if pos is None:
            continue

        key = (pos.symbol, pos.expiry, pos.strike, pos.opt_type)
        ltp = ltp_map.get(key)
        if ltp is None:
            continue

        sign = _sign(pos.action)
        pnl_pct = (ltp - pos.entry_price) / pos.entry_price * 100 * sign

        if rule.trailing_stop:
            current_signed_ltp = ltp * sign
            peak_signed = (rule.peak_ltp or pos.entry_price) * sign
            if current_signed_ltp > peak_signed:
                rule.peak_ltp = ltp
                changed = True

        should_trigger = False
        if rule.target_pct > 0 and pnl_pct >= rule.target_pct:
            should_trigger = True
        if rule.stop_loss_pct > 0 and pnl_pct <= -rule.stop_loss_pct:
            should_trigger = True

        if rule.trailing_stop and rule.peak_ltp is not None and rule.stop_loss_pct > 0:
            peak = rule.peak_ltp
            trail_pct = (ltp - peak) / peak * 100 * sign
            if trail_pct <= -rule.stop_loss_pct:
                should_trigger = True

        if should_trigger:
            triggered_list.append((rule, pos, ltp))

    if changed:
        save_rules(rules)

    return triggered_list


def mark_triggered(rule_id: str) -> None:
    rules = load_rules()
    for r in rules:
        if r.id == rule_id:
            r.status = "TRIGGERED"
            save_rules(rules)
            return
