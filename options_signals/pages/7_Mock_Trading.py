"""
Mock Trading — Paper trading platform.

MANUAL mode: user places paper trades through this UI.
AUTO mode:   autonomous bot runs as a separate process (`python mock_trading/run_bot.py`).

The bot writes to data_store/paper_trades.json and data_store/bot_status.json.
This page reads those files and displays live state.
"""
from __future__ import annotations

import os
import sys
import datetime
import subprocess

import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import INDICES, IST
from mock_trading.paper_engine import (
    place_bot_trade, check_and_exit_positions,
    get_trade_log, paper_pnl_summary,
)
from positions.tracker import get_open_positions, close_position, add_position, gross_pnl
from store.local_store import load
from utils.helpers import now_ist

st.set_page_config(page_title="Mock Trading", page_icon="🤖", layout="wide")

with st.sidebar:
    st.title("🤖 Mock Trading")
    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")
    st.info(
        "Paper trading platform — no real money involved. "
        "MANUAL: you place trades. AUTO: bot places trades on high-confidence signals."
    )

# ── Header ────────────────────────────────────────────────────────────────────
st.title("🤖 Mock Trading Platform")
st.markdown(
    "Test trading strategies with **zero risk**. "
    "Track manual trades and watch the autonomous bot execute high-confidence signals in real time."
)

tab_manual, tab_bot, tab_pnl = st.tabs(["📝 Manual Trades", "🤖 Bot Control", "📊 P&L Dashboard"])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — MANUAL TRADES
# ═══════════════════════════════════════════════════════════════════════════════
with tab_manual:
    st.subheader("Place a Manual Paper Trade")

    with st.form("manual_trade_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        sym      = c1.selectbox("Index / Stock", list(INDICES.keys()), key="mt_sym")
        opt_type = c2.radio("Option Type", ["CE", "PE"], horizontal=True, key="mt_ot")
        action   = c3.radio("Action", ["BUY", "SELL"], horizontal=True, key="mt_act")

        c4, c5, c6 = st.columns(3)
        expiry_str  = c4.text_input("Expiry (YYYY-MM-DD)",
                                     value=str(datetime.date.today()), key="mt_exp")
        strike      = c5.number_input("Strike", min_value=1.0, value=22500.0,
                                       step=50.0, key="mt_str")
        quantity    = c6.number_input("Qty (lots)", min_value=1, max_value=100,
                                       value=1, key="mt_qty")

        entry_price = st.number_input("Entry Price (₹)", min_value=0.01,
                                       value=100.0, step=0.5, key="mt_ep")
        strategy_tag = st.text_input("Strategy / Note", value="Manual test", key="mt_tag")

        if st.form_submit_button("Place Paper Trade", type="primary"):
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
                st.success(f"✅ Paper trade placed — ID: {pos.id[:8]}")
                st.rerun()
            except ValueError:
                st.error("Invalid expiry date format. Use YYYY-MM-DD.")

    # ── Open manual positions ─────────────────────────────────────────────────
    st.subheader("Open Manual Positions")
    manual_positions = [p for p in get_open_positions() if p.source == "MANUAL"]

    if not manual_positions:
        st.info("No open manual paper positions.")
    else:
        rows = []
        for p in manual_positions:
            pnl = gross_pnl(p, p.entry_price)
            rows.append({
                "ID":       p.id[:8],
                "Symbol":   p.symbol,
                "Expiry":   p.expiry,
                "Strike":   int(p.strike),
                "Type":     p.opt_type,
                "Action":   p.action,
                "Qty":      p.quantity,
                "Entry ₹":  f"{p.entry_price:.2f}",
                "P&L ₹":    f"{pnl:+.2f}",
                "Tag":      p.strategy_tag,
            })
        df_m = pd.DataFrame(rows)
        st.dataframe(df_m, use_container_width=True)

        # Close position
        pos_labels = {
            f"{p.symbol} {p.opt_type} {int(p.strike)} [{p.id[:8]}]": p.id
            for p in manual_positions
        }
        sel = st.selectbox("Select to close", list(pos_labels.keys()), key="mt_close_sel")
        exit_px = st.number_input("Exit price (₹)", min_value=0.01, value=1.0, step=0.5, key="mt_exit_px")
        if st.button("Close Selected Position", key="mt_close_btn"):
            closed = close_position(pos_labels[sel], exit_px)
            if closed:
                st.success("Position closed.")
                st.rerun()
            else:
                st.error("Could not close position.")

    # ── Manual trade history ──────────────────────────────────────────────────
    st.subheader("Manual Trade History")
    trade_log = [t for t in get_trade_log() if t.get("source") == "MANUAL"]
    if trade_log:
        st.dataframe(pd.DataFrame(trade_log), use_container_width=True)
    else:
        st.caption("No manual trade history yet.")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — BOT CONTROL
# ═══════════════════════════════════════════════════════════════════════════════
with tab_bot:
    st.subheader("Autonomous Trading Bot")

    # Bot status
    bot_status = load("bot_status", {})
    is_running = bot_status.get("running", False)
    last_run   = bot_status.get("last_run", "Never")
    bot_symbol = bot_status.get("symbol", "—")
    bot_spot   = bot_status.get("spot", 0)

    status_color = "🟢" if is_running else "🔴"
    st.markdown(f"### Bot Status: {status_color} {'RUNNING' if is_running else 'STOPPED'}")

    bc1, bc2, bc3 = st.columns(3)
    bc1.metric("Last Run",     last_run if last_run != "Never" else "—")
    bc2.metric("Watching",     bot_symbol)
    bc3.metric("Last Spot",    f"₹{bot_spot:,.0f}" if bot_spot else "—")

    st.divider()

    # How to start/stop
    st.subheader("Start / Stop the Bot")
    st.markdown(
        "The bot runs as a **separate terminal process** to avoid Streamlit threading limitations. "
        "Open a terminal in the `options_signals/` directory and run:"
    )
    st.code(
        "# Start the bot (Nifty, offline mode for testing)\n"
        "python mock_trading/run_bot.py --index NIFTY --offline --interval 60\n\n"
        "# Start the bot (live mode, 5-minute interval)\n"
        "python mock_trading/run_bot.py --index BANKNIFTY --interval 300\n\n"
        "# Stop the bot\n"
        "Press Ctrl+C in the bot's terminal window",
        language="bash"
    )
    st.info(
        "**Bot behaviour:**\n"
        "- Scans every `interval` seconds during market hours\n"
        "- Fetches options chain for nearest 2 expiries\n"
        "- Places paper trades only on **HIGH-confidence** signals\n"
        "- Exits positions on 50% stop-loss or 1 day before expiry\n"
        "- Max 1 open bot position per expiry per direction\n"
        "- All activity logged to `data_store/paper_trades.json`"
    )

    # Bot open positions
    st.subheader("Bot's Open Positions")
    bot_positions = [p for p in get_open_positions() if p.source == "BOT"]

    if not bot_positions:
        st.info("Bot has no open positions currently.")
    else:
        bot_rows = []
        for p in bot_positions:
            pnl = gross_pnl(p, p.entry_price)
            bot_rows.append({
                "Symbol":   p.symbol,
                "Expiry":   p.expiry,
                "Strike":   int(p.strike),
                "Type":     p.opt_type,
                "Entry ₹":  f"{p.entry_price:.2f}",
                "P&L ₹":    f"{pnl:+.2f}",
                "Strategy": p.strategy_tag,
                "Entry":    p.entry_time[:16] if p.entry_time else "—",
            })
        st.dataframe(pd.DataFrame(bot_rows), use_container_width=True)

    # Bot trade activity log
    st.subheader("Bot Trade Activity Log")
    bot_log = [t for t in get_trade_log() if t.get("source") == "BOT"]
    if bot_log:
        df_bot = pd.DataFrame(bot_log[-50:])   # last 50 events
        if "event" in df_bot.columns:
            df_bot = df_bot.sort_values("timestamp", ascending=False)
        st.dataframe(df_bot, use_container_width=True)
    else:
        st.caption("No bot trades recorded yet. Start the bot to see activity here.")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — P&L DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
with tab_pnl:
    st.subheader("Paper Trading P&L Dashboard")

    summary = paper_pnl_summary()
    all_log = get_trade_log()

    if summary["total"] == 0:
        st.info("No closed trades yet. Place or let the bot execute some trades first.")
    else:
        # Overall metrics
        st.markdown("#### Overall (Closed Trades)")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Trades",  summary["total"])
        m2.metric("Win Rate",      f"{summary['win_rate']:.1f}%",
                  f"{summary['wins']}W / {summary['losses']}L")
        m3.metric("Total P&L",     f"₹{summary['total_pnl']:+,.2f}",
                  delta_color="normal" if summary["total_pnl"] >= 0 else "inverse")
        m4.metric("Avg P&L / trade", f"₹{summary['avg_pnl']:+,.2f}")

        m5, m6 = st.columns(2)
        m5.metric("Best Trade",  f"₹{summary['best']:+,.2f}")
        m6.metric("Worst Trade", f"₹{summary['worst']:+,.2f}")

        # Manual vs Bot split
        exit_trades = [t for t in all_log if t.get("event") == "EXIT"]
        manual_exits = [t for t in exit_trades if t.get("source") == "MANUAL"]
        bot_exits    = [t for t in exit_trades if t.get("source") == "BOT"]

        if manual_exits or bot_exits:
            st.markdown("#### Manual vs Bot Comparison")
            comp_rows = []
            for label, trades in [("Manual", manual_exits), ("Bot", bot_exits)]:
                if trades:
                    pnls = [t.get("pnl_gross", 0) for t in trades]
                    wins = sum(1 for p in pnls if p > 0)
                    comp_rows.append({
                        "Source":    label,
                        "Trades":    len(pnls),
                        "Wins":      wins,
                        "Win Rate %": f"{wins/len(pnls)*100:.1f}",
                        "Total P&L ₹": f"{sum(pnls):+,.2f}",
                        "Avg P&L ₹":   f"{sum(pnls)/len(pnls):+,.2f}",
                        "Best ₹":      f"{max(pnls):+,.2f}",
                        "Worst ₹":     f"{min(pnls):+,.2f}",
                    })
            if comp_rows:
                st.dataframe(pd.DataFrame(comp_rows), use_container_width=True)

        # Strategy breakdown
        strategy_trades: dict[str, list[float]] = {}
        for t in exit_trades:
            tag = t.get("strategy_tag") or "Unknown"
            strategy_trades.setdefault(tag, []).append(t.get("pnl_gross", 0))

        if len(strategy_trades) > 1:
            st.markdown("#### Strategy Performance")
            strat_rows = []
            for tag, pnls in sorted(strategy_trades.items(),
                                    key=lambda x: sum(x[1]), reverse=True):
                wins = sum(1 for p in pnls if p > 0)
                strat_rows.append({
                    "Strategy":    tag,
                    "Trades":      len(pnls),
                    "Win Rate %":  f"{wins/len(pnls)*100:.1f}" if pnls else "—",
                    "Total P&L ₹": f"{sum(pnls):+,.2f}",
                    "Avg P&L ₹":   f"{sum(pnls)/len(pnls):+,.2f}" if pnls else "—",
                })
            st.dataframe(pd.DataFrame(strat_rows), use_container_width=True)

        # Equity curve
        if len(exit_trades) >= 2:
            try:
                import plotly.graph_objects as go
                pnls_seq = [t.get("pnl_gross", 0) for t in exit_trades]
                cum_pnl  = [sum(pnls_seq[:i+1]) for i in range(len(pnls_seq))]
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    y=cum_pnl,
                    mode="lines+markers",
                    name="Cumulative P&L",
                    line=dict(color="#42A5F5", width=2),
                    fill="tozeroy",
                    fillcolor="rgba(66,165,245,0.10)",
                ))
                fig.add_hline(y=0, line_dash="dash", line_color="gray")
                fig.update_layout(
                    title="Cumulative Paper P&L",
                    xaxis_title="Trade #",
                    yaxis_title="Cumulative P&L (₹)",
                    template="plotly_dark",
                    height=350,
                )
                st.plotly_chart(fig, use_container_width=True)
            except ImportError:
                pass

        # Full trade log
        st.markdown("#### Full Trade Log")
        if exit_trades:
            df_log = pd.DataFrame(exit_trades)
            disp_cols = [c for c in
                ["timestamp", "source", "symbol", "expiry", "strike", "opt_type",
                 "action", "entry_price", "exit_price", "pnl_gross", "strategy_tag"]
                if c in df_log.columns]
            st.dataframe(df_log[disp_cols].sort_values("timestamp", ascending=False),
                         use_container_width=True)

    st.divider()
    st.caption(
        "⚠️ Paper trading only — no real money or real orders. "
        "P&L excludes STT, brokerage, and exchange charges. "
        "Bot positions use 50% stop-loss and 1-day-before-expiry exit rules."
    )
