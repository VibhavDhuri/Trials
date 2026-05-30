"""
Backtest — Signal replay using real NSE bhav copy data (or HV estimate fallback).
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
from data.nse_bhav import is_available as bhav_available
from utils.helpers import now_ist

st.set_page_config(page_title="Backtest", page_icon="📈", layout="wide")

with st.sidebar:
    st.title("📈 Backtest")
    symbol = st.selectbox("Index", list(INDICES.keys()), key="bt_symbol")
    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")

    # Data source info
    st.divider()
    st.subheader("Data Source")
    with st.spinner("Checking NSE archives…"):
        nse_reachable = bhav_available()

    if nse_reachable:
        st.success("NSE bhav copy reachable — **real historical options prices** will be used for recent dates.")
    else:
        st.warning("NSE archives unreachable — using **HV-based estimate** (indicative only).")

    try:
        import nselib  # noqa: F401
        st.info("nselib installed — available as fallback data source.")
    except ImportError:
        st.caption("Optional: `pip install nselib` for an additional fallback source.")

    try:
        import breeze_connect  # noqa: F401
        st.info("breeze-connect installed — ICICI Direct historical data available.")
    except ImportError:
        st.caption("Optional: `pip install breeze-connect` for ICICI Direct data (up to 3yr, per-strike OHLCV).")

client  = st.session_state.get("client")
offline = st.session_state.get("offline", True)

st.title("📈 Signal Backtest")

if nse_reachable:
    st.info(
        "**Data mode: NSE Bhav Copy (real EOD prices)**  \n"
        "Using actual NSE F&O settlement prices for dates within the cached range. "
        "Dates without cached data fall back to HV-based estimation. "
        "P&L is gross — excludes STT (0.125% on settlement), brokerage, and other charges."
    )
else:
    st.warning(
        "⚠️ **ESTIMATED mode** — NSE bhav copy unavailable.  \n"
        "Option premiums are estimated via Black-Scholes using 20-day HV × 1.25 (VRP adjustment). "
        "Results are biased and should not be used to evaluate real strategies."
    )

# ── Controls ───────────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)
today      = datetime.date.today()
end_date   = col1.date_input("End date",    value=today, key="bt_end")
start_date = col2.date_input("Start date",
                              value=today - datetime.timedelta(days=90), key="bt_start")
strategy   = col3.selectbox(
    "Strategy",
    ["ATM_CE (Long Call)", "ATM_PE (Long Put)", "STRADDLE (Long Straddle)"],
    key="bt_strategy",
)
stop_loss_pct = st.slider("Stop-loss %", 10, 80, 50, step=5,
                           help="Exit when premium falls by this % from entry price")

days_back = (end_date - start_date).days
if days_back > 252:
    st.warning("Date range capped at 252 trading days.")
    days_back = 252

# ── Run ───────────────────────────────────────────────────────────────────────
if st.button("Run Backtest", type="primary"):
    with st.spinner(f"Running backtest on {symbol} ({days_back} days)…"):
        strat_key = strategy.split(" ")[0]   # ATM_CE, ATM_PE, STRADDLE
        trades_df, summary = run_backtest(
            symbol=symbol,
            client=None if offline else client,
            days_back=days_back,
            strategy=strat_key,
            stop_loss_pct=stop_loss_pct / 100,
        )

    if trades_df.empty:
        st.info("No trades generated. Try a longer date range or different strategy.")
    else:
        st.subheader("Summary")
        s = format_summary(summary)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Trades",  s["total_trades"])
        m2.metric("Win Rate",      s["win_rate"])
        m3.metric("Avg P&L / trade", s["avg_pnl"])
        m4.metric("Sharpe (indicative)", s["sharpe"])

        m5, m6, m7 = st.columns(3)
        m5.metric("Total P&L",    s["total_pnl"])
        m6.metric("Max Drawdown", s["max_drawdown"])
        m7.metric("Best / Worst", f"{s['best']} / {s['worst']}")

        try:
            fig = equity_curve_fig(trades_df)
            st.plotly_chart(fig, use_container_width=True)
        except Exception:
            st.line_chart(trades_df.set_index("entry_date")["cum_pnl"])

        st.subheader("Trade Log")
        display_cols = [c for c in
            ["entry_date", "exit_date", "signal", "entry_price",
             "exit_price", "pnl", "exit_reason"]
            if c in trades_df.columns]
        st.dataframe(trades_df[display_cols], use_container_width=True)

st.divider()
st.subheader("About Data Sources")
with st.expander("How to get real historical options data"):
    st.markdown("""
**Source 1: NSE Bhav Copy (auto-downloaded, free)**
- NSE publishes end-of-day F&O settlement data daily
- The backtest downloads and caches it automatically when NSE archives are reachable
- Cached in `data_store/bhav_cache/` as Parquet files (no re-downloading)
- Coverage: pre-8 Jul 2024 uses old URL format; post-8 Jul 2024 uses new UDiFF format

**Source 2: nselib (free, no account needed)**
```bash
pip install nselib
```
Fetches NSE option price/volume data programmatically. Installed as a fallback if bhav copy fails.

**Source 3: Breeze API / ICICI Direct (free, needs ICICI Direct account)**
```bash
pip install breeze-connect
```
Historical per-strike OHLCV + OI for up to 3 years back. Useful for detailed analysis.
Set `BREEZE_API_KEY`, `BREEZE_API_SECRET`, `BREEZE_SESSION_TOKEN` in your `.env`.

**Source 4: jugaad-data (free, uncertain post-Jul 2024 support)**
```bash
pip install jugaad-data
```
Downloads bhav copy via a simpler interface. May need updates for the new UDiFF URL format.

**Source 5: TrueData / Global Datafeeds (paid, ₹500–2000/month)**
Full historical options chain data with Greeks, intraday resolution, long history.
""")
