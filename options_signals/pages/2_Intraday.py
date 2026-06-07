"""
Intraday Chart — 1-min / 5-min candlestick chart with VWAP, 9-EMA, 21-EMA.
"""
from __future__ import annotations

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import INDICES, IST
from data.intraday import fetch_intraday
from utils.helpers import now_ist

st.set_page_config(page_title="Intraday Chart", page_icon="🕯", layout="wide")

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# ── Sidebar controls ──────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🕯 Intraday Chart")
    symbol   = st.selectbox("Index", list(INDICES.keys()), key="chart_symbol")
    interval = st.radio("Interval", ["1minute", "5minute"], horizontal=True)
    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")

client = st.session_state.get("client")

# ── Fetch data ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def _get_intraday(symbol: str, interval: str, _offline: bool):
    return fetch_intraday(symbol, None if _offline else client, interval)

st.title(f"🕯 {symbol} — Intraday ({interval})")

with st.spinner("Loading candles…"):
    offline = st.session_state.get("offline", True)
    df = _get_intraday(symbol, interval, offline)

if df.empty:
    st.warning("No intraday data available.")
    st.stop()

current_price = float(df["close"].iloc[-1])
open_price    = float(df["open"].iloc[0])
pct_chg       = (current_price - open_price) / open_price * 100

# ── Header metrics ────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Last Price", f"₹{current_price:,.2f}", f"{pct_chg:+.2f}%")
c2.metric("Open",       f"₹{open_price:,.2f}")
c3.metric("Day High",   f"₹{float(df['high'].max()):,.2f}")
c4.metric("Day Low",    f"₹{float(df['low'].min()):,.2f}")

if not HAS_PLOTLY:
    st.error("Plotly is required for charts. Run: pip install plotly")
    st.dataframe(df.tail(30))
    st.stop()

# ── Candlestick + VWAP + EMAs ─────────────────────────────────────────────────
fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    row_heights=[0.75, 0.25],
    vertical_spacing=0.03,
)

# Candlesticks
fig.add_trace(go.Candlestick(
    x=df["datetime"],
    open=df["open"], high=df["high"], low=df["low"], close=df["close"],
    name="Price",
    increasing_line_color="#26a69a",
    decreasing_line_color="#ef5350",
), row=1, col=1)

# VWAP
if "vwap" in df.columns:
    fig.add_trace(go.Scatter(
        x=df["datetime"], y=df["vwap"],
        name="VWAP", line=dict(color="#FFD700", width=1.8, dash="dot"),
    ), row=1, col=1)

# EMAs
if "ema9" in df.columns:
    fig.add_trace(go.Scatter(
        x=df["datetime"], y=df["ema9"],
        name="9-EMA", line=dict(color="#42A5F5", width=1.4),
    ), row=1, col=1)

if "ema21" in df.columns:
    fig.add_trace(go.Scatter(
        x=df["datetime"], y=df["ema21"],
        name="21-EMA", line=dict(color="#FF7043", width=1.4),
    ), row=1, col=1)

# Current price horizontal line
fig.add_hline(
    y=current_price, line_dash="dash", line_color="white", line_width=1,
    annotation_text=f"LTP {current_price:,.0f}",
    annotation_position="right",
    row=1, col=1,
)

# Volume bars
colors = ["#26a69a" if c >= o else "#ef5350"
          for c, o in zip(df["close"], df["open"])]
fig.add_trace(go.Bar(
    x=df["datetime"], y=df["volume"],
    name="Volume", marker_color=colors, showlegend=False,
), row=2, col=1)

fig.update_layout(
    height=600,
    template="plotly_dark",
    xaxis_rangeslider_visible=False,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=40, r=40, t=20, b=20),
)
fig.update_yaxes(title_text="Price (₹)", row=1, col=1)
fig.update_yaxes(title_text="Volume",    row=2, col=1)

st.plotly_chart(fig, use_container_width=True)

# ── Legend note ───────────────────────────────────────────────────────────────
st.caption(
    "**VWAP** uses typical price (H+L+C)/3 per candle.  "
    "Data cached for 60 seconds.  "
    "Offline mode uses generated sample candles."
)
