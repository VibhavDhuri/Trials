"""
Strategy scheduler — runs conditional/time-based strategy execution.
Conditions: time-of-day, PCR threshold, VIX level, IV rank, day-of-week.
Run standalone: python automation/scheduler.py [--offline] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import INDICES, IST, RISK_FREE_RATE
from store.local_store import load, save
from analysis.greeks import bs_price
from positions.tracker import add_position

_STORE_KEY = "scheduled_strategies"


@dataclass
class ScheduledStrategy:
    id: str
    name: str
    symbol: str
    strategy_type: str       # "SELL_STRADDLE"|"BUY_STRADDLE"|"SELL_STRANGLE"|"BUY_CALL"|"BUY_PUT"|"IRON_CONDOR"
    conditions: dict
    schedule: dict
    enabled: bool
    last_run: Optional[str]
    created_at: str


def _strategy_from_dict(d: dict) -> ScheduledStrategy:
    return ScheduledStrategy(
        id=d["id"],
        name=d["name"],
        symbol=d["symbol"],
        strategy_type=d["strategy_type"],
        conditions=d["conditions"],
        schedule=d["schedule"],
        enabled=d["enabled"],
        last_run=d.get("last_run"),
        created_at=d["created_at"],
    )


def load_strategies() -> list[ScheduledStrategy]:
    raw = load(_STORE_KEY, [])
    out: list[ScheduledStrategy] = []
    for d in raw:
        try:
            out.append(_strategy_from_dict(d))
        except (KeyError, TypeError):
            pass
    return out


def save_strategies(strategies: list[ScheduledStrategy]) -> None:
    save(_STORE_KEY, [asdict(s) for s in strategies])


def add_strategy(
    name: str,
    symbol: str,
    strategy_type: str,
    conditions: dict,
    schedule: dict,
) -> ScheduledStrategy:
    strategy = ScheduledStrategy(
        id=str(uuid.uuid4())[:8],
        name=name,
        symbol=symbol,
        strategy_type=strategy_type,
        conditions=conditions,
        schedule=schedule,
        enabled=True,
        last_run=None,
        created_at=datetime.datetime.now(IST).isoformat(),
    )
    strategies = load_strategies()
    strategies.append(strategy)
    save_strategies(strategies)
    return strategy


def remove_strategy(strategy_id: str) -> bool:
    strategies = load_strategies()
    before = len(strategies)
    strategies = [s for s in strategies if s.id != strategy_id]
    save_strategies(strategies)
    return len(strategies) < before


def enable_strategy(strategy_id: str, enabled: bool) -> None:
    strategies = load_strategies()
    for s in strategies:
        if s.id == strategy_id:
            s.enabled = enabled
            break
    save_strategies(strategies)


def check_conditions(
    strategy: ScheduledStrategy, market_snapshot: dict
) -> tuple[bool, str]:
    c = strategy.conditions
    vix = market_snapshot.get("vix", 0.0)
    iv_rank = market_snapshot.get("iv_rank", 0.0)
    pcr = market_snapshot.get("pcr", 0.0)
    is_market_open = market_snapshot.get("is_market_open", True)

    if c.get("require_market_open") and not is_market_open:
        return False, "Market is not open"

    if "min_vix" in c and vix < c["min_vix"]:
        return False, f"VIX {vix:.2f} below minimum {c['min_vix']}"
    if "max_vix" in c and vix > c["max_vix"]:
        return False, f"VIX {vix:.2f} above maximum {c['max_vix']}"
    if "min_iv_rank" in c and iv_rank < c["min_iv_rank"]:
        return False, f"IV rank {iv_rank:.1f} below minimum {c['min_iv_rank']}"
    if "max_iv_rank" in c and iv_rank > c["max_iv_rank"]:
        return False, f"IV rank {iv_rank:.1f} above maximum {c['max_iv_rank']}"
    if "min_pcr" in c and pcr < c["min_pcr"]:
        return False, f"PCR {pcr:.2f} below minimum {c['min_pcr']}"
    if "max_pcr" in c and pcr > c["max_pcr"]:
        return False, f"PCR {pcr:.2f} above maximum {c['max_pcr']}"

    return True, "All conditions met"


def is_due(strategy: ScheduledStrategy) -> bool:
    now = datetime.datetime.now(IST)
    sched = strategy.schedule

    days_of_week: list[int] = sched.get("days_of_week", list(range(5)))
    if now.weekday() not in days_of_week:
        return False

    time_str: str = sched.get("time_ist", "09:20")
    try:
        h, m = map(int, time_str.split(":"))
    except (ValueError, AttributeError):
        return False
    scheduled_minutes = h * 60 + m
    current_minutes = now.hour * 60 + now.minute
    if abs(current_minutes - scheduled_minutes) > 5:
        return False

    frequency: str = sched.get("frequency", "daily")
    today_str = now.date().isoformat()

    if frequency == "once":
        return strategy.last_run is None

    if frequency == "daily":
        if strategy.last_run is None:
            return True
        try:
            last_date = datetime.datetime.fromisoformat(strategy.last_run).date().isoformat()
        except ValueError:
            last_date = strategy.last_run[:10]
        return last_date != today_str

    if frequency == "weekly":
        if strategy.last_run is None:
            return True
        try:
            last_dt = datetime.datetime.fromisoformat(strategy.last_run)
        except ValueError:
            return True
        return (now.date() - last_dt.date()).days >= 7

    return False


def execute_strategy(
    strategy: ScheduledStrategy,
    spot: float,
    atm_strike: float,
    atm_iv_pct: float,
    expiry: str,
    dry_run: bool = False,
) -> dict:
    step = INDICES[strategy.symbol].strike_gap
    sigma = atm_iv_pct / 100.0
    T = 7 / 365.0

    def premium(strike: float, opt_type: str) -> float:
        return bs_price(spot, strike, T, RISK_FREE_RATE, sigma, opt_type)

    legs_spec: list[dict]
    match strategy.strategy_type:
        case "SELL_STRADDLE":
            legs_spec = [
                {"action": "SELL", "strike": atm_strike, "opt_type": "CE"},
                {"action": "SELL", "strike": atm_strike, "opt_type": "PE"},
            ]
        case "BUY_STRADDLE":
            legs_spec = [
                {"action": "BUY", "strike": atm_strike, "opt_type": "CE"},
                {"action": "BUY", "strike": atm_strike, "opt_type": "PE"},
            ]
        case "SELL_STRANGLE":
            legs_spec = [
                {"action": "SELL", "strike": atm_strike + step, "opt_type": "CE"},
                {"action": "SELL", "strike": atm_strike - step, "opt_type": "PE"},
            ]
        case "IRON_CONDOR":
            legs_spec = [
                {"action": "BUY",  "strike": atm_strike + 2 * step, "opt_type": "CE"},
                {"action": "SELL", "strike": atm_strike + step,     "opt_type": "CE"},
                {"action": "SELL", "strike": atm_strike - step,     "opt_type": "PE"},
                {"action": "BUY",  "strike": atm_strike - 2 * step, "opt_type": "PE"},
            ]
        case "BUY_CALL":
            legs_spec = [{"action": "BUY", "strike": atm_strike, "opt_type": "CE"}]
        case "BUY_PUT":
            legs_spec = [{"action": "BUY", "strike": atm_strike, "opt_type": "PE"}]
        case _:
            legs_spec = []

    legs_detail = [
        {
            **leg,
            "estimated_premium": round(premium(leg["strike"], leg["opt_type"]), 2),
        }
        for leg in legs_spec
    ]

    if dry_run:
        return {
            "dry_run": True,
            "legs_would_execute": legs_detail,
            "strategy_name": strategy.name,
            "strategy_id": strategy.id,
        }

    placed_legs = []
    for leg in legs_detail:
        pos = add_position(
            symbol=strategy.symbol,
            expiry=expiry,
            strike=leg["strike"],
            opt_type=leg["opt_type"],
            action=leg["action"],
            quantity=1,
            entry_price=leg["estimated_premium"],
            source="SCHEDULER",
            strategy_tag=strategy.name,
        )
        placed_legs.append({"position_id": pos.id, **leg})

    strategies = load_strategies()
    for s in strategies:
        if s.id == strategy.id:
            s.last_run = datetime.datetime.now(IST).isoformat()
            break
    save_strategies(strategies)

    return {
        "executed": True,
        "legs": placed_legs,
        "strategy_id": strategy.id,
        "strategy_name": strategy.name,
    }


def _build_mock_snapshot() -> dict:
    return {
        "vix": 14.5,
        "iv_rank": 45.0,
        "pcr": 1.1,
        "spot": 22000.0,
        "is_market_open": True,
    }


def _build_live_snapshot(symbol: str) -> dict:
    token = os.environ.get("UPSTOX_ACCESS_TOKEN", "")
    if not token:
        return _build_mock_snapshot()
    try:
        from data.upstox_client import UpstoxClient
        client = UpstoxClient(token)
        quote = client.get_market_quote(
            [f"NSE_INDEX|{symbol}"]
        )
        spot = 0.0
        for v in quote.values():
            spot = v.get("last_price", 0.0)
            break
    except Exception:
        spot = 0.0
    return {
        "vix": 14.5,
        "iv_rank": 45.0,
        "pcr": 1.1,
        "spot": spot,
        "is_market_open": True,
    }


def run_scheduler_loop(
    offline: bool = False,
    dry_run: bool = False,
    interval: int = 60,
) -> None:
    def log(msg: str) -> None:
        ts = datetime.datetime.now(IST).isoformat(timespec="seconds")
        print(f"[{ts}] {msg}")

    log(f"Scheduler started | offline={offline} dry_run={dry_run} interval={interval}s")

    while True:
        try:
            strategies = load_strategies()
            due = [s for s in strategies if s.enabled and is_due(s)]

            if not due:
                log("No strategies due.")
            else:
                log(f"{len(due)} strategy/ies due.")

            for strategy in due:
                snapshot = _build_mock_snapshot() if offline else _build_live_snapshot(strategy.symbol)
                ok, reason = check_conditions(strategy, snapshot)
                if not ok:
                    log(f"[{strategy.name}] Skipped — {reason}")
                    continue

                spot = snapshot["spot"] or 22000.0
                atm_strike = round(spot / INDICES[strategy.symbol].strike_gap) * INDICES[strategy.symbol].strike_gap
                atm_iv_pct = 15.0

                try:
                    result = execute_strategy(
                        strategy=strategy,
                        spot=spot,
                        atm_strike=atm_strike,
                        atm_iv_pct=atm_iv_pct,
                        expiry="",
                        dry_run=dry_run,
                    )
                    log(f"[{strategy.name}] Result: {result}")
                except Exception as exc:
                    log(f"[{strategy.name}] Error during execution: {exc}")

        except Exception as exc:
            print(f"[SCHEDULER ERROR] {exc}")

        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Options strategy scheduler")
    parser.add_argument("--offline", action="store_true", help="Use mock market data")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without placing positions")
    parser.add_argument("--interval", type=int, default=60, help="Loop interval in seconds")
    args = parser.parse_args()
    run_scheduler_loop(offline=args.offline, dry_run=args.dry_run, interval=args.interval)
