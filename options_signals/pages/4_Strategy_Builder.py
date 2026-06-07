"""
Strategy Builder — Build multi-leg strategies, payoff diagram, breakeven solver.
"""
from __future__ import annotations

import os
import sys

import streamlit as st
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import INDICES, IST
from positions.builder import Leg, analyse
from positions.tracker import add_position
from data.options_chain import OptionsChainFetcher
from broker.order_manager import execute_paper_or_live, is_live_trading_enabled, OrderManager, get_span_margin
from utils.helpers import now_ist

st.set_page_config(page_title="Strategy Builder", page_icon="🔧", layout="wide")

try:
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

with st.sidebar:
    st.title("🔧 Strategy Builder")
    symbol = st.selectbox("Index", list(INDICES.keys()), key="sb_symbol")
    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")

client  = st.session_state.get("client")
offline = st.session_state.get("offline", True)

st.title("🔧 Multi-Leg Strategy Builder")

# ── Load options chain for strike dropdown ────────────────────────────────────
@st.cache_data(ttl=120, show_spinner=False)
def _load_chain(symbol: str, _offline: bool):
    from data.options_chain import OptionsChainFetcher
    ocf = OptionsChainFetcher(client, offline=_offline)
    expiries = ocf.get_expiries(symbol)
    if not expiries:
        return [], [], None
    exp = expiries[0]
    # rough spot
    from data.market_data import MarketDataFetcher
    mdf = MarketDataFetcher(client, offline=_offline)
    spot_data = mdf.get_spot(symbol)
    spot = float(spot_data.get("last_price", 0) or 22000)
    df = ocf.get_chain_df(symbol, exp, spot)
    strikes = sorted(df["strike"].unique().tolist()) if not df.empty else []
    return expiries, strikes, spot

with st.spinner("Loading chain…"):
    expiries, strikes, spot = _load_chain(symbol, offline)

if not strikes:
    strikes = list(range(22000, 23500, 50))
    spot    = 22500.0
    expiries = ["2025-06-26"]

if not expiries:
    st.warning("Could not load expiry dates.")
    st.stop()

expiry_sel = st.selectbox("Expiry", expiries)

# ── Leg inputs ────────────────────────────────────────────────────────────────
st.subheader("Define Legs (up to 4)")
n_legs = st.slider("Number of legs", 1, 4, 2)

legs: list[Leg] = []
cols = st.columns(n_legs)
for i in range(n_legs):
    with cols[i]:
        st.markdown(f"**Leg {i+1}**")
        opt_type = st.selectbox("Type",   ["CE", "PE"],         key=f"lt_{i}")
        action   = st.selectbox("Action", ["BUY", "SELL"],      key=f"la_{i}")
        default_strike = float(strikes[len(strikes)//2]) if strikes else 22500.0
        strike   = st.selectbox("Strike", strikes, index=len(strikes)//2, key=f"ls_{i}")
        quantity = st.number_input("Qty (lots)", 1, 20, 1, key=f"lq_{i}")
        premium  = st.number_input("Premium ₹", 0.01, 5000.0, 100.0, step=0.5, key=f"lp_{i}")

        legs.append(Leg(
            opt_type=opt_type,
            strike=float(strike),
            action=action,
            quantity=int(quantity),
            premium=float(premium),
        ))

# ── Analyse ───────────────────────────────────────────────────────────────────
if st.button("Analyse Strategy", type="primary"):
    result = analyse(legs, symbol, float(spot or 22500))

    st.subheader("Strategy Analysis")
    m1, m2, m3, m4 = st.columns(4)
    net_prem = result.net_premium
    m1.metric("Net Premium",
              f"₹{abs(net_prem):,.2f}",
              "Credit" if net_prem > 0 else "Debit",
              delta_color="normal" if net_prem > 0 else "inverse")
    m2.metric("Max Profit",  f"₹{result.max_profit:,.2f}" if result.max_profit is not None else "Unlimited")
    m3.metric("Max Loss",    f"₹{result.max_loss:,.2f}"   if result.max_loss   is not None else "Unlimited")

    if result.breakevens:
        be_str = " / ".join(f"₹{b:,.0f}" for b in result.breakevens)
    else:
        be_str = "N/A"
    m4.metric("Breakeven(s)", be_str)

    # Greeks
    st.subheader("Net Greeks")
    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Net Delta", f"{result.net_delta:+.4f}")
    g2.metric("Net Gamma", f"{result.net_gamma:+.4f}")
    g3.metric("Net Theta", f"{result.net_theta:+.4f} /day")
    g4.metric("Net Vega",  f"{result.net_vega:+.4f} /1%IV")

    # Margin estimate — use real SPAN API if client available, else rough proxy
    lot_size = INDICES[symbol].lot_size
    _margin_label = "Rough Proxy"
    if client and is_live_trading_enabled():
        try:
            _span_legs = [
                {
                    "instrument_key": f"NSE_FO|{symbol}_{expiry_sel}_{int(leg.strike)}_{leg.opt_type}",
                    "quantity": leg.quantity,
                    "transaction_type": leg.action,
                    "price": leg.premium,
                    "lot_size": lot_size,
                }
                for leg in legs
            ]
            margin_est = get_span_margin(_span_legs, getattr(client, "_token", ""))
            _margin_label = "SPAN (via Upstox)"
        except Exception:
            margin_est = sum(
                leg.premium * leg.quantity * lot_size * 3
                for leg in legs if leg.action == "SELL"
            )
    else:
        margin_est = sum(
            leg.premium * leg.quantity * lot_size * 3
            for leg in legs if leg.action == "SELL"
        )
    if margin_est > 0:
        st.info(f"Estimated margin ({_margin_label}): ₹{margin_est:,.0f}. "
                "Actual margin requirements may differ. Verify with your broker.")

    # Payoff diagram
    if HAS_PLOTLY and result.payoff_x and result.payoff_y:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=result.payoff_x,
            y=result.payoff_y,
            mode="lines",
            name="P&L at expiry",
            line=dict(color="#42A5F5", width=2),
            fill="tozeroy",
            fillcolor="rgba(66,165,245,0.10)",
        ))
        # Zero line
        fig.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
        # Current spot
        if spot:
            fig.add_vline(x=spot, line_dash="dot", line_color="yellow",
                          annotation_text=f"Spot {spot:,.0f}", annotation_position="top right")
        # Breakevens
        for be in result.breakevens:
            fig.add_vline(x=be, line_dash="dash", line_color="orange",
                          annotation_text=f"BE {be:,.0f}", annotation_position="top left")
        fig.update_layout(
            title="Payoff at Expiry",
            xaxis_title="Underlying Price (₹)",
            yaxis_title="P&L (₹)",
            template="plotly_dark",
            height=400,
            margin=dict(l=40, r=40, t=40, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)
    elif not HAS_PLOTLY:
        df_payoff = pd.DataFrame({"Underlying": result.payoff_x, "P&L (₹)": result.payoff_y})
        st.dataframe(df_payoff)

    # Add to portfolio
    st.subheader("Add to Portfolio")
    if st.button("Add all legs to Portfolio"):
        for leg in legs:
            add_position(
                symbol=symbol,
                expiry=expiry_sel,
                strike=leg.strike,
                opt_type=leg.opt_type,
                action=leg.action,
                quantity=leg.quantity,
                entry_price=leg.premium,
                source="MANUAL",
                strategy_tag="Strategy Builder",
            )
        st.success(f"Added {len(legs)} leg(s) to portfolio.")

    # Execute via broker
    st.subheader("Execute via Broker")
    _live = is_live_trading_enabled()
    _trade_mode = "🔴 LIVE ORDER" if _live else "📋 Paper Trade"
    st.caption(f"Trade mode: **{_trade_mode}**")
    if _live:
        st.warning("Live trading enabled — this will place real orders with real money!")
    if st.button(
        f"Execute Strategy ({_trade_mode})", type="primary", key="sb_exec_btn"
    ):
        st.session_state["sb_exec_confirm"] = True

    if st.session_state.get("sb_exec_confirm"):
        st.warning(f"⚠️ Execute **{n_legs}** leg(s) in **{_trade_mode}** mode?")
        _sb1, _sb2 = st.columns(2)
        if _sb1.button("✅ Confirm Execution", key="sb_exec_yes"):
            _mgr = None
            if _live and client:
                _mgr = OrderManager(client._token)
            _sb_ok, _sb_fails, _sb_mode = 0, [], "PAPER"
            for _leg in legs:
                try:
                    _ikey = (
                        f"NSE_FO|{symbol}_{expiry_sel}"
                        f"_{int(_leg.strike)}_{_leg.opt_type}"
                    )
                    _sb_mode, _pos = execute_paper_or_live(
                        manager=_mgr,
                        instrument_key=_ikey,
                        symbol=symbol,
                        expiry=expiry_sel,
                        strike=_leg.strike,
                        opt_type=_leg.opt_type,
                        action=_leg.action,
                        quantity=_leg.quantity,
                        ltp=_leg.premium,
                        strategy_tag="Strategy Builder",
                        source="MANUAL",
                    )
                    if _pos:
                        _sb_ok += 1
                except Exception as _e:
                    _sb_fails.append(str(_e))
            if _sb_ok:
                st.success(
                    f"✅ {_sb_ok} leg(s) executed in **{_sb_mode}** mode. "
                    "View in Portfolio or Orders page ▶"
                )
                st.session_state.pop("portfolio_ltp_map", None)
            for _fm in _sb_fails:
                st.error(f"❌ {_fm}")
            st.session_state["sb_exec_confirm"] = False
        if _sb2.button("❌ Cancel", key="sb_exec_no"):
            st.session_state["sb_exec_confirm"] = False
            st.rerun()

st.divider()
st.caption(
    "Payoff computed at expiry using intrinsic value only (no time value). "
    "Greeks are estimated using Black-Scholes with current IV. "
    "Margin estimate is a rough proxy — actual SPAN margin varies."
)
