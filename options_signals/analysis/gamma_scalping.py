"""
Gamma scalping tracker — monitors delta of a long-gamma position and tracks hedge P&L.
Used when holding a long straddle/strangle and delta-hedging with futures/underlying.
"""
from __future__ import annotations

import datetime
import math
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional

import pandas as pd

from config import INDICES, IST
from store.local_store import load, save
from positions.tracker import get_open_positions

_STORE_KEY = "gamma_sessions"


@dataclass
class HedgeTrade:
    id: str
    timestamp: str
    delta_before: float
    delta_after: float
    hedge_action: str        # "BUY_FUTURES" | "SELL_FUTURES"
    hedge_qty: float
    hedge_price: float
    cumulative_hedge_pnl: float


@dataclass
class GammaScalpingSession:
    id: str
    symbol: str
    position_ids: list[str]
    start_time: str
    target_delta_range: float
    hedge_lot_size: int
    hedge_trades: list[HedgeTrade]
    total_gamma_pnl: float
    status: str              # "ACTIVE" | "CLOSED"


def _session_from_dict(d: dict) -> GammaScalpingSession:
    hedge_trades = [HedgeTrade(**ht) for ht in d.get("hedge_trades", [])]
    return GammaScalpingSession(
        id=d["id"],
        symbol=d["symbol"],
        position_ids=d["position_ids"],
        start_time=d["start_time"],
        target_delta_range=d["target_delta_range"],
        hedge_lot_size=d["hedge_lot_size"],
        hedge_trades=hedge_trades,
        total_gamma_pnl=d["total_gamma_pnl"],
        status=d["status"],
    )


def load_sessions() -> list[GammaScalpingSession]:
    raw = load(_STORE_KEY, [])
    out: list[GammaScalpingSession] = []
    for d in raw:
        try:
            out.append(_session_from_dict(d))
        except (KeyError, TypeError):
            pass
    return out


def save_sessions(sessions: list[GammaScalpingSession]) -> None:
    save(_STORE_KEY, [asdict(s) for s in sessions])


def create_session(
    symbol: str,
    position_ids: list[str],
    target_delta_range: float = 5.0,
    hedge_lot_size: int = 1,
) -> GammaScalpingSession:
    session = GammaScalpingSession(
        id=str(uuid.uuid4())[:8],
        symbol=symbol,
        position_ids=position_ids,
        start_time=datetime.datetime.now(IST).isoformat(),
        target_delta_range=target_delta_range,
        hedge_lot_size=hedge_lot_size,
        hedge_trades=[],
        total_gamma_pnl=0.0,
        status="ACTIVE",
    )
    sessions = load_sessions()
    sessions.append(session)
    save_sessions(sessions)
    return session


def close_session(session_id: str) -> None:
    sessions = load_sessions()
    for s in sessions:
        if s.id == session_id:
            s.status = "CLOSED"
            break
    save_sessions(sessions)


def compute_session_delta(session: GammaScalpingSession, chain_df: pd.DataFrame) -> float:
    open_positions = get_open_positions()
    relevant = [p for p in open_positions if p.id in session.position_ids]
    lot_size = INDICES[session.symbol].lot_size
    net_delta = 0.0
    for pos in relevant:
        mask = (
            (chain_df["strike"] == pos.strike) &
            (chain_df["opt_type"] == pos.opt_type)
        )
        matched = chain_df[mask]
        if matched.empty:
            continue
        delta = float(matched.iloc[0]["delta"])
        sign = 1 if pos.action == "BUY" else -1
        net_delta += delta * pos.quantity * lot_size * sign
    return net_delta


def record_hedge(
    session_id: str,
    delta_before: float,
    delta_after: float,
    hedge_action: str,
    hedge_qty: float,
    hedge_price: float,
    prev_cumulative_pnl: float,
) -> HedgeTrade:
    trade = HedgeTrade(
        id=str(uuid.uuid4())[:8],
        timestamp=datetime.datetime.now(IST).isoformat(),
        delta_before=delta_before,
        delta_after=delta_after,
        hedge_action=hedge_action,
        hedge_qty=hedge_qty,
        hedge_price=hedge_price,
        cumulative_hedge_pnl=prev_cumulative_pnl,
    )
    sessions = load_sessions()
    for s in sessions:
        if s.id == session_id:
            s.hedge_trades.append(trade)
            break
    save_sessions(sessions)
    return trade


def session_summary(session: GammaScalpingSession, current_spot: float) -> dict:
    start_dt = datetime.datetime.fromisoformat(session.start_time)
    now_dt = datetime.datetime.now(IST)
    if start_dt.tzinfo is None:
        start_dt = IST.localize(start_dt)
    duration_hours = (now_dt - start_dt).total_seconds() / 3600.0

    total_hedge_pnl = 0.0
    for ht in session.hedge_trades:
        if ht.hedge_action == "BUY_FUTURES":
            pnl = (current_spot - ht.hedge_price) * ht.hedge_qty * session.hedge_lot_size
        else:
            pnl = (ht.hedge_price - current_spot) * ht.hedge_qty * session.hedge_lot_size
        total_hedge_pnl += pnl

    avg_hedge_delta = (
        sum(abs(ht.delta_before) for ht in session.hedge_trades) / len(session.hedge_trades)
        if session.hedge_trades
        else 0.0
    )

    return {
        "session_id": session.id,
        "symbol": session.symbol,
        "n_hedges": len(session.hedge_trades),
        "total_hedge_pnl": round(total_hedge_pnl, 2),
        "avg_hedge_delta": round(avg_hedge_delta, 4),
        "status": session.status,
        "duration_hours": round(duration_hours, 2),
    }


def check_and_suggest_hedge(
    session: GammaScalpingSession, current_delta: float
) -> dict | None:
    if abs(current_delta) <= session.target_delta_range:
        return None

    if current_delta > 0:
        action = "SELL_FUTURES"
        qty = math.ceil(current_delta / session.target_delta_range)
        new_delta_estimate = current_delta - qty * session.target_delta_range
    else:
        action = "BUY_FUTURES"
        qty = math.ceil(abs(current_delta) / session.target_delta_range)
        new_delta_estimate = current_delta + qty * session.target_delta_range

    return {
        "action": action,
        "qty": qty,
        "reason": (
            f"Net delta {current_delta:.2f} exceeds target range "
            f"±{session.target_delta_range}; hedge with {action} {qty} lot(s)"
        ),
        "new_delta_estimate": round(new_delta_estimate, 4),
    }
