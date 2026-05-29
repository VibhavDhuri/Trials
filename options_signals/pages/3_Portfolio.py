"""
Portfolio — Live P&L tracker, open positions, add/close trades.
"""
from __future__ import annotations

import os
import sys
import datetime

import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import INDICES, IST
from positions.tracker import (
    add_position, close_position, get_open_positions, portfolio_greeks,
    gross_pnl,
)
from utils.helpers import now_ist

st.set_page_config(page_title="Portfolio", page_icon="💼", layout="wide")

with st.sidebar:
    st.title("💼 Portfolio")
    symbol = st.selectbox("Default Index", list(INDICES.keys()), key="port_symbol")
    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")

client  = st.session_state.get("client")
offline = st.session_state.get("offline", True)

# ── Open positions ─────────────────────────────────────────────────────────────
st.title("💼 Portfolio")

positions = get_open_positions()

if not positions:
    st.info("No open positions. Use the form below to add a paper trade.")
else:
    # Build display dataframe — fetch current LTP for P&L
    rows = []
    for p in positions:
        # In live mode we'd fetch current LTP; use entry price as proxy here
        current_ltp = p.entry_price  # placeholder — real: fetch from client
        pnl = gross_pnl(p, current_ltp)
        rows.append({
            "ID":         p.id[:8],
            "Symbol":     p.symbol,
            "Expiry":     p.expiry,
            "Strike":     int(p.strike),
            "Type":       p.opt_type,
            "Action":     p.action,
            "Qty (lots)": p.quantity,
            "Entry ₹":    f"{p.entry_price:.2f}",
            "LTP ₹":      f"{current_ltp:.2f}",
            "P&L ₹":      f"{pnl:+.2f}",
            "Source":     p.source,
        })
    df_pos = pd.DataFrame(rows)

    def _color_pnl(val: str) -> str:
        try:
            v = float(val.replace(",", ""))
            return "color: #4CAF50" if v >= 0 else "color: #F44336"
        except Exception:
            return ""

    styled = df_pos.style.applymap(_color_pnl, subset=["P&L ₹"])
    st.dataframe(styled, use_container_width=True)

    # Portfolio totals
    total_pnl = sum(gross_pnl(p, p.entry_price) for p in positions)
    st.metric("Total Unrealised P&L", f"₹{total_pnl:+,.2f}")

    # Portfolio Greeks
    greeks = portfolio_greeks(positions)
    if any(v != 0 for v in greeks.values()):
        st.subheader("Portfolio Greeks")
        g1, g2, g3, g4 = st.columns(4)
        g1.metric("Net Delta",  f"{greeks.get('delta', 0):+.4f}")
        g2.metric("Net Gamma",  f"{greeks.get('gamma', 0):+.4f}")
        g3.metric("Net Theta",  f"{greeks.get('theta', 0):+.2f} / day")
        g4.metric("Net Vega",   f"{greeks.get('vega',  0):+.2f} / 1%IV")

    st.caption(
        "⚠️ P&L shown at entry price (no live feed in current view). "
        "Refresh the page to get updated prices from scanner or signals pages."
    )

    # ── Close position ────────────────────────────────────────────────────────
    st.subheader("Close a Position")
    pos_ids = {f"{p.symbol} {p.opt_type} {int(p.strike)} (ID:{p.id[:8]})": p.id
               for p in positions}
    selected_label = st.selectbox("Select position to close", list(pos_ids.keys()))
    exit_price_input = st.number_input("Exit price (₹)", min_value=0.01, value=1.0, step=0.05)

    if st.button("Close Position", type="primary"):
        pos_id = pos_ids[selected_label]
        closed = close_position(pos_id, exit_price_input)
        if closed:
            st.success(f"Position closed at ₹{exit_price_input:.2f}")
            st.rerun()
        else:
            st.error("Could not close position — it may already be closed.")

st.divider()

# ── Add position form ─────────────────────────────────────────────────────────
st.subheader("Add Paper Trade")

with st.form("add_position_form", clear_on_submit=True):
    c1, c2, c3 = st.columns(3)
    sym      = c1.selectbox("Index / Stock", list(INDICES.keys()))
    opt_type = c2.radio("Option Type", ["CE", "PE"], horizontal=True)
    action   = c3.radio("Action", ["BUY", "SELL"], horizontal=True)

    c4, c5, c6 = st.columns(3)
    expiry_str  = c4.text_input("Expiry (YYYY-MM-DD)", value=str(datetime.date.today()))
    strike      = c5.number_input("Strike Price", min_value=1.0, value=22500.0, step=50.0)
    quantity    = c6.number_input("Quantity (lots)", min_value=1, max_value=100, value=1, step=1)

    entry_price = st.number_input("Entry Price (₹)", min_value=0.01, value=100.0, step=0.5)
    strategy_tag = st.text_input("Strategy Tag (optional)", value="")

    submitted = st.form_submit_button("Add Trade", type="primary")
    if submitted:
        try:
            datetime.datetime.strptime(expiry_str, "%Y-%m-%d")
            pos = add_position(
                symbol=sym,
                expiry=expiry_str,
                strike=float(strike),
                opt_type=opt_type,
                action=action,
                quantity=int(quantity),
                entry_price=float(entry_price),
                source="MANUAL",
                strategy_tag=strategy_tag,
            )
            st.success(f"Trade added — ID: {pos.id[:8]}")
            st.rerun()
        except ValueError:
            st.error("Invalid expiry date. Use YYYY-MM-DD format.")

st.divider()
st.caption(
    "⚠️ STT Disclaimer: On exercise/assignment, STT is charged at 0.125% of settlement value "
    "(not premium). For deep-ITM options this can significantly impact P&L. "
    "P&L figures here do not include STT, brokerage, or exchange fees."
)
