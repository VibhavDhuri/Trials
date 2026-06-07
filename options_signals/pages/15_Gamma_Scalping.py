"""
Gamma Scalping Tracker — manage delta-hedging sessions for long-gamma positions.
"""
from __future__ import annotations

import os
import sys

import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import INDICES
from utils.helpers import now_ist

st.set_page_config(page_title="Gamma Scalping", page_icon="⚡", layout="wide")

try:
    from analysis.gamma_scalping import (
        GammaScalpingSession, HedgeTrade,
        create_session, get_sessions, get_session, close_session,
        record_hedge, compute_session_delta, check_and_suggest_hedge, session_summary,
    )
    from positions.tracker import get_open_positions
    from data.options_chain import OptionsChainFetcher
    from data.market_data import MarketDataFetcher
    _HAS_GS = True
except ImportError as _e:
    _HAS_GS = False
    _GS_ERR = str(_e)

with st.sidebar:
    st.title("⚡ Gamma Scalping")
    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")
    st.divider()
    st.info(
        "Gamma scalping: hold a long straddle/strangle and delta-hedge by trading "
        "the underlying as spot moves. Profit from realised volatility exceeding IV paid."
    )

st.title("⚡ Gamma Scalping Tracker")

if not _HAS_GS:
    st.error(f"Gamma scalping module unavailable: {_GS_ERR}")
    st.stop()

client  = st.session_state.get("client")
offline = st.session_state.get("offline", True)

# ── Create new session ────────────────────────────────────────────────────────
st.subheader("New Scalping Session")
with st.form("gs_new_session"):
    _c1, _c2, _c3, _c4 = st.columns(4)
    _gs_sym    = _c1.selectbox("Index", list(INDICES.keys()), key="gs_sym")
    _gs_expiry = _c2.text_input("Expiry (YYYY-MM-DD)", value="2025-06-26", key="gs_exp")
    _gs_strike = _c3.number_input("ATM Strike", 1000.0, 100000.0, 22500.0, step=50.0)
    _gs_thresh = _c4.number_input("Hedge threshold (Δ lots)", 0.5, 20.0, 5.0, step=0.5,
                                   help="Trigger a hedge when |net delta| exceeds this many lot-equivalents.")
    _gs_note   = st.text_input("Notes (optional)")
    if st.form_submit_button("Create Session", type="primary"):
        _sess = create_session(
            symbol=_gs_sym,
            expiry=_gs_expiry,
            strike=float(_gs_strike),
            hedge_threshold=float(_gs_thresh),
            notes=_gs_note,
        )
        st.success(f"Session created: {_sess.id[:8]}…")
        st.rerun()

st.divider()

# ── Active sessions ───────────────────────────────────────────────────────────
sessions = get_sessions(status="OPEN")

if not sessions:
    st.info("No active gamma scalping sessions. Create one above.")
else:
    for sess in sessions:
        with st.expander(
            f"📍 {sess.symbol} | Strike {sess.strike:,.0f} | Expiry {sess.expiry} | "
            f"Started {sess.start_time[:16]}",
            expanded=True,
        ):
            # Fetch current chain for delta computation
            @st.cache_data(ttl=60, show_spinner=False)
            def _load_chain_gs(sym, exp, _off):
                import pandas as pd
                if _off or not st.session_state.get("client"):
                    return pd.DataFrame(), 22500.0
                _ocf = OptionsChainFetcher(st.session_state.get("client"), offline=False)
                _mdf = MarketDataFetcher(st.session_state.get("client"), offline=False)
                _sp = float(_mdf.get_spot(sym).get("last_price", 22500) or 22500)
                return _ocf.get_chain_df(sym, exp, _sp), _sp

            chain_df, current_spot = _load_chain_gs(sess.symbol, sess.expiry, offline)

            open_pos = [p for p in get_open_positions() if p.symbol == sess.symbol and p.expiry == sess.expiry]

            net_delta = compute_session_delta(sess, open_pos, chain_df, INDICES[sess.symbol].lot_size)
            suggestion = check_and_suggest_hedge(sess, open_pos, chain_df, INDICES[sess.symbol].lot_size)
            summ = session_summary(sess, current_spot)

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Net Session Delta", f"{net_delta:+.2f}")
            m2.metric("Hedge Threshold", f"±{sess.hedge_threshold:.1f}")
            m3.metric("Hedge P&L (MtM)", f"₹{summ['hedge_pnl']:+,.0f}")
            m4.metric("Trades Logged", summ["num_trades"])

            if suggestion:
                st.warning(
                    f"⚡ **Hedge suggested:** {suggestion['action']} "
                    f"**{suggestion['lots']} lot(s)** of underlying  \n"
                    f"Net delta before: {suggestion['delta_before']:+.2f} → "
                    f"after: {suggestion['delta_after']:+.2f}"
                )

            # Record a hedge trade
            st.markdown("**Log a Hedge Trade**")
            hc1, hc2, hc3 = st.columns(3)
            _h_action = hc1.selectbox("Action", ["BUY", "SELL"], key=f"ha_{sess.id}")
            _h_lots   = hc2.number_input("Lots", 1, 100, 1, key=f"hl_{sess.id}")
            _h_price  = hc3.number_input("Executed Price ₹", 0.01, 200000.0, float(current_spot), step=1.0, key=f"hp_{sess.id}")
            if st.button("Log Hedge", key=f"log_{sess.id}"):
                record_hedge(sess.id, _h_action, int(_h_lots), float(_h_price))
                st.success("Hedge trade logged.")
                st.rerun()

            # Hedge trade history
            if sess.hedge_trades:
                _ht_df = pd.DataFrame([
                    {"Time": t.timestamp[:16], "Action": t.action,
                     "Lots": t.lots, "Price": f"₹{t.hedge_price:,.2f}"}
                    for t in sess.hedge_trades
                ])
                st.dataframe(_ht_df, use_container_width=True, hide_index=True)

            if st.button("Close Session", key=f"close_{sess.id}", type="secondary"):
                close_session(sess.id)
                st.success("Session closed.")
                st.rerun()

st.divider()

# ── Closed sessions ───────────────────────────────────────────────────────────
with st.expander("📋 Closed Sessions"):
    closed = get_sessions(status="CLOSED")
    if closed:
        _rows = []
        for s in closed:
            _sm = session_summary(s, s.strike)
            _rows.append({
                "Symbol": s.symbol,
                "Strike": s.strike,
                "Expiry": s.expiry,
                "Started": s.start_time[:16],
                "Closed": (s.end_time or "")[:16],
                "Hedge Trades": _sm["num_trades"],
                "Hedge P&L ₹": f"{_sm['hedge_pnl']:+,.0f}",
            })
        st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No closed sessions yet.")

st.divider()
st.caption(
    "Gamma scalping profits come from realised volatility > IV. "
    "Each hedge locks in a small move profit. Net P&L = hedge gains − premium decay (theta)."
)
