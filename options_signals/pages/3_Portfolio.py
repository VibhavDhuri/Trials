"""
Portfolio — Live P&L tracker with real-time LTP refresh, open positions, add/close trades.
"""
from __future__ import annotations

import os
import sys
import datetime
import random

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

# Auto-refresh every 30s when market is open
try:
    from streamlit_autorefresh import st_autorefresh
    from utils.helpers import is_market_open
    if is_market_open():
        st_autorefresh(interval=30_000, key="portfolio_refresh")
except Exception:
    pass

with st.sidebar:
    st.title("💼 Portfolio")
    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")
    if st.button("↻ Refresh Prices"):
        # Clear cached prices so next load re-fetches
        st.session_state.pop("portfolio_ltp_map", None)
        st.rerun()

client  = st.session_state.get("client")
offline = st.session_state.get("offline", True)


def _fetch_live_ltps(positions) -> dict:
    """
    Build {(symbol, expiry, strike, opt_type): ltp} for all open positions.
    In offline mode: simulate ±8% random drift around entry price (seeded per run).
    """
    ltp_map: dict = {}
    if offline or client is None:
        rng = random.Random()  # unseeded — drifts each refresh
        for p in positions:
            drift = rng.gauss(0, 0.04)   # ±4% noise
            ltp_map[(p.symbol, p.expiry, p.strike, p.opt_type)] = max(
                0.05, p.entry_price * (1 + drift)
            )
        return ltp_map

    # Live mode: fetch chain for each unique (symbol, expiry) pair
    from data.options_chain import OptionsChainFetcher
    from data.market_data import MarketDataFetcher
    ocf = OptionsChainFetcher(client, offline=False)
    mdf = MarketDataFetcher(client, offline=False)

    combos: set = {(p.symbol, p.expiry) for p in positions}
    for symbol, expiry in combos:
        try:
            spot_data = mdf.get_spot(symbol)
            spot = float(spot_data.get("last_price", 0) or 0)
            if spot <= 0:
                continue
            df = ocf.get_chain_df(symbol, expiry, spot)
            for _, row in df.iterrows():
                key = (row["spot"], row["expiry"], row["strike"], row["opt_type"])
                ltp_map[key] = float(row.get("ltp", 0) or 0)
        except Exception:
            continue

    # Fall back to entry price for any position not found in chain
    for p in positions:
        key = (p.symbol, p.expiry, p.strike, p.opt_type)
        if key not in ltp_map or ltp_map[key] <= 0:
            ltp_map[key] = p.entry_price
    return ltp_map


def _build_greek_lookup(positions) -> dict:
    """Build chain_lookup for portfolio_greeks from cached or freshly fetched chain."""
    if offline or client is None:
        return {}
    from data.options_chain import OptionsChainFetcher
    from data.market_data import MarketDataFetcher
    ocf = OptionsChainFetcher(client, offline=False)
    mdf = MarketDataFetcher(client, offline=False)
    lookup: dict = {}
    for symbol, expiry in {(p.symbol, p.expiry) for p in positions}:
        try:
            spot = float(mdf.get_spot(symbol).get("last_price", 0) or 0)
            df = ocf.get_chain_df(symbol, expiry, spot)
            for _, row in df.iterrows():
                key = (row.get("spot", symbol), row["expiry"], row["strike"], row["opt_type"])
                lookup[key] = {
                    "delta": row.get("delta", 0),
                    "gamma": row.get("gamma", 0),
                    "theta": row.get("theta", 0),
                    "vega":  row.get("vega",  0),
                }
        except Exception:
            continue
    return lookup


# ── Open positions ────────────────────────────────────────────────────────────
st.title("💼 Portfolio")

positions = get_open_positions()

if not positions:
    st.info("No open positions. Use the form below to add a paper trade.")
else:
    # Fetch live LTPs (cached in session state; cleared by Refresh button)
    if "portfolio_ltp_map" not in st.session_state:
        with st.spinner("Fetching live prices…"):
            st.session_state["portfolio_ltp_map"] = _fetch_live_ltps(positions)

    ltp_map = st.session_state["portfolio_ltp_map"]

    rows = []
    for p in positions:
        key = (p.symbol, p.expiry, p.strike, p.opt_type)
        current_ltp = ltp_map.get(key, p.entry_price)
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
            v = float(val.replace(",", "").replace("+", ""))
            return "color: #4CAF50" if v >= 0 else "color: #F44336"
        except Exception:
            return ""

    styled = df_pos.style.applymap(_color_pnl, subset=["P&L ₹"])
    st.dataframe(styled, use_container_width=True)

    # Totals
    total_unrealised = sum(
        gross_pnl(p, ltp_map.get((p.symbol, p.expiry, p.strike, p.opt_type), p.entry_price))
        for p in positions
    )
    mode_note = "(simulated drift)" if offline else "(live LTP)"
    st.metric("Total Unrealised P&L", f"₹{total_unrealised:+,.2f}",
              help=f"Based on current LTPs {mode_note}. Auto-refreshes every 30s during market hours.")

    # Portfolio Greeks (live mode only — needs chain data)
    if not offline and client:
        with st.expander("Portfolio Greeks (fetches chain data)"):
            with st.spinner("Computing Greeks…"):
                greek_lookup = _build_greek_lookup(positions)
            greeks = portfolio_greeks(positions, greek_lookup)
            if any(v != 0 for v in greeks.values()):
                g1, g2, g3, g4 = st.columns(4)
                g1.metric("Net Delta", f"{greeks['delta']:+.4f}")
                g2.metric("Net Gamma", f"{greeks['gamma']:+.4f}")
                g3.metric("Net Theta", f"{greeks['theta']:+.2f}/day")
                g4.metric("Net Vega",  f"{greeks['vega']:+.2f}/1%IV")
            else:
                st.caption("Greeks not available — chain data could not be fetched.")
    else:
        st.caption("Portfolio Greeks available in live mode only (requires Upstox token).")

    st.divider()

    # ── Auto-exit rules ───────────────────────────────────────────────────────
    try:
        from positions.auto_exit import add_rule as _add_exit, load_rules as _load_exits, cancel_rule as _cancel_exit
        _HAS_AUTOEXIT = True
    except ImportError:
        _HAS_AUTOEXIT = False

    if _HAS_AUTOEXIT:
        with st.expander("🎯 Auto-Exit Rules"):
            st.caption("Set automatic stop-loss and target exits. Run `python positions/run_watcher.py` in the background to activate.")
            _all_rules = _load_exits()
            _active_map = {r.position_id: r for r in _all_rules if r.status == "ACTIVE"}
            for p in positions:
                _rule = _active_map.get(p.id)
                _lbl = f"{p.symbol} {p.opt_type} {int(p.strike)} [{p.id[:8]}]"
                if _rule:
                    _ra, _rb = st.columns([4, 1])
                    _ra.caption(f"✅ {_lbl} — target +{_rule.target_pct:.0f}% | stop -{_rule.stop_loss_pct:.0f}% {'(trailing)' if _rule.trailing_stop else ''}")
                    if _rb.button("Remove", key=f"rm_ae_{p.id}"):
                        _cancel_exit(_rule.id)
                        st.rerun()
                else:
                    _ea, _eb, _ec, _ed = st.columns([2, 2, 1, 1])
                    _tgt   = _ea.number_input("Target % profit", 5.0, 500.0, 40.0, key=f"tgt_{p.id}")
                    _sl    = _eb.number_input("Stop loss %", 5.0, 100.0, 50.0, key=f"sl_{p.id}")
                    _trail = _ec.checkbox("Trailing SL", key=f"tr_{p.id}")
                    _ec.caption(_lbl)
                    if _ed.button("Set", key=f"set_ae_{p.id}", type="primary"):
                        _add_exit(p.id, float(_tgt), float(_sl), bool(_trail))
                        st.success(f"Auto-exit set for {_lbl}")
                        st.rerun()

    st.divider()

    # ── Close position ────────────────────────────────────────────────────────
    st.subheader("Close a Position")
    pos_ids = {f"{p.symbol} {p.opt_type} {int(p.strike)} exp:{p.expiry} (ID:{p.id[:8]})": p.id
               for p in positions}
    selected_label = st.selectbox("Select position to close", list(pos_ids.keys()))

    # Pre-fill exit price from current LTP
    sel_pos = next((p for p in positions if p.id == pos_ids.get(selected_label)), None)
    default_exit = float(ltp_map.get(
        (sel_pos.symbol, sel_pos.expiry, sel_pos.strike, sel_pos.opt_type),
        sel_pos.entry_price if sel_pos else 1.0
    )) if sel_pos else 1.0

    exit_price_input = st.number_input("Exit price (₹)", min_value=0.01,
                                        value=round(default_exit, 2), step=0.05)

    if st.button("Close Position", type="primary"):
        pos_id = pos_ids[selected_label]
        closed = close_position(pos_id, exit_price_input)
        if closed:
            st.session_state.pop("portfolio_ltp_map", None)
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

    entry_price  = st.number_input("Entry Price (₹)", min_value=0.01, value=100.0, step=0.5)
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
            st.session_state.pop("portfolio_ltp_map", None)
            st.success(f"Trade added — ID: {pos.id[:8]}")
            st.rerun()
        except ValueError:
            st.error("Invalid expiry date. Use YYYY-MM-DD format.")

# ── Closed P&L summary ────────────────────────────────────────────────────────
st.divider()
st.subheader("Closed Trade Summary")

from positions.tracker import get_all_positions, realised_pnl
all_pos = get_all_positions()
closed  = [p for p in all_pos if p.status == "CLOSED"]
if closed:
    total_realised = sum(realised_pnl(p) for p in closed)
    wins = sum(1 for p in closed if realised_pnl(p) > 0)
    c1, c2, c3 = st.columns(3)
    c1.metric("Closed Trades", len(closed))
    c2.metric("Win Rate",      f"{wins / len(closed) * 100:.1f}%" if closed else "—")
    c3.metric("Total Realised P&L", f"₹{total_realised:+,.2f}",
              delta_color="normal" if total_realised >= 0 else "inverse")
else:
    st.caption("No closed trades yet.")

st.divider()
st.caption(
    "⚠️ STT Disclaimer: On exercise/assignment, STT = 0.125% of settlement value (not premium). "
    "For deep-ITM options this can exceed gross profit. "
    "P&L figures exclude STT, brokerage, and exchange fees. "
    f"Prices last updated: {now_ist().strftime('%H:%M:%S IST')}. "
    "Press '↻ Refresh Prices' in the sidebar for the latest LTPs."
)
