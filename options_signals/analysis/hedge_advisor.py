"""
Auto-hedge advisor — suggests minimum-cost option or futures hedge to reduce portfolio delta.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from config import INDICES
from positions.tracker import Position


@dataclass
class HedgeSuggestion:
    needed: bool
    reason: str = ""
    action: str = ""
    instrument_desc: str = ""
    quantity: int = 0
    estimated_cost_inr: float = 0.0
    net_delta_before: float = 0.0
    net_delta_after: float = 0.0


def portfolio_net_delta(
    positions: list[Position],
    chain_lookup: dict,
) -> float:
    if not chain_lookup:
        return 0.0
    total_delta = 0.0
    for pos in positions:
        if pos.status != "OPEN":
            continue
        key = (pos.symbol, pos.expiry, pos.strike, pos.opt_type)
        entry = chain_lookup.get(key, {})
        delta = entry.get("delta", 0.0)
        cfg = INDICES.get(pos.symbol)
        lot_size = cfg.lot_size if cfg else 75
        sign = 1 if pos.action == "BUY" else -1
        total_delta += delta * pos.quantity * lot_size * sign
    return total_delta


def suggest_hedge(
    positions: list[Position],
    spot: float,
    chain_df: pd.DataFrame,
    threshold: float = 10.0,
) -> HedgeSuggestion:
    if chain_df.empty:
        return HedgeSuggestion(needed=False, reason="No option chain data available")

    open_positions = [p for p in positions if p.status == "OPEN"]
    if not open_positions:
        return HedgeSuggestion(needed=False, reason="No open positions")

    symbol: str = open_positions[0].symbol
    cfg = INDICES.get(symbol)
    lot_size: int = cfg.lot_size if cfg else 75

    def _get_delta_ltp(strike: float, opt_type: str) -> tuple[float, float]:
        rows = chain_df[
            (chain_df["strike"] == strike) & (chain_df["opt_type"] == opt_type)
        ]
        if rows.empty:
            typed_rows = chain_df[chain_df["opt_type"] == opt_type]
            if typed_rows.empty:
                return 0.0, 0.0
            nearest_idx = (typed_rows["strike"] - strike).abs().idxmin()
            rows = chain_df.loc[[nearest_idx]]
        if rows.empty:
            return 0.0, 0.0
        delta = float(rows["delta"].iloc[0])
        ltp = float(rows["ltp"].iloc[0])
        return delta, ltp

    net_delta = 0.0
    for pos in open_positions:
        delta, _ = _get_delta_ltp(pos.strike, pos.opt_type)
        sign = 1 if pos.action == "BUY" else -1
        net_delta += delta * pos.quantity * lot_size * sign

    if abs(net_delta) < threshold:
        return HedgeSuggestion(
            needed=False,
            reason="Portfolio delta within acceptable range",
            net_delta_before=net_delta,
        )

    atm_idx = (chain_df["strike"] - spot).abs().idxmin()
    atm_strike = float(chain_df.loc[atm_idx, "strike"])

    if net_delta > threshold:
        pe_rows = chain_df[
            (chain_df["strike"] == atm_strike) & (chain_df["opt_type"] == "PE")
        ]
        if pe_rows.empty:
            pe_typed = chain_df[chain_df["opt_type"] == "PE"]
            if pe_typed.empty:
                return HedgeSuggestion(needed=False, reason="No PE options available for hedge")
            nearest_idx = (pe_typed["strike"] - spot).abs().idxmin()
            pe_rows = chain_df.loc[[nearest_idx]]
            atm_strike = float(pe_rows["strike"].iloc[0])

        pe_ltp = float(pe_rows["ltp"].iloc[0])
        hedge_delta_per_lot = 0.5 * lot_size
        lots_needed = math.ceil(net_delta / hedge_delta_per_lot)
        cost = lots_needed * pe_ltp * lot_size
        net_delta_after = net_delta - lots_needed * hedge_delta_per_lot

        return HedgeSuggestion(
            needed=True,
            reason=f"Net delta +{net_delta:.1f} exceeds threshold {threshold}",
            action="BUY",
            instrument_desc=f"ATM PE (strike ~{atm_strike:.0f})",
            quantity=lots_needed,
            estimated_cost_inr=cost,
            net_delta_before=net_delta,
            net_delta_after=net_delta_after,
        )

    ce_rows = chain_df[
        (chain_df["strike"] == atm_strike) & (chain_df["opt_type"] == "CE")
    ]
    if ce_rows.empty:
        ce_typed = chain_df[chain_df["opt_type"] == "CE"]
        if ce_typed.empty:
            return HedgeSuggestion(needed=False, reason="No CE options available for hedge")
        nearest_idx = (ce_typed["strike"] - spot).abs().idxmin()
        ce_rows = chain_df.loc[[nearest_idx]]
        atm_strike = float(ce_rows["strike"].iloc[0])

    ce_ltp = float(ce_rows["ltp"].iloc[0])
    hedge_delta_per_lot = 0.5 * lot_size
    lots_needed = math.ceil(abs(net_delta) / hedge_delta_per_lot)
    cost = lots_needed * ce_ltp * lot_size
    net_delta_after = net_delta + lots_needed * hedge_delta_per_lot

    return HedgeSuggestion(
        needed=True,
        reason=f"Net delta {net_delta:.1f} exceeds threshold -{threshold}",
        action="BUY",
        instrument_desc=f"ATM CE (strike ~{atm_strike:.0f})",
        quantity=lots_needed,
        estimated_cost_inr=cost,
        net_delta_before=net_delta,
        net_delta_after=net_delta_after,
    )
