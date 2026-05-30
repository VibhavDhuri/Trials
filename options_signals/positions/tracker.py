"""
Position tracker — paper and live positions with live P&L.

IMPORTANT DISCLAIMER:
P&L shown is GROSS (before transaction costs).
In India, STT on options exercise = 0.125% of settlement value (intrinsic × lot_size).
Exchange charges, SEBI turnover fee, and brokerage add further costs.
For near-expiry ITM options, STT alone can exceed the gross profit.
Always account for all costs before making trading decisions.
"""
from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from config import INDICES, IST
from store.local_store import load, save

_STORE_KEY = "positions"


@dataclass
class Position:
    id: str
    symbol: str
    expiry: str
    strike: float
    opt_type: str          # "CE" | "PE"
    action: str            # "BUY" | "SELL"
    quantity: int          # number of lots
    entry_price: float
    entry_time: str
    status: str = "OPEN"   # "OPEN" | "CLOSED"
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    source: str = "MANUAL"  # "MANUAL" | "BOT"
    strategy_tag: str = ""


def _direction(action: str) -> int:
    return 1 if action == "BUY" else -1


def gross_pnl(pos: Position, current_ltp: float) -> float:
    lot_size = INDICES[pos.symbol].lot_size
    return (current_ltp - pos.entry_price) * pos.quantity * lot_size * _direction(pos.action)


def realised_pnl(pos: Position) -> float:
    if pos.exit_price is None:
        return 0.0
    lot_size = INDICES[pos.symbol].lot_size
    return (pos.exit_price - pos.entry_price) * pos.quantity * lot_size * _direction(pos.action)


def load_positions() -> List[Position]:
    raw = load(_STORE_KEY, [])
    out = []
    for r in raw:
        try:
            out.append(Position(**{k: v for k, v in r.items() if k in Position.__dataclass_fields__}))
        except TypeError:
            pass
    return out


def save_positions(positions: List[Position]) -> None:
    save(_STORE_KEY, [asdict(p) for p in positions])


def add_position(
    symbol: str,
    expiry: str,
    strike: float,
    opt_type: str,
    action: str,
    quantity: int,
    entry_price: float,
    source: str = "MANUAL",
    strategy_tag: str = "",
) -> Position:
    positions = load_positions()
    pos = Position(
        id=str(uuid.uuid4())[:8],
        symbol=symbol,
        expiry=expiry,
        strike=strike,
        opt_type=opt_type,
        action=action,
        quantity=quantity,
        entry_price=entry_price,
        entry_time=datetime.datetime.now(IST).isoformat(),
        source=source,
        strategy_tag=strategy_tag,
    )
    positions.append(pos)
    save_positions(positions)
    return pos


def close_position(pos_id: str, exit_price: float) -> Optional[Position]:
    positions = load_positions()
    for p in positions:
        if p.id == pos_id and p.status == "OPEN":
            p.status = "CLOSED"
            p.exit_price = exit_price
            p.exit_time = datetime.datetime.now(IST).isoformat()
            save_positions(positions)
            return p
    return None


def get_open_positions() -> List[Position]:
    return [p for p in load_positions() if p.status == "OPEN"]


def get_all_positions() -> List[Position]:
    return load_positions()


def portfolio_greeks(open_positions: List[Position], chain_lookup: Optional[Dict] = None) -> Dict:
    """
    Sum delta, gamma, theta across all open positions.
    chain_lookup: optional dict mapping (symbol, expiry, strike, opt_type) → greek values dict.
    Portfolio Greeks are signed by position direction (BUY=+1, SELL=-1).
    Returns zero dict when chain_lookup is not provided.
    """
    total = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    if not chain_lookup:
        return total
    for p in open_positions:
        key = (p.symbol, p.expiry, p.strike, p.opt_type)
        greeks = chain_lookup.get(key, {})
        cfg = INDICES.get(p.symbol)
        lot = cfg.lot_size if cfg else 1
        sign = _direction(p.action)
        for g in ("delta", "gamma", "theta", "vega"):
            total[g] += greeks.get(g, 0.0) * p.quantity * lot * sign
    return total
