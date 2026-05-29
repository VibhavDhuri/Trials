"""
Strategy-level details: strikes, breakevens, max P/L, margin estimates.

NOTE: Margin figures are rough estimates (LTP × lot size × position count).
Actual margin depends on SPAN calculations performed by your broker.
Always verify margin requirements with your broker before trading.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import pandas as pd

from analysis.signals import Signal, Direction
from config import INDICES
from utils.helpers import format_inr


@dataclass
class StrategyDetails:
    name: str
    legs: List[dict]         # [{ opt_type, action, strike, ltp, iv }]
    max_profit: Optional[float]
    max_loss: Optional[float]
    breakevens: List[float]
    net_premium: float       # positive = credit received, negative = debit paid
    margin_estimate: float   # rough buyer or seller margin in INR per lot
    risk_reward: Optional[float]
    disclaimer: str = (
        "⚠️  Margin estimates are approximate. "
        "Verify with your broker's margin calculator before placing orders."
    )


def _atm_row(chain_df: pd.DataFrame, spot: float, opt_type: str) -> Optional[pd.Series]:
    rows = chain_df[chain_df["opt_type"] == opt_type]
    if rows.empty:
        return None
    return rows.iloc[(rows["atm_distance"]).argsort()[:1]].iloc[0]


def _otm_row(
    chain_df: pd.DataFrame, spot: float, opt_type: str, offset_strikes: int = 1
) -> Optional[pd.Series]:
    rows = chain_df[chain_df["opt_type"] == opt_type]
    if rows.empty:
        return None
    if opt_type == "CE":
        candidates = rows[rows["strike"] > spot].nsmallest(offset_strikes + 1, "atm_distance")
    else:
        candidates = rows[rows["strike"] < spot].nsmallest(offset_strikes + 1, "atm_distance")
    if candidates.empty:
        return None
    return candidates.iloc[-1]


def _leg(action: str, row: pd.Series, opt_type: str) -> dict:
    return {
        "opt_type": opt_type,
        "action": action,
        "strike": row["strike"],
        "ltp": row["ltp"],
        "iv": row["iv"],
        "delta": row["delta"],
    }


def build_strategy_details(signal: Signal, chain_df: pd.DataFrame, symbol: str) -> StrategyDetails:
    """Construct detailed legs and metrics for the recommended strategy."""
    spot = signal.spot
    lot = INDICES[symbol].lot_size
    strategy = signal.strategy

    atm_ce = _atm_row(chain_df, spot, "CE")
    atm_pe = _atm_row(chain_df, spot, "PE")
    otm_ce = _otm_row(chain_df, spot, "CE", 2)
    otm_pe = _otm_row(chain_df, spot, "PE", 2)
    far_ce = _otm_row(chain_df, spot, "CE", 4)
    far_pe = _otm_row(chain_df, spot, "PE", 4)

    empty = StrategyDetails(
        name=strategy, legs=[], max_profit=None, max_loss=None,
        breakevens=[], net_premium=0.0, margin_estimate=0.0, risk_reward=None,
    )

    def _safe(row):
        return row is not None and "ltp" in row.index

    if strategy == "Long Call":
        if not _safe(atm_ce):
            return empty
        premium = float(atm_ce["ltp"])
        return StrategyDetails(
            name=strategy,
            legs=[_leg("BUY", atm_ce, "CE")],
            max_profit=None,  # theoretically unlimited
            max_loss=premium * lot,
            breakevens=[float(atm_ce["strike"]) + premium],
            net_premium=-premium,
            margin_estimate=premium * lot,
            risk_reward=None,
        )

    if strategy == "Long Put":
        if not _safe(atm_pe):
            return empty
        premium = float(atm_pe["ltp"])
        return StrategyDetails(
            name=strategy,
            legs=[_leg("BUY", atm_pe, "PE")],
            max_profit=(float(atm_pe["strike"]) - premium) * lot,
            max_loss=premium * lot,
            breakevens=[float(atm_pe["strike"]) - premium],
            net_premium=-premium,
            margin_estimate=premium * lot,
            risk_reward=None,
        )

    if strategy == "Bull Call Spread":
        if not _safe(atm_ce) or not _safe(otm_ce):
            return empty
        debit = float(atm_ce["ltp"]) - float(otm_ce["ltp"])
        width = float(otm_ce["strike"]) - float(atm_ce["strike"])
        return StrategyDetails(
            name=strategy,
            legs=[_leg("BUY", atm_ce, "CE"), _leg("SELL", otm_ce, "CE")],
            max_profit=(width - debit) * lot,
            max_loss=debit * lot,
            breakevens=[float(atm_ce["strike"]) + debit],
            net_premium=-debit,
            margin_estimate=debit * lot,
            risk_reward=(width - debit) / debit if debit > 0 else None,
        )

    if strategy == "Bear Put Spread":
        if not _safe(atm_pe) or not _safe(otm_pe):
            return empty
        debit = float(atm_pe["ltp"]) - float(otm_pe["ltp"])
        width = float(atm_pe["strike"]) - float(otm_pe["strike"])
        return StrategyDetails(
            name=strategy,
            legs=[_leg("BUY", atm_pe, "PE"), _leg("SELL", otm_pe, "PE")],
            max_profit=(width - debit) * lot,
            max_loss=debit * lot,
            breakevens=[float(atm_pe["strike"]) - debit],
            net_premium=-debit,
            margin_estimate=debit * lot,
            risk_reward=(width - debit) / debit if debit > 0 else None,
        )

    if strategy == "Bull Put Spread":
        if not _safe(otm_pe) or not _safe(far_pe):
            return empty
        credit = float(otm_pe["ltp"]) - float(far_pe["ltp"])
        width = float(otm_pe["strike"]) - float(far_pe["strike"])
        return StrategyDetails(
            name=strategy,
            legs=[_leg("SELL", otm_pe, "PE"), _leg("BUY", far_pe, "PE")],
            max_profit=credit * lot,
            max_loss=(width - credit) * lot,
            breakevens=[float(otm_pe["strike"]) - credit],
            net_premium=credit,
            margin_estimate=(width - credit) * lot,
            risk_reward=credit / (width - credit) if (width - credit) > 0 else None,
        )

    if strategy == "Bear Call Spread":
        if not _safe(otm_ce) or not _safe(far_ce):
            return empty
        credit = float(otm_ce["ltp"]) - float(far_ce["ltp"])
        width = float(far_ce["strike"]) - float(otm_ce["strike"])
        return StrategyDetails(
            name=strategy,
            legs=[_leg("SELL", otm_ce, "CE"), _leg("BUY", far_ce, "CE")],
            max_profit=credit * lot,
            max_loss=(width - credit) * lot,
            breakevens=[float(otm_ce["strike"]) + credit],
            net_premium=credit,
            margin_estimate=(width - credit) * lot,
            risk_reward=credit / (width - credit) if (width - credit) > 0 else None,
        )

    if strategy in ("Short Straddle", "Iron Fly"):
        if not _safe(atm_ce) or not _safe(atm_pe):
            return empty
        credit = float(atm_ce["ltp"]) + float(atm_pe["ltp"])
        legs = [_leg("SELL", atm_ce, "CE"), _leg("SELL", atm_pe, "PE")]
        bes = [float(atm_ce["strike"]) + credit, float(atm_pe["strike"]) - credit]
        if strategy == "Iron Fly" and _safe(far_ce) and _safe(far_pe):
            wing_cost = float(far_ce["ltp"]) + float(far_pe["ltp"])
            net = credit - wing_cost
            width = float(far_ce["strike"]) - float(atm_ce["strike"])
            legs += [_leg("BUY", far_ce, "CE"), _leg("BUY", far_pe, "PE")]
            return StrategyDetails(
                name=strategy, legs=legs,
                max_profit=net * lot,
                max_loss=(width - net) * lot,
                breakevens=bes,
                net_premium=net,
                margin_estimate=(width - net) * lot,
                risk_reward=net / (width - net) if (width - net) > 0 else None,
            )
        return StrategyDetails(
            name=strategy, legs=legs,
            max_profit=credit * lot,
            max_loss=None,  # unlimited on naked straddle
            breakevens=bes,
            net_premium=credit,
            margin_estimate=credit * lot * 3,  # rough seller margin
            risk_reward=None,
        )

    if strategy == "Iron Condor":
        if not all(_safe(r) for r in (otm_ce, far_ce, otm_pe, far_pe)):
            return empty
        credit_ce = float(otm_ce["ltp"]) - float(far_ce["ltp"])
        credit_pe = float(otm_pe["ltp"]) - float(far_pe["ltp"])
        net = credit_ce + credit_pe
        width_ce = float(far_ce["strike"]) - float(otm_ce["strike"])
        width_pe = float(otm_pe["strike"]) - float(far_pe["strike"])
        max_loss = (max(width_ce, width_pe) - net) * lot
        return StrategyDetails(
            name=strategy,
            legs=[
                _leg("SELL", otm_ce, "CE"), _leg("BUY", far_ce, "CE"),
                _leg("SELL", otm_pe, "PE"), _leg("BUY", far_pe, "PE"),
            ],
            max_profit=net * lot,
            max_loss=max_loss,
            breakevens=[float(otm_ce["strike"]) + net, float(otm_pe["strike"]) - net],
            net_premium=net,
            margin_estimate=max_loss,
            risk_reward=net * lot / max_loss if max_loss > 0 else None,
        )

    if strategy == "Long Straddle":
        if not _safe(atm_ce) or not _safe(atm_pe):
            return empty
        debit = float(atm_ce["ltp"]) + float(atm_pe["ltp"])
        return StrategyDetails(
            name=strategy,
            legs=[_leg("BUY", atm_ce, "CE"), _leg("BUY", atm_pe, "PE")],
            max_profit=None,
            max_loss=debit * lot,
            breakevens=[float(atm_ce["strike"]) + debit, float(atm_pe["strike"]) - debit],
            net_premium=-debit,
            margin_estimate=debit * lot,
            risk_reward=None,
        )

    return empty
