"""
Options Calculator — standalone pricer, probability calculator, and break-even analyzer.
No live API required — works fully offline.
"""
from __future__ import annotations

import os
import sys

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import INDICES, IST, RISK_FREE_RATE
from analysis.greeks import bs_price, compute_greeks, expected_move
from analysis.probability import prob_itm, prob_of_profit, expected_value, breakeven_table
from utils.helpers import now_ist

st.set_page_config(page_title="Options Calculator", page_icon="🧮", layout="wide")

client  = st.session_state.get("client")
offline = st.session_state.get("offline", True)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🧮 Options Calculator")
    st.info("Works fully offline — no API required.")
    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
st.title("🧮 Options Calculator")

STRATEGY_LIST = [
    "Long Call",
    "Long Put",
    "Bull Call Spread",
    "Bear Put Spread",
    "Long Straddle",
    "Short Straddle",
    "Iron Condor",
]

tab_pricer, tab_pop, tab_be = st.tabs(
    ["📊 Options Pricer", "🎯 Strategy PoP", "📋 Break-even Table"]
)

# ===========================================================================
# TAB 1 — Options Pricer
# ===========================================================================
with tab_pricer:
    st.subheader("Black-Scholes Options Pricer")

    inp_col1, inp_col2 = st.columns(2)
    with inp_col1:
        p_spot   = st.number_input("Spot Price", min_value=10_000, max_value=100_000,
                                   value=22_500, step=50, key="p_spot")
        p_strike = st.number_input("Strike Price", min_value=10_000, max_value=100_000,
                                   value=22_500, step=50, key="p_strike")
        p_iv     = st.number_input("Implied Volatility (%)", min_value=1.0, max_value=200.0,
                                   value=15.0, step=0.5, key="p_iv")
    with inp_col2:
        p_dte    = st.number_input("Days to Expiry", min_value=0, max_value=365,
                                   value=30, step=1, key="p_dte")
        p_r      = st.number_input("Risk-Free Rate (%)", min_value=1.0, max_value=15.0,
                                   value=6.5, step=0.1, key="p_r")
        p_type   = st.selectbox("Option Type", ["CE", "PE"], key="p_type")

    T_years = max(p_dte / 365.0, 1e-6)
    r_frac  = p_r / 100.0
    iv_frac = p_iv / 100.0

    greeks = compute_greeks(
        S=float(p_spot),
        K=float(p_strike),
        T=T_years,
        r=r_frac,
        sigma=iv_frac,
        opt=p_type,
    )

    itm_prob   = prob_itm(float(p_spot), float(p_strike), r_frac, iv_frac, T_years, p_type)
    exp_mv     = expected_move(float(p_spot), iv_frac, T_years)
    lower_1sd  = float(p_spot) - exp_mv
    upper_1sd  = float(p_spot) + exp_mv

    st.divider()
    st.subheader("Results")

    row1_c1, row1_c2, row1_c3, row1_c4 = st.columns(4)
    row1_c1.metric("Premium ₹", f"{greeks.theoretical_price:.2f}")
    row1_c2.metric("Delta", f"{greeks.delta:.4f}")
    row1_c3.metric("Gamma", f"{greeks.gamma:.6f}")
    row1_c4.metric("Theta / day", f"{greeks.theta:.4f}")

    row2_c1, row2_c2, row2_c3, row2_c4 = st.columns(4)
    row2_c1.metric("Vega / 1% IV", f"{greeks.vega:.4f}")
    row2_c2.metric("Rho", f"{greeks.rho:.4f}")
    row2_c3.metric("ITM Prob %", f"{itm_prob * 100:.1f}%")
    row2_c4.metric(
        "1-SD Range",
        f"{lower_1sd:,.0f} – {upper_1sd:,.0f}",
        help="Spot ± expected move (1σ over DTE)",
    )

    st.caption(
        "All values are theoretical (Black-Scholes). "
        "Actual market prices may differ."
    )

# ===========================================================================
# TAB 2 — Strategy PoP
# ===========================================================================
with tab_pop:
    st.subheader("Strategy Probability of Profit")

    pc1, pc2 = st.columns(2)
    with pc1:
        pop_spot    = st.number_input("Spot Price", min_value=10_000, max_value=100_000,
                                      value=22_500, step=50, key="pop_spot")
        pop_atm     = st.number_input("ATM Strike", min_value=10_000, max_value=100_000,
                                      value=22_500, step=50, key="pop_atm")
        pop_otm     = st.number_input("OTM Strike (for spreads / IC)",
                                      min_value=10_000, max_value=100_000,
                                      value=23_000, step=50, key="pop_otm")
    with pc2:
        pop_iv      = st.number_input("IV (%)", min_value=1.0, max_value=200.0,
                                      value=15.0, step=0.5, key="pop_iv")
        pop_dte     = st.number_input("Days to Expiry", min_value=1, max_value=365,
                                      value=30, step=1, key="pop_dte")
        pop_lot     = st.number_input("Lot Size", min_value=1, max_value=10_000,
                                      value=75, step=1, key="pop_lot")

    pop_strategy = st.selectbox("Strategy", STRATEGY_LIST, key="pop_strategy")

    calc_btn = st.button("Calculate", type="primary", key="pop_calc_btn")

    if calc_btn:
        S    = float(pop_spot)
        K    = float(pop_atm)
        K2   = float(pop_otm)
        iv_f = pop_iv / 100.0
        r_f  = RISK_FREE_RATE
        T    = pop_dte / 365.0
        ls   = int(pop_lot)

        # Helper to price a leg
        def _p(strike: float, opt: str) -> float:
            return bs_price(S, strike, max(T, 1e-6), r_f, iv_f, opt)

        # --- Build Leg objects (simple dataclass compatible with prob functions) ---
        # The probability functions only need: opt_type, strike, action, quantity, premium
        from dataclasses import dataclass

        @dataclass
        class _Leg:
            opt_type: str
            strike: float
            action: str
            quantity: int
            premium: float

        strategy = pop_strategy
        legs: list[_Leg] = []

        if strategy == "Long Call":
            legs = [_Leg("CE", K, "BUY", 1, _p(K, "CE"))]

        elif strategy == "Long Put":
            legs = [_Leg("PE", K, "BUY", 1, _p(K, "PE"))]

        elif strategy == "Bull Call Spread":
            legs = [
                _Leg("CE", K,  "BUY",  1, _p(K,  "CE")),
                _Leg("CE", K2, "SELL", 1, _p(K2, "CE")),
            ]

        elif strategy == "Bear Put Spread":
            # ATM put buy, OTM (lower strike) put sell
            otm_put = min(K, K2)  # lower strike = OTM put
            atm_put = max(K, K2)
            legs = [
                _Leg("PE", atm_put, "BUY",  1, _p(atm_put, "PE")),
                _Leg("PE", otm_put, "SELL", 1, _p(otm_put, "PE")),
            ]

        elif strategy == "Long Straddle":
            legs = [
                _Leg("CE", K, "BUY", 1, _p(K, "CE")),
                _Leg("PE", K, "BUY", 1, _p(K, "PE")),
            ]

        elif strategy == "Short Straddle":
            legs = [
                _Leg("CE", K, "SELL", 1, _p(K, "CE")),
                _Leg("PE", K, "SELL", 1, _p(K, "PE")),
            ]

        elif strategy == "Iron Condor":
            # Short strikes at ATM ± 5%, long wings at ATM ± 10%
            short_call = K * 1.05
            long_call  = K * 1.10
            short_put  = K * 0.95
            long_put   = K * 0.90
            legs = [
                _Leg("PE", long_put,   "BUY",  1, _p(long_put,   "PE")),
                _Leg("PE", short_put,  "SELL", 1, _p(short_put,  "PE")),
                _Leg("CE", short_call, "SELL", 1, _p(short_call, "CE")),
                _Leg("CE", long_call,  "BUY",  1, _p(long_call,  "CE")),
            ]

        # Compute max profit/loss from payoff extremes
        import numpy as np
        spots_arr = np.linspace(S * 0.8, S * 1.2, 500)
        payoff_arr = np.zeros(len(spots_arr))
        net_prem_total = 0.0
        for leg in legs:
            sign = 1 if leg.action == "BUY" else -1
            if leg.opt_type == "CE":
                intrinsic = np.maximum(spots_arr - leg.strike, 0.0)
            else:
                intrinsic = np.maximum(leg.strike - spots_arr, 0.0)
            payoff_arr    += sign * (intrinsic - leg.premium) * leg.quantity * ls
            net_prem_total += (-1 if leg.action == "BUY" else 1) * leg.premium * leg.quantity * ls

        max_profit_val = float(payoff_arr.max())
        max_loss_val   = float(payoff_arr.min())

        with st.spinner("Running Monte Carlo (50,000 paths)…"):
            pop_pct = prob_of_profit(legs, S, iv_f, float(pop_dte), ls)  # type: ignore[arg-type]
            ev_inr  = expected_value(legs, S, iv_f, float(pop_dte), ls)  # type: ignore[arg-type]

        res_c1, res_c2, res_c3, res_c4 = st.columns(4)
        res_c1.metric("Probability of Profit", f"{pop_pct * 100:.1f}%")
        res_c2.metric("Expected Value ₹", f"{ev_inr:+,.2f}")
        res_c3.metric(
            "Max Profit ₹",
            f"{'Unlimited' if max_profit_val > 1e8 else f'{max_profit_val:+,.2f}'}",
        )
        res_c4.metric(
            "Max Loss ₹",
            f"{'Unlimited' if max_loss_val < -1e8 else f'{max_loss_val:+,.2f}'}",
        )

        st.caption(
            "Monte Carlo with 50,000 paths — result varies slightly each run (~±0.5%)"
        )


# ===========================================================================
# TAB 3 — Break-even Table
# ===========================================================================
with tab_be:
    st.subheader("Break-even & P&L Table")

    be_c1, be_c2 = st.columns(2)
    with be_c1:
        be_spot   = st.number_input("Spot Price", min_value=10_000, max_value=100_000,
                                    value=22_500, step=50, key="be_spot")
        be_strike = st.number_input("ATM Strike", min_value=10_000, max_value=100_000,
                                    value=22_500, step=50, key="be_strike")
        be_otm    = st.number_input("OTM Strike (for spreads / IC)",
                                    min_value=10_000, max_value=100_000,
                                    value=23_000, step=50, key="be_otm")
    with be_c2:
        be_iv     = st.number_input("IV (%)", min_value=1.0, max_value=200.0,
                                    value=15.0, step=0.5, key="be_iv")
        be_dte    = st.number_input("Days to Expiry", min_value=0, max_value=365,
                                    value=30, step=1, key="be_dte")
        be_lot    = st.number_input("Lot Size", min_value=1, max_value=10_000,
                                    value=75, step=1, key="be_lot")

    be_strategy = st.selectbox("Strategy", STRATEGY_LIST, key="be_strategy")

    show_table_btn = st.button("Show Table", type="primary", key="be_show_btn")

    if show_table_btn:
        S_be   = float(be_spot)
        K_be   = float(be_strike)
        K2_be  = float(be_otm)
        iv_be  = be_iv / 100.0
        r_be   = RISK_FREE_RATE
        T_be   = max(be_dte / 365.0, 1e-6)
        ls_be  = int(be_lot)

        def _pb(strike: float, opt: str) -> float:
            return bs_price(S_be, strike, T_be, r_be, iv_be, opt)

        from dataclasses import dataclass as _dc

        @_dc
        class _LegBE:
            opt_type: str
            strike: float
            action: str
            quantity: int
            premium: float

        be_legs: list[_LegBE] = []
        strat = be_strategy

        if strat == "Long Call":
            be_legs = [_LegBE("CE", K_be, "BUY", 1, _pb(K_be, "CE"))]
        elif strat == "Long Put":
            be_legs = [_LegBE("PE", K_be, "BUY", 1, _pb(K_be, "PE"))]
        elif strat == "Bull Call Spread":
            be_legs = [
                _LegBE("CE", K_be,  "BUY",  1, _pb(K_be,  "CE")),
                _LegBE("CE", K2_be, "SELL", 1, _pb(K2_be, "CE")),
            ]
        elif strat == "Bear Put Spread":
            atm_p = max(K_be, K2_be)
            otm_p = min(K_be, K2_be)
            be_legs = [
                _LegBE("PE", atm_p, "BUY",  1, _pb(atm_p, "PE")),
                _LegBE("PE", otm_p, "SELL", 1, _pb(otm_p, "PE")),
            ]
        elif strat == "Long Straddle":
            be_legs = [
                _LegBE("CE", K_be, "BUY", 1, _pb(K_be, "CE")),
                _LegBE("PE", K_be, "BUY", 1, _pb(K_be, "PE")),
            ]
        elif strat == "Short Straddle":
            be_legs = [
                _LegBE("CE", K_be, "SELL", 1, _pb(K_be, "CE")),
                _LegBE("PE", K_be, "SELL", 1, _pb(K_be, "PE")),
            ]
        elif strat == "Iron Condor":
            sc = K_be * 1.05
            lc = K_be * 1.10
            sp = K_be * 0.95
            lp = K_be * 0.90
            be_legs = [
                _LegBE("PE", lp, "BUY",  1, _pb(lp, "PE")),
                _LegBE("PE", sp, "SELL", 1, _pb(sp, "PE")),
                _LegBE("CE", sc, "SELL", 1, _pb(sc, "CE")),
                _LegBE("CE", lc, "BUY",  1, _pb(lc, "CE")),
            ]

        df_be = breakeven_table(be_legs, S_be, n_points=41, lot_size=ls_be)  # type: ignore[arg-type]

        # Style: green rows where P&L > 0, red where P&L < 0
        def _colour_pnl(row: pd.Series) -> list[str]:
            colour = "background-color: #1a3d1a; color: #7fff7f" if row["total_pnl"] > 0 \
                     else "background-color: #3d1a1a; color: #ff7f7f" if row["total_pnl"] < 0 \
                     else ""
            return [colour] * len(row)

        styled_df = df_be.style.apply(_colour_pnl, axis=1).format({
            "underlying_price": "{:,.2f}",
            "total_pnl": "{:+,.2f}",
            "pnl_pct_of_spot": "{:+.4f}%",
        })

        st.dataframe(styled_df, use_container_width=True, hide_index=True)

        # Plotly P&L line chart
        fig_be = go.Figure()
        fig_be.add_trace(go.Scatter(
            x=df_be["underlying_price"],
            y=df_be["total_pnl"],
            mode="lines",
            name="P&L",
            line=dict(color="#4fc3f7", width=2),
            fill="tozeroy",
            fillcolor="rgba(79, 195, 247, 0.1)",
        ))
        fig_be.add_hline(y=0, line_dash="dash", line_color="gray")
        fig_be.add_vline(x=S_be, line_dash="dot", line_color="yellow",
                         annotation_text="Current Spot")
        fig_be.update_layout(
            title=f"{strat} — P&L vs Underlying Price at Expiry",
            xaxis_title="Underlying Price (₹)",
            yaxis_title="P&L (₹)",
            template="plotly_dark",
            height=400,
        )
        st.plotly_chart(fig_be, use_container_width=True)
