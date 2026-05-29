"""
Scanner — Scan top 30 F&O stocks for options signals.
"""
from __future__ import annotations

import os
import sys

import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scanner.stock_scanner import scan
from utils.helpers import now_ist

st.set_page_config(page_title="F&O Scanner", page_icon="🔍", layout="wide")

with st.sidebar:
    st.title("🔍 F&O Scanner")
    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")
    st.info("Fetches ATM ±3 strikes only per stock to minimise API load.")

client  = st.session_state.get("client")
offline = st.session_state.get("offline", True)

st.title("🔍 F&O Stock Scanner")
st.caption(
    "Scans top 30 NSE F&O stocks by options liquidity. "
    "Concurrently fetches ATM options (nearest expiry) via ThreadPoolExecutor. "
    "IV Rank is an approximation based on ATM IV vs a stock-type baseline — "
    "treat directionally, not as a precise value."
)

# ── Controls ──────────────────────────────────────────────────────────────────
col1, col2 = st.columns([2, 1])
direction_filter = col1.selectbox(
    "Direction filter",
    ["ALL", "BULLISH", "BEARISH", "NEUTRAL"],
    index=0,
    key="scanner_dir",
)
scan_btn = col2.button("Scan Now", type="primary", use_container_width=True)

if offline:
    st.info("**Offline mode** — showing sample scanner results (randomized seed per stock).")

# ── Run scan ──────────────────────────────────────────────────────────────────
if scan_btn or "scanner_results" not in st.session_state:
    with st.spinner("Scanning 30 F&O stocks… (this may take 10-15 seconds in live mode)"):
        results = scan(
            client=None if offline else client,
            direction_filter=direction_filter,
        )
    st.session_state["scanner_results"] = results
    st.session_state["scanner_filter"]  = direction_filter

results = st.session_state.get("scanner_results", [])

# ── Filter in-place if direction changed without re-scan ─────────────────────
if direction_filter != st.session_state.get("scanner_filter", "ALL"):
    if direction_filter != "ALL":
        results = [r for r in results if r.signal == direction_filter]

if not results:
    st.warning("No results match the selected filter.")
else:
    # ── Results table ─────────────────────────────────────────────────────────
    rows = []
    for r in results:
        rows.append({
            "Stock":       r.ticker,
            "LTP (₹)":     f"{r.ltp:,.2f}",
            "Signal":      r.signal,
            "Confidence":  r.confidence,
            "IV Rank ~":   f"{r.iv_rank_approx:.1f}",
            "PCR":         f"{r.pcr:.3f}",
            "ATM IV %":    f"{r.atm_iv:.2f}",
            "Strategy":    r.strategy,
            "Lot Size":    r.lot_size,
        })

    df = pd.DataFrame(rows)

    def _color_signal(val: str) -> str:
        if val == "BULLISH":  return "color: #4CAF50"
        if val == "BEARISH":  return "color: #F44336"
        return "color: #FFC107"

    def _color_conf(val: str) -> str:
        if val == "HIGH":   return "color: #4CAF50; font-weight: bold"
        if val == "MEDIUM": return "color: #FFC107"
        return "color: #9E9E9E"

    styled = (df.style
              .applymap(_color_signal, subset=["Signal"])
              .applymap(_color_conf,   subset=["Confidence"]))

    st.dataframe(styled, use_container_width=True, height=400)

    # ── Signal breakdown ──────────────────────────────────────────────────────
    st.subheader("Signal Breakdown")
    b1, b2, b3 = st.columns(3)
    bullish_cnt  = sum(1 for r in results if r.signal == "BULLISH")
    bearish_cnt  = sum(1 for r in results if r.signal == "BEARISH")
    neutral_cnt  = len(results) - bullish_cnt - bearish_cnt
    b1.metric("Bullish",  bullish_cnt)
    b2.metric("Bearish",  bearish_cnt)
    b3.metric("Neutral",  neutral_cnt)

    high_conf = [r for r in results if r.confidence == "HIGH"]
    if high_conf:
        st.subheader("High Confidence Picks")
        for r in high_conf[:5]:
            direction_icon = "🟢" if r.signal == "BULLISH" else ("🔴" if r.signal == "BEARISH" else "⚪")
            st.markdown(
                f"{direction_icon} **{r.ticker}** — {r.signal} | {r.strategy} | "
                f"IV≈{r.iv_rank_approx:.0f} | PCR={r.pcr:.2f} | LTP ₹{r.ltp:,.0f}"
            )

st.divider()
st.caption(
    "Results show top 10 by confidence + direction match. "
    "All signals are indicative — not financial advice. "
    "Scan is concurrent (ThreadPoolExecutor, max 4 simultaneous API calls)."
)
