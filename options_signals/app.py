"""
Options Trading Signals — Main entry point.
Streamlit multipage app: each feature has its own page in pages/.
Run: streamlit run app.py
"""
from __future__ import annotations

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))

from auth.upstox_auth import get_stored_token, validate_token, AUTH_INSTRUCTIONS, build_auth_url
from config import INDICES, IST
from data.upstox_client import UpstoxClient
from utils.helpers import is_market_open, market_status, now_ist

st.set_page_config(
    page_title="Options Trading Signals",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Shared client — stored in session state so pages can reuse it ─────────────
if "client" not in st.session_state:
    token = get_stored_token()
    if token and validate_token(token):
        st.session_state.client   = UpstoxClient(token)
        st.session_state.offline  = False
    else:
        st.session_state.client   = None
        st.session_state.offline  = True

is_offline = st.session_state.offline

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("📈 Options Signals")
    st.caption("Indian Derivatives — Powered by Upstox")
    st.divider()

    ms = market_status()
    col1, col2 = st.columns(2)
    col1.metric("Market", ms)
    col2.metric("Mode", "OFFLINE" if is_offline else "LIVE")

    st.divider()
    if is_offline:
        st.warning("**Offline mode** — showing sample data.  \nSet `UPSTOX_ACCESS_TOKEN` in `.env` for live data.")
        with st.expander("How to authenticate"):
            st.code(AUTH_INSTRUCTIONS, language="text")
        if st.button("Get Auth URL"):
            try:
                st.code(build_auth_url())
            except Exception:
                st.error("Set UPSTOX_API_KEY in .env first.")
    else:
        st.success("Connected to Upstox")

    st.divider()
    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")
    st.caption("Auto-refreshes every 30s during market hours.")

# ── Home page ─────────────────────────────────────────────────────────────────
st.title("📈 Options Trading Signals")
st.markdown(
    "**Real-time options intelligence for Indian derivatives.**  \n"
    "Navigate using the sidebar pages:"
)

pages = [
    ("📊", "Signals",          "Live signals, options chain, OI & IV analysis, Greeks heatmap"),
    ("🕯",  "Intraday Chart",   "1-min/5-min candlestick chart with VWAP, 9-EMA, 21-EMA"),
    ("💼", "Portfolio",         "Live P&L tracker, open positions, add/close trades"),
    ("🔧", "Strategy Builder",  "Build multi-leg strategies, payoff diagram, breakeven solver"),
    ("📈", "Backtest",          "Replay signals on 252 days of historical data (indicative)"),
    ("🔍", "Scanner",           "Scan top 30 F&O stocks for options signals"),
    ("🤖", "Mock Trading",      "Paper trading platform — manual trades + autonomous bot"),
]

cols = st.columns(2)
for i, (icon, name, desc) in enumerate(pages):
    with cols[i % 2]:
        st.markdown(
            f"""<div style="border:1px solid #333;border-radius:8px;padding:12px;margin-bottom:8px">
            <b>{icon} {name}</b><br><span style="color:#aaa;font-size:0.85em">{desc}</span>
            </div>""",
            unsafe_allow_html=True,
        )

st.divider()
st.caption(
    "⚠️  Disclaimer: For informational purposes only. Not financial advice. "
    "Options trading involves significant risk of loss. "
    "Past signals do not guarantee future performance."
)
