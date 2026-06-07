"""
Risk management — position sizing, daily loss limits, circuit breaker.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, asdict
from typing import Dict, Tuple

from config import INDICES, IST
from store.local_store import load as _load, save as _save

_RISK_KEY = "risk_settings"


@dataclass
class RiskSettings:
    capital: float = 500_000.0          # total capital in INR
    risk_per_trade_pct: float = 2.0     # max % per trade
    daily_loss_limit_pct: float = 3.0   # circuit-breaker threshold
    max_open_positions: int = 5
    max_portfolio_delta: float = 10.0   # max absolute net delta


def load_settings() -> RiskSettings:
    raw = _load(_RISK_KEY, {})
    if not raw:
        return RiskSettings()
    return RiskSettings(**{k: v for k, v in raw.items() if k in RiskSettings.__dataclass_fields__})


def save_settings(s: RiskSettings) -> None:
    _save(_RISK_KEY, asdict(s))


def position_size(
    capital: float,
    risk_pct: float,
    premium: float,
    lot_size: int,
) -> int:
    """
    Max lots we can buy given capital and risk %, where max-loss = full premium paid.
    Returns at least 1.
    """
    if premium <= 0 or lot_size <= 0:
        return 1
    budget = capital * risk_pct / 100.0
    lots = int(budget / (premium * lot_size))
    return max(1, lots)


def daily_pnl_realised() -> float:
    """Sum of realised P&L from positions closed today (IST)."""
    from positions.tracker import get_all_positions, realised_pnl
    today = datetime.datetime.now(IST).date().isoformat()
    total = 0.0
    for p in get_all_positions():
        if p.status == "CLOSED" and p.exit_time and p.exit_time[:10] == today:
            try:
                total += realised_pnl(p)
            except Exception:
                pass
    return total


def circuit_breaker_triggered(settings: RiskSettings, pnl: float) -> bool:
    limit = -(settings.capital * settings.daily_loss_limit_pct / 100.0)
    return pnl < limit


def check_position_limit(settings: RiskSettings) -> Tuple[int, bool]:
    from positions.tracker import get_open_positions
    n = len(get_open_positions())
    return n, n >= settings.max_open_positions


def risk_report(settings: RiskSettings, pnl: float) -> Dict:
    n_open, pos_limit_hit = check_position_limit(settings)
    loss_limit_inr = settings.capital * settings.daily_loss_limit_pct / 100.0
    used_pct = min(abs(pnl) / loss_limit_inr * 100, 100) if loss_limit_inr > 0 else 0.0
    breaker = circuit_breaker_triggered(settings, pnl)
    return {
        "open_positions": n_open,
        "max_positions": settings.max_open_positions,
        "positions_limit_hit": pos_limit_hit,
        "daily_pnl": pnl,
        "daily_loss_limit_inr": loss_limit_inr,
        "daily_loss_used_pct": used_pct,
        "circuit_breaker": breaker,
        "risk_per_trade_inr": settings.capital * settings.risk_per_trade_pct / 100.0,
    }
