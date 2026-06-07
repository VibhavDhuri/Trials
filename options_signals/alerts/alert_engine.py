"""
Alert rules engine. Checks market snapshots against user-defined conditions.
Rules are persisted atomically via store.local_store.
"""
from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Optional

from config import IST
from store.local_store import load, save

_STORE_KEY = "alerts"


class ConditionType(str, Enum):
    PCR_ABOVE       = "PCR_ABOVE"
    PCR_BELOW       = "PCR_BELOW"
    IV_RANK_ABOVE   = "IV_RANK_ABOVE"
    IV_RANK_BELOW   = "IV_RANK_BELOW"
    PRICE_ABOVE     = "PRICE_ABOVE"
    PRICE_BELOW     = "PRICE_BELOW"
    MAX_PAIN_BREACH = "MAX_PAIN_BREACH"   # spot crosses max pain
    SIGNAL_CHANGE   = "SIGNAL_CHANGE"    # signal direction changes


@dataclass
class AlertRule:
    id: str
    index: str
    condition_type: str
    threshold: float
    label: str = ""
    triggered: bool = False
    active: bool = True
    last_checked: Optional[str] = None
    last_value: Optional[float] = None
    last_signal: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.datetime.now(IST).isoformat()
    )


@dataclass
class MarketSnapshot:
    index: str
    spot: float
    pcr_oi: float
    iv_rank: float
    max_pain: float
    signal_direction: str


def load_rules() -> List[AlertRule]:
    raw = load(_STORE_KEY, [])
    rules = []
    for r in raw:
        try:
            rules.append(AlertRule(**{k: v for k, v in r.items() if k in AlertRule.__dataclass_fields__}))
        except TypeError:
            pass
    return rules


def save_rules(rules: List[AlertRule]) -> None:
    save(_STORE_KEY, [asdict(r) for r in rules])


def add_rule(index: str, condition_type: str, threshold: float, label: str = "") -> AlertRule:
    rules = load_rules()
    rule = AlertRule(
        id=str(uuid.uuid4())[:8],
        index=index,
        condition_type=condition_type,
        threshold=threshold,
        label=label or f"{index} {condition_type} {threshold}",
    )
    rules.append(rule)
    save_rules(rules)
    return rule


def remove_rule(rule_id: str) -> None:
    rules = [r for r in load_rules() if r.id != rule_id]
    save_rules(rules)


def check_alerts(snapshot: MarketSnapshot) -> List[AlertRule]:
    """
    Evaluate all active rules for the given snapshot.
    Returns rules that fired. Persists updated last_value / triggered state.
    """
    rules = load_rules()
    fired: List[AlertRule] = []
    now_str = datetime.datetime.now(IST).isoformat()

    for rule in rules:
        if not rule.active or rule.index != snapshot.index:
            continue

        ct = rule.condition_type
        prev_val = rule.last_value
        val: Optional[float] = None
        triggered = False

        if ct == ConditionType.PCR_ABOVE:
            val = snapshot.pcr_oi
            triggered = val > rule.threshold
        elif ct == ConditionType.PCR_BELOW:
            val = snapshot.pcr_oi
            triggered = val < rule.threshold
        elif ct == ConditionType.IV_RANK_ABOVE:
            val = snapshot.iv_rank
            triggered = val > rule.threshold
        elif ct == ConditionType.IV_RANK_BELOW:
            val = snapshot.iv_rank
            triggered = val < rule.threshold
        elif ct == ConditionType.PRICE_ABOVE:
            val = snapshot.spot
            triggered = val > rule.threshold
        elif ct == ConditionType.PRICE_BELOW:
            val = snapshot.spot
            triggered = val < rule.threshold
        elif ct == ConditionType.MAX_PAIN_BREACH:
            # Fire when spot crosses max pain (sign of (spot - max_pain) flips)
            val = snapshot.spot - snapshot.max_pain
            if prev_val is not None:
                triggered = (prev_val * val) < 0  # sign change
        elif ct == ConditionType.SIGNAL_CHANGE:
            prev_sig = rule.last_signal
            triggered = prev_sig is not None and prev_sig != snapshot.signal_direction
            rule.last_signal = snapshot.signal_direction

        rule.last_checked = now_str
        rule.last_value = val
        if triggered:
            rule.triggered = True
            fired.append(rule)

    save_rules(rules)
    return fired
