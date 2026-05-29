"""
Backtest — Replay signals on historical data (indicative only).
"""
from __future__ import annotations

import os
import sys
import datetime

import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import INDICES
from backtest.engine import run_backtest
from backtest.report import equity_curve_fig, format_summary
from utils.helpers import now_ist

st.set_page_config(page_title="Backtest", page_icon="📈", layout="wide")

with st.sidebar:
    st.title("📈 Backtest")
    symbol = st.selectbox("Index", list(INDICES.keys()), key="bt_symbol")
    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")

client  = st.session_state.get("client")
offline = st.session_state.get("offline", True)

st.title("📈 Signal Backtest")
st.warning(
    "⚠️ **INDICATIVE ONLY** — This backtest uses 20-day historical volatility (HV) as an IV proxy. "
    "HV systematically underestimates realized IV by 3-5% due to the volatility risk premium. "
    "Results are biased optimistic for premium-selling strategies. "
    "No actual historical options prices are used — signal replay on underlying moves only."
)

# ── Controls ──────────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)
today     = datetime.date.today()
end_date  = col1.date_input("End date",   value=today,                         key="bt_end")
start_date = col2.date_input("Start date", value=today - datetime.timedelta(days=90), key="bt_start")
strategy  = col3.selectbox(
    "Strategy",
    ["ATM_CE (Long Call)", "ATM_PE (Long Put)", "STRADDLE (Long Straddle)"],
    key="bt_strategy",
)

stop_loss_pct = st.slider("Stop-loss %", 10, 80, 50, step=5,
                           help="Exit when premium falls by this % from entry")

days_back = (end_date - start_date).days
if days_back > 252:
    st.warning("Date range capped at 252 trading days. Adjusting automatically.")
    days_back = 252

# ── Run ───────────────────────────────────────────────────────────────────────
if st.button("Run Backtest", type="primary"):
    with st.spinner(f"Running backtest on {symbol} ({days_back} days)…"):
        strat_key = strategy.split(" ")[0]  # ATM_CE, ATM_PE, STRADDLE
        trades_df, summary = run_backtest(
            symbol=symbol,
            client=None if offline else client,
            days_back=days_back,
            strategy=strat_key,
            stop_loss_pct=stop_loss_pct / 100,
        )

    if trades_df.empty:
        st.info("No trades generated for this period. Try a longer date range or different strategy.")
    else:
        # Summary metrics
        st.subheader("Summary")
        s = format_summary(summary)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Trades",  s["total_trades"])
        m2.metric("Win Rate",      s["win_rate"])
        m3.metric("Avg P&L / trade", s["avg_pnl"])
        m4.metric("Sharpe (indicative)", s["sharpe"])

        m5, m6, m7 = st.columns(3)
        m5.metric("Total P&L",  s["total_pnl"])
        m6.metric("Max Drawdown", s["max_drawdown"])
        m7.metric("Best / Worst", f"{s['best']} / {s['worst']}")

        # Equity curve
        try:
            fig = equity_curve_fig(trades_df)
            st.plotly_chart(fig, use_container_width=True)
        except Exception:
            st.line_chart(trades_df.set_index("entry_date")["cum_pnl"])

        # Trades table
        st.subheader("Trade Log")
        display_cols = [c for c in
            ["entry_date", "exit_date", "signal", "entry_price",
             "exit_price", "pnl", "exit_reason"]
            if c in trades_df.columns]
        st.dataframe(trades_df[display_cols], use_container_width=True)

        st.caption(
            "Entry: next-day open after signal. "
            "Exit: stop-loss (premium -50%) or held to expiry. "
            "All values are indicative and do not account for bid-ask spread, slippage, or taxes."
        )
