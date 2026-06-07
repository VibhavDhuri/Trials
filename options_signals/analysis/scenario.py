"""
Scenario analysis — reprice portfolio under hypothetical spot and IV changes.
"""
from __future__ import annotations

from dataclasses import dataclass

import plotly.graph_objects as go

from config import INDICES, RISK_FREE_RATE
from analysis.greeks import bs_price
from positions.tracker import Position
from utils.helpers import days_to_expiry


@dataclass
class ScenarioResult:
    position_id: str
    symbol: str
    expiry: str
    strike: float
    opt_type: str
    action: str
    quantity: int
    lot_size: int
    entry_price: float
    scenario_price: float
    pnl_inr: float


class ScenarioEngine:
    def __init__(self) -> None:
        pass

    def compute(
        self,
        positions: list[Position],
        spot: float,
        chain_lookup: dict,
        spot_change_pct: float,
        iv_change_pts: float,
        days_forward: int,
    ) -> list[ScenarioResult]:
        results: list[ScenarioResult] = []
        new_spot = spot * (1 + spot_change_pct / 100.0)
        for pos in positions:
            if pos.status != "OPEN":
                continue
            key = (pos.symbol, pos.expiry, pos.strike, pos.opt_type)
            chain_entry = chain_lookup.get(key, {})
            current_iv_pct: float = chain_entry.get("iv", 15.0)
            new_iv_frac = max((current_iv_pct + iv_change_pts) / 100.0, 0.01)
            T = max(days_to_expiry(pos.expiry) - days_forward / 365.0, 1.0 / 365.0)
            scenario_price = bs_price(new_spot, pos.strike, T, RISK_FREE_RATE, new_iv_frac, pos.opt_type)
            lot_size = INDICES[pos.symbol].lot_size if pos.symbol in INDICES else 75
            sign = 1 if pos.action == "BUY" else -1
            pnl_inr = (scenario_price - pos.entry_price) * pos.quantity * lot_size * sign
            results.append(ScenarioResult(
                position_id=pos.id,
                symbol=pos.symbol,
                expiry=pos.expiry,
                strike=pos.strike,
                opt_type=pos.opt_type,
                action=pos.action,
                quantity=pos.quantity,
                lot_size=lot_size,
                entry_price=pos.entry_price,
                scenario_price=scenario_price,
                pnl_inr=pnl_inr,
            ))
        return results

    @staticmethod
    def total_pnl(results: list[ScenarioResult]) -> float:
        return sum(r.pnl_inr for r in results)

    def heatmap_data(
        self,
        positions: list[Position],
        spot: float,
        chain_lookup: dict,
        spot_changes: list[float],
        iv_changes: list[float],
    ) -> tuple[list, list, list[list]]:
        spot_labels = [f"{sc:+.1f}%" for sc in spot_changes]
        iv_labels = [f"{iv:+.1f}pp" for iv in iv_changes]
        pnl_matrix: list[list] = []
        for sc in spot_changes:
            row: list[float] = []
            for iv in iv_changes:
                results = self.compute(positions, spot, chain_lookup, sc, iv, 0)
                row.append(self.total_pnl(results))
            pnl_matrix.append(row)
        return spot_labels, iv_labels, pnl_matrix


def scenario_heatmap_fig(
    spot_changes: list[float],
    iv_changes: list[float],
    pnl_matrix: list[list],
) -> go.Figure:
    spot_labels = [f"{sc:+.1f}%" for sc in spot_changes]
    iv_labels = [f"{iv:+.1f}pp" for iv in iv_changes]

    annotations: list[dict] = []
    for i, row in enumerate(pnl_matrix):
        for j, val in enumerate(row):
            annotations.append(dict(
                x=iv_labels[j],
                y=spot_labels[i],
                text=f"₹{val:+,.0f}",
                showarrow=False,
                font=dict(size=11),
            ))

    fig = go.Figure(data=go.Heatmap(
        z=pnl_matrix,
        x=iv_labels,
        y=spot_labels,
        colorscale="RdYlGn",
        showscale=True,
        colorbar=dict(title="P&L (₹)"),
    ))
    fig.update_layout(
        title="Portfolio P&L Scenario Matrix",
        xaxis_title="IV Change",
        yaxis_title="Spot Change",
        annotations=annotations,
        template="plotly_dark",
        height=350,
    )
    return fig
