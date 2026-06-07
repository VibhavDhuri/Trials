"""
India VIX historical data — fetches and caches 30-day VIX history for trend chart.
NSE publishes VIX via the same historical candle endpoint as index data.
"""
from __future__ import annotations

import datetime
import random
from dataclasses import dataclass

import plotly.graph_objects as go

from config import IST
from store.local_store import load, save

VIX_INSTRUMENT_KEY = "NSE_INDEX|India VIX"
_STORE_KEY = "vix_history"


@dataclass
class VIXPoint:
    date: str
    open: float
    high: float
    low: float
    close: float


def _synthetic_vix_points(days: int = 30) -> list[VIXPoint]:
    rng = random.Random(42)
    points: list[VIXPoint] = []
    base = 14.8
    today = datetime.date.today()
    cal_days_needed = days + 14
    count = 0
    for offset in range(cal_days_needed - 1, -1, -1):
        d = today - datetime.timedelta(days=offset)
        if d.weekday() >= 5:
            continue
        base += rng.uniform(-0.4, 0.4)
        base = max(11.0, min(22.0, base))
        noise = rng.uniform(0.2, 0.8)
        o = round(base + rng.uniform(-0.15, 0.15), 2)
        h = round(base + noise, 2)
        lo = round(base - noise, 2)
        c = round(base + rng.uniform(-0.2, 0.2), 2)
        points.append(VIXPoint(date=d.isoformat(), open=o, high=h, low=lo, close=c))
        count += 1
        if count >= days:
            break
    return sorted(points, key=lambda p: p.date)


def get_vix_history(client, days: int = 30) -> list[VIXPoint]:
    today_str = datetime.date.today().isoformat()
    cached = load(_STORE_KEY, {})
    if isinstance(cached, dict) and cached.get("date") == today_str:
        raw_points = cached.get("points", [])
        if raw_points:
            all_points = [VIXPoint(**p) for p in raw_points]
            return all_points[-days:]

    if client is None:
        points = _synthetic_vix_points(days)
        save(_STORE_KEY, {"date": today_str, "points": [p.__dict__ for p in points]})
        return points

    try:
        to_date = datetime.date.today()
        from_date = to_date - datetime.timedelta(days=days + 10)
        candles = client.get_historical_candles(
            VIX_INSTRUMENT_KEY,
            "day",
            from_date.isoformat(),
            to_date.isoformat(),
        )
        if not candles:
            raise ValueError("Empty candle response")

        points: list[VIXPoint] = []
        for candle in candles:
            ts, o, h, lo, c = candle[0], candle[1], candle[2], candle[3], candle[4]
            if isinstance(ts, str):
                date_str = ts[:10]
            else:
                date_str = str(ts)[:10]
            points.append(VIXPoint(date=date_str, open=float(o), high=float(h), low=float(lo), close=float(c)))

        points = sorted(points, key=lambda p: p.date)[-days:]
        save(_STORE_KEY, {"date": today_str, "points": [p.__dict__ for p in points]})
        return points

    except Exception:
        points = _synthetic_vix_points(days)
        save(_STORE_KEY, {"date": today_str, "points": [p.__dict__ for p in points]})
        return points


def vix_history_fig(points: list[VIXPoint], current_vix: float) -> go.Figure:
    dates = [p.date for p in points]
    closes = [p.close for p in points]

    min_date = dates[0] if dates else "2024-01-01"
    max_date = dates[-1] if dates else "2024-01-31"

    shapes = [
        dict(
            type="rect",
            xref="x",
            yref="y",
            x0=min_date,
            x1=max_date,
            y0=0,
            y1=12,
            fillcolor="rgba(0,200,80,0.08)",
            line_width=0,
            layer="below",
        ),
        dict(
            type="rect",
            xref="x",
            yref="y",
            x0=min_date,
            x1=max_date,
            y0=20,
            y1=max(max(closes, default=25) + 5, 30),
            fillcolor="rgba(220,50,50,0.08)",
            line_width=0,
            layer="below",
        ),
    ]

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=dates,
            y=closes,
            mode="lines",
            fill="tozeroy",
            fillcolor="rgba(99,110,250,0.15)",
            line=dict(color="rgba(99,110,250,0.9)", width=2),
            name="VIX Close",
        )
    )

    fig.add_hline(
        y=12,
        line=dict(color="rgba(0,220,80,0.85)", width=1.5, dash="dash"),
        annotation_text="Complacency (12)",
        annotation_position="right",
        annotation_font=dict(color="rgba(0,220,80,0.85)", size=11),
    )
    fig.add_hline(
        y=20,
        line=dict(color="rgba(220,50,50,0.85)", width=1.5, dash="dash"),
        annotation_text="Fear (20)",
        annotation_position="right",
        annotation_font=dict(color="rgba(220,50,50,0.85)", size=11),
    )
    fig.add_hline(
        y=current_vix,
        line=dict(color="rgba(255,255,255,0.75)", width=1.5, dash="dash"),
        annotation_text=f"Current ({current_vix:.2f})",
        annotation_position="right",
        annotation_font=dict(color="rgba(255,255,255,0.75)", size=11),
    )

    fig.update_layout(
        title="India VIX — 30 Day History",
        template="plotly_dark",
        height=280,
        shapes=shapes,
        margin=dict(l=50, r=80, t=40, b=30),
        showlegend=False,
        xaxis=dict(rangeslider=dict(visible=False), showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.08)"),
    )

    return fig
