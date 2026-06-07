"""
NSE F&O sector classification and sector performance heatmap.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

import plotly.graph_objects as go

from data.upstox_client import UpstoxClient

SECTOR_MAP: dict[str, list[str]] = {
    "Banking":      ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK"],
    "IT":           ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM"],
    "Pharma":       ["SUNPHARMA", "DRREDDY", "DIVISLAB"],
    "Auto":         ["MARUTI", "TATAMOTORS", "BAJAJ-AUTO"],
    "Energy":       ["RELIANCE", "ONGC", "BPCL", "COALINDIA"],
    "FMCG":         ["HINDUNILVR", "NESTLEIND", "ASIANPAINT"],
    "Metal":        ["TATASTEEL", "HINDALCO", "JSWSTEEL"],
    "Infra/Realty": ["LT", "ADANIPORTS", "DLF"],
}

_SECTOR_ORDER = list(SECTOR_MAP.keys())


@dataclass
class SectorData:
    sector: str
    change_pct: float
    stocks: list[tuple[str, float]]


def get_sector_instrument_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    for symbols in SECTOR_MAP.values():
        for sym in symbols:
            keys[sym] = f"NSE_EQ|{sym}"
    return keys


def fetch_sector_performance(client: Optional[UpstoxClient]) -> list[SectorData]:
    if client is None:
        result: list[SectorData] = []
        for sector, symbols in SECTOR_MAP.items():
            stocks: list[tuple[str, float]] = [
                (sym, round(random.uniform(-2.0, 2.0), 2)) for sym in symbols
            ]
            avg = sum(pct for _, pct in stocks) / len(stocks)
            result.append(SectorData(sector=sector, change_pct=round(avg, 2), stocks=stocks))
        result.sort(key=lambda s: s.change_pct, reverse=True)
        return result

    instrument_keys = get_sector_instrument_keys()
    all_symbols = list(instrument_keys.keys())
    all_keys = list(instrument_keys.values())

    quotes: dict = {}
    batch_size = 20
    for i in range(0, len(all_keys), batch_size):
        batch = all_keys[i : i + batch_size]
        try:
            batch_quotes = client.get_market_quotes(batch)
            quotes.update(batch_quotes)
        except Exception:
            pass

    symbol_change: dict[str, float] = {}
    for sym in all_symbols:
        ikey = instrument_keys[sym]
        data = quotes.get(ikey, {})
        if not data:
            for k, v in quotes.items():
                if sym.lower() in k.lower():
                    data = v
                    break
        ltp = float(data.get("last_price", 0) or 0)
        close = float(data.get("close_price", 1) or 1)
        if close == 0:
            close = 1.0
        symbol_change[sym] = (ltp / close - 1) * 100

    result = []
    for sector, symbols in SECTOR_MAP.items():
        stocks = [(sym, round(symbol_change.get(sym, 0.0), 2)) for sym in symbols]
        avg = sum(pct for _, pct in stocks) / len(stocks) if stocks else 0.0
        result.append(SectorData(sector=sector, change_pct=round(avg, 2), stocks=stocks))

    result.sort(key=lambda s: s.change_pct, reverse=True)
    return result


def sector_heatmap_fig(data: list[SectorData]) -> go.Figure:
    ordered = sorted(data, key=lambda s: _SECTOR_ORDER.index(s.sector) if s.sector in _SECTOR_ORDER else 99)

    sectors = [s.sector for s in ordered]
    values = [s.change_pct for s in ordered]

    row1_sectors = sectors[:4]
    row1_values  = values[:4]
    row2_sectors = sectors[4:]
    row2_values  = values[4:]

    while len(row2_sectors) < 4:
        row2_sectors.append("")
        row2_values.append(float("nan"))

    z = [row1_values, row2_values]
    text_grid = [
        [f"{s}\n{v:+.1f}%" if s else "" for s, v in zip(row1_sectors, row1_values)],
        [f"{s}\n{v:+.1f}%" if s else "" for s, v in zip(row2_sectors, row2_values)],
    ]

    colorscale = [
        [0.0,  "rgb(178,24,43)"],
        [0.5,  "rgb(255,255,191)"],
        [1.0,  "rgb(26,150,65)"],
    ]

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            text=text_grid,
            texttemplate="%{text}",
            colorscale=colorscale,
            zmin=-3,
            zmax=3,
            showscale=False,
            xgap=3,
            ygap=3,
        )
    )
    fig.update_layout(
        template="plotly_dark",
        height=250,
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        title="Sector Performance",
        xaxis={"showticklabels": False},
        yaxis={"showticklabels": False},
    )
    return fig
