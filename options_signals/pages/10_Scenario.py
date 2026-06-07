"""
Scenario Analysis — reprice portfolio under hypothetical market moves.
"""
from __future__ import annotations

import os
import sys
import datetime

import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import INDICES, IST, RISK_FREE_RATE
from analysis.greeks import bs_price
from analysis.scenario import ScenarioEngine, scenario_heatmap_fig
from positions.tracker import get_open_positions, Position
from utils.helpers import now_ist, days_to_expiry, generate_expiry_dates
from data.market_data import MarketDataFetcher
from data.options_chain import OptionsChainFetcher

st.set_page_config(page_title="Scenario Analysis", page_icon="🎯", layout="wide")

client  = st.session_state.get("client")
offline = st.session_state.get("offline", True)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🎯 Scenario Analysis")
    symbol = st.selectbox("Index", list(INDICES.keys()), key="scenario_symbol")
    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("🎯 Scenario Analysis")
st.markdown("**What happens to your portfolio if markets move?**")
st.divider()

# ---------------------------------------------------------------------------
# Controls row
# ---------------------------------------------------------------------------
col_s, col_iv, col_d = st.columns(3)
with col_s:
    spot_change = st.slider(
        "Spot Change (%)",
        min_value=-10.0,
        max_value=10.0,
        step=0.5,
        value=0.0,
        key="scenario_spot_change",
    )
with col_iv:
    iv_change = st.slider(
        "IV Change (pts)",
        min_value=-10,
        max_value=15,
        step=1,
        value=0,
        key="scenario_iv_change",
    )
with col_d:
    days_forward = st.slider(
        "Days Forward",
        min_value=0,
        max_value=30,
        step=1,
        value=0,
        key="scenario_days_forward",
    )

st.divider()

# ---------------------------------------------------------------------------
# Fetch market data / spot price
# ---------------------------------------------------------------------------
mdf = MarketDataFetcher(client=client, offline=offline)
spot_data = mdf.get_spot(symbol)
spot = spot_data.get("last_price", 22500.0)

# ---------------------------------------------------------------------------
# Load open positions; show demo if none
# ---------------------------------------------------------------------------
open_positions = get_open_positions()

using_demo = False
if not open_positions:
    st.info(
        "No open positions. Add trades from Portfolio page.  "
        "Showing **demo** positions for illustration."
    )
    using_demo = True
    cfg = INDICES[symbol]
    atm_strike = round(spot / cfg.strike_gap) * cfg.strike_gap
    demo_expiry = (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    open_positions = [
        Position(
            id="DEMO1",
            symbol=symbol,
            expiry=demo_expiry,
            strike=atm_strike,
            opt_type="CE",
            action="BUY",
            quantity=1,
            entry_price=150.0,
            entry_time=now_ist().isoformat(),
            status="OPEN",
        ),
        Position(
            id="DEMO2",
            symbol=symbol,
            expiry=demo_expiry,
            strike=atm_strike - 5 * cfg.strike_gap,
            opt_type="PE",
            action="BUY",
            quantity=1,
            entry_price=130.0,
            entry_time=now_ist().isoformat(),
            status="OPEN",
        ),
    ]

# ---------------------------------------------------------------------------
# Build chain_lookup (offline: empty → ScenarioEngine defaults 15%; online: fetch)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=60, show_spinner=False)
def _fetch_chain_lookup(sym: str, expiry: str, _offline: bool) -> dict:
    """Return {(sym, expiry, strike, opt_type): {'iv': pct}} mapping."""
    lookup: dict = {}
    if _offline:
        return lookup  # ScenarioEngine falls back to 15%
    try:
        fetcher = OptionsChainFetcher(client=client, offline=False)
        quote = MarketDataFetcher(client=client, offline=False).get_spot(sym)
        sp = quote.get("last_price", 22500.0)
        df = fetcher.get_chain_df(sym, expiry, sp)
        if not df.empty:
            for _, row in df.iterrows():
                key = (sym, expiry, float(row["strike"]), str(row["opt_type"]))
                lookup[key] = {"iv": float(row.get("iv", 0.15)) * 100}
    except Exception:
        pass
    return lookup


expiries_needed = list({p.expiry for p in open_positions if p.symbol == symbol})
chain_lookup: dict = {}
for exp in expiries_needed:
    chain_lookup.update(_fetch_chain_lookup(symbol, exp, offline))

# ---------------------------------------------------------------------------
# Run scenario engine for current slider values
# ---------------------------------------------------------------------------
engine = ScenarioEngine()
results = engine.compute(
    positions=open_positions,
    spot=spot,
    chain_lookup=chain_lookup,
    spot_change_pct=spot_change,
    iv_change_pts=float(iv_change),
    days_forward=days_forward,
)
total_pnl = engine.total_pnl(results)

# ---------------------------------------------------------------------------
# Total P&L metric
# ---------------------------------------------------------------------------
col_m1, col_m2, col_m3 = st.columns([1, 1, 2])
with col_m1:
    st.metric(
        "Total Scenario P&L",
        f"₹{total_pnl:+,.2f}",
        delta=f"{'▲' if total_pnl >= 0 else '▼'} {abs(total_pnl):,.2f}",
        delta_color="normal" if total_pnl >= 0 else "inverse",
    )
with col_m2:
    st.metric("Current Spot", f"₹{spot:,.2f}")
with col_m3:
    st.metric(
        "Scenario Spot",
        f"₹{spot * (1 + spot_change / 100):,.2f}",
        delta=f"{spot_change:+.1f}%",
    )

st.divider()

# ---------------------------------------------------------------------------
# Per-position breakdown table
# ---------------------------------------------------------------------------
st.subheader("Position Breakdown")
if results:
    rows = []
    for r in results:
        rows.append({
            "Symbol": r.symbol,
            "Strike": r.strike,
            "Type": r.opt_type,
            "Entry ₹": f"{r.entry_price:.2f}",
            "Scenario ₹": f"{r.scenario_price:.2f}",
            "P&L ₹": f"{r.pnl_inr:+,.2f}",
        })
    df_breakdown = pd.DataFrame(rows)
    st.dataframe(df_breakdown, use_container_width=True, hide_index=True)
else:
    st.warning("No scenario results to display.")

st.divider()

# ---------------------------------------------------------------------------
# Heatmap — 5×5 grid
# ---------------------------------------------------------------------------
st.subheader("Portfolio P&L Heatmap")

SPOT_CHANGES = [-10.0, -5.0, 0.0, 5.0, 10.0]
IV_CHANGES   = [-5.0,   0.0,  5.0, 10.0, 15.0]

with st.spinner("Computing heatmap…"):
    spot_labels, iv_labels, pnl_matrix = engine.heatmap_data(
        positions=open_positions,
        spot=spot,
        chain_lookup=chain_lookup,
        spot_changes=SPOT_CHANGES,
        iv_changes=IV_CHANGES,
    )

fig_heatmap = scenario_heatmap_fig(SPOT_CHANGES, IV_CHANGES, pnl_matrix)
st.plotly_chart(fig_heatmap, use_container_width=True)
st.caption(
    "Heatmap shows total portfolio P&L at each scenario. "
    "Green = profit, Red = loss."
)

st.divider()
st.caption(
    "⚠️ Scenario uses Black-Scholes repricing — actual results depend on "
    "market microstructure."
)
