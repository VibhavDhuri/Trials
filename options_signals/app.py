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

    # ── Watchlist ─────────────────────────────────────────────────────────────
    try:
        from data.watchlist import load_watchlist, fetch_prices, add_to_watchlist, remove_from_watchlist, WatchlistItem
        @st.cache_data(ttl=30, show_spinner=False)
        def _wl_prices(_offline):
            items = load_watchlist()
            cl = st.session_state.get("client") if not _offline else None
            return fetch_prices(cl, items), items
        _wl_data, _wl_items = _wl_prices(is_offline)
        st.markdown("**Watchlist**")
        for _wp in _wl_data:
            _col = "green" if _wp["change_pct"] >= 0 else "red"
            st.markdown(
                f"<span style='font-size:0.85em'>{_wp['display_name']}</span>  "
                f"<b>{_wp['ltp']:,.2f}</b>  "
                f"<span style='color:{_col}'>{'+' if _wp['change_pct']>=0 else ''}{_wp['change_pct']:.2f}%</span>",
                unsafe_allow_html=True,
            )
        with st.expander("Manage Watchlist"):
            for _wi in _wl_items:
                _wa, _wb = st.columns([4, 1])
                _wa.caption(_wi.display_name)
                if _wb.button("✕", key=f"wl_rm_{_wi.symbol}"):
                    remove_from_watchlist(_wi.symbol)
                    st.rerun()
            _new_sym = st.text_input("Add symbol (e.g. HDFCBANK)", key="wl_add_sym")
            _new_key = st.text_input("Instrument key (e.g. NSE_EQ|HDFCBANK)", key="wl_add_key")
            if st.button("Add") and _new_sym and _new_key:
                add_to_watchlist(WatchlistItem(_new_sym, _new_key, _new_sym))
                st.rerun()
    except ImportError:
        pass

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
    ("📋", "Orders",            "Order book — all executed trades by source and strategy, tax report"),
    ("🛡", "Risk",              "Position sizing, daily loss limits, circuit breaker, delta hedge"),
    ("🎯", "Scenario",          "Stress-test portfolio — reprice under spot + IV moves"),
    ("🧮", "Calculator",        "Standalone options pricer, Probability of Profit, break-even table"),
    ("📅", "Calendar",          "Economic & events calendar — RBI, Fed, expiry, earnings dates"),
    ("📓", "Journal",           "Trade journal — notes, tags, conviction, mood per trade"),
    ("📊", "Performance",       "Equity curve, Sharpe, Sortino, monthly P&L heatmap, drawdown"),
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
