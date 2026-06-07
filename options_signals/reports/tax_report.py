"""
Tax P&L report for F&O trading — simplified for Indian ITR-3 filing.
F&O is treated as business income (non-speculative) under Section 43(5).
"""
from __future__ import annotations

import datetime
import io
from typing import Any

import pandas as pd

from config import INDICES
from positions.tracker import Position, realised_pnl


def financial_year_range(fy: str) -> tuple[datetime.date, datetime.date]:
    start_year = int(fy.split("-")[0])
    return (
        datetime.date(start_year, 4, 1),
        datetime.date(start_year + 1, 3, 31),
    )


def generate_tax_report(
    positions: list[Any],
    fy: str = "2025-26",
) -> tuple[pd.DataFrame, dict]:
    fy_start, fy_end = financial_year_range(fy)

    rows: list[dict] = []
    for pos in positions:
        if pos.status != "CLOSED":
            continue
        if pos.exit_time is None:
            continue
        exit_date_str = pos.exit_time[:10]
        try:
            exit_date = datetime.date.fromisoformat(exit_date_str)
        except ValueError:
            continue
        if not (fy_start <= exit_date <= fy_end):
            continue

        lot_size = INDICES[pos.symbol].lot_size if pos.symbol in INDICES else 1
        gross = realised_pnl(pos)
        stt_estimate = 0.00125 * abs((pos.exit_price or 0.0) * pos.quantity * lot_size)
        net = gross - stt_estimate

        entry_date_str = pos.entry_time[:10] if pos.entry_time else ""

        rows.append(
            {
                "symbol":       pos.symbol,
                "expiry":       pos.expiry,
                "strike":       pos.strike,
                "opt_type":     pos.opt_type,
                "action":       pos.action,
                "quantity":     pos.quantity,
                "entry_date":   entry_date_str,
                "exit_date":    exit_date_str,
                "entry_price":  pos.entry_price,
                "exit_price":   pos.exit_price,
                "gross_pnl":    gross,
                "stt_estimate": stt_estimate,
                "net_pnl":      net,
            }
        )

    df = pd.DataFrame(
        rows,
        columns=[
            "symbol", "expiry", "strike", "opt_type", "action", "quantity",
            "entry_date", "exit_date", "entry_price", "exit_price",
            "gross_pnl", "stt_estimate", "net_pnl",
        ],
    )

    turnover = 0.0
    for pos in positions:
        if pos.status != "CLOSED":
            continue
        if pos.exit_time is None:
            continue
        exit_date_str = pos.exit_time[:10]
        try:
            exit_date = datetime.date.fromisoformat(exit_date_str)
        except ValueError:
            continue
        if not (fy_start <= exit_date <= fy_end):
            continue
        lot_size = INDICES[pos.symbol].lot_size if pos.symbol in INDICES else 1
        turnover += abs(pos.entry_price * pos.quantity * lot_size)
        turnover += abs((pos.exit_price or 0.0) * pos.quantity * lot_size)

    summary: dict = {
        "fy":           fy,
        "total_trades": len(df),
        "turnover":     turnover,
        "gross_pnl":    float(df["gross_pnl"].sum()) if not df.empty else 0.0,
        "stt_total":    float(df["stt_estimate"].sum()) if not df.empty else 0.0,
        "net_pnl":      float(df["net_pnl"].sum()) if not df.empty else 0.0,
    }
    return df, summary


def to_csv(df: pd.DataFrame) -> str:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()
