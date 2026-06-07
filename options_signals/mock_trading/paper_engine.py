"""
Paper trading engine.

Two modes:
  MANUAL  — user places paper trades through the Streamlit UI.
  AUTO    — the bot autonomously generates signals every 5 minutes and
             places paper trades on HIGH-confidence signals.

Auto-bot lifecycle:
  - Run `python mock_trading/run_bot.py` as a separate process.
  - The bot writes all activity to data_store/paper_trades.json and
    open positions to data_store/positions.json (via PositionTracker).
  - The Streamlit Mock Trading page reads these files and displays live state.

Stop-loss: exits a position when current price < entry_price × (1 - stop_loss_pct).
Expiry exit: exits all positions one trading day before expiry date.
"""
from __future__ import annotations

import datetime
import logging
from typing import List, Optional

from config import INDICES, IST
from analysis.greeks import bs_price
from analysis.signals import Direction, Confidence
from positions.tracker import (
    add_position, close_position, get_open_positions, Position
)
from store.local_store import load, save

_STORE_KEY = "paper_trades"
_STOP_LOSS_PCT = 0.50        # exit if premium falls 50%
_MIN_CONFIDENCE = Confidence.HIGH

log = logging.getLogger(__name__)


def _load_trade_log() -> List[dict]:
    return load(_STORE_KEY, [])


def _append_trade_log(entry: dict) -> None:
    trades = _load_trade_log()
    trades.append(entry)
    save(_STORE_KEY, trades)


def _should_exit(pos: Position, current_ltp: float) -> bool:
    """True if stop-loss hit or position expired."""
    # Stop-loss: for a BUY position, exit if LTP < entry × (1 - stop)
    if pos.action == "BUY" and current_ltp < pos.entry_price * (1 - _STOP_LOSS_PCT):
        return True
    # Expiry: exit 1 trading day before expiry
    try:
        exp = datetime.datetime.strptime(pos.expiry, "%Y-%m-%d").date()
        days_left = (exp - datetime.date.today()).days
        if days_left <= 1:
            return True
    except ValueError:
        pass
    return False


def check_and_exit_positions(current_prices: dict) -> List[dict]:
    """
    Check all open paper positions and exit those that hit stop-loss or expiry.
    current_prices: {(symbol, expiry, strike, opt_type): ltp}
    Returns list of exit records.
    """
    exits = []
    for pos in get_open_positions():
        if pos.source not in ("BOT", "MANUAL"):
            continue
        key = (pos.symbol, pos.expiry, pos.strike, pos.opt_type)
        ltp = current_prices.get(key, pos.entry_price)
        if _should_exit(pos, ltp):
            closed = close_position(pos.id, ltp)
            if closed:
                from positions.tracker import realised_pnl
                pnl = realised_pnl(closed)
                record = {
                    "event":       "EXIT",
                    "id":          pos.id,
                    "symbol":      pos.symbol,
                    "expiry":      pos.expiry,
                    "strike":      pos.strike,
                    "opt_type":    pos.opt_type,
                    "action":      pos.action,
                    "entry_price": pos.entry_price,
                    "exit_price":  ltp,
                    "pnl_gross":   round(pnl, 2),
                    "timestamp":   datetime.datetime.now(IST).isoformat(),
                    "source":      pos.source,
                }
                _append_trade_log(record)
                exits.append(record)
                log.info("PAPER EXIT %s %s %s@%.2f pnl=%.2f", pos.symbol, pos.opt_type, pos.strike, ltp, pnl)
    return exits


def place_bot_trade(
    symbol: str,
    expiry: str,
    strike: float,
    opt_type: str,
    action: str,
    ltp: float,
    strategy_tag: str = "",
    quantity: int = 1,
) -> Optional[Position]:
    """Place a single paper trade from the auto-bot."""
    if ltp <= 0:
        return None
    pos = add_position(
        symbol=symbol,
        expiry=expiry,
        strike=strike,
        opt_type=opt_type,
        action=action,
        quantity=quantity,
        entry_price=ltp,
        source="BOT",
        strategy_tag=strategy_tag,
    )
    record = {
        "event":        "ENTRY",
        "id":           pos.id,
        "symbol":       symbol,
        "expiry":       expiry,
        "strike":       strike,
        "opt_type":     opt_type,
        "action":       action,
        "entry_price":  ltp,
        "strategy_tag": strategy_tag,
        "timestamp":    datetime.datetime.now(IST).isoformat(),
        "source":       "BOT",
    }
    _append_trade_log(record)
    log.info("PAPER ENTRY %s %s %s@%.2f [%s]", symbol, opt_type, strike, ltp, strategy_tag)
    return pos


def get_trade_log() -> List[dict]:
    return _load_trade_log()


def paper_pnl_summary() -> dict:
    """Compute summary stats from the trade log (closed trades only)."""
    trades = [t for t in _load_trade_log() if t.get("event") == "EXIT"]
    if not trades:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                "total_pnl": 0.0, "avg_pnl": 0.0, "best": 0.0, "worst": 0.0}
    pnls = [t.get("pnl_gross", 0.0) for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    return {
        "total":    len(pnls),
        "wins":     wins,
        "losses":   len(pnls) - wins,
        "win_rate": round(wins / len(pnls) * 100, 1),
        "total_pnl": round(sum(pnls), 2),
        "avg_pnl":  round(sum(pnls) / len(pnls), 2),
        "best":     round(max(pnls), 2),
        "worst":    round(min(pnls), 2),
    }
