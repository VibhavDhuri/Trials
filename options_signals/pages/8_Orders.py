"""
Orders — Executed order history and active positions by source/strategy.
"""
from __future__ import annotations

import os
import sys

import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from positions.tracker import get_all_positions, close_position, realised_pnl, gross_pnl
from broker.order_manager import is_live_trading_enabled
from utils.helpers import now_ist

st.set_page_config(page_title="Orders", page_icon="📋", layout="wide")

with st.sidebar:
    st.title("📋 Orders")
    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")
    st.divider()

    _mode_live = is_live_trading_enabled()
    if _mode_live:
        st.error("🔴 LIVE TRADING ENABLED")
    else:
        st.info("📋 Paper Trading Mode")

    st.subheader("Filters")
    src_filter = st.multiselect(
        "Source", ["SIGNAL", "MANUAL", "BOT"], default=["SIGNAL", "MANUAL", "BOT"]
    )
    status_filter = st.multiselect(
        "Status", ["OPEN", "CLOSED"], default=["OPEN", "CLOSED"]
    )

st.title("📋 Order Book")

all_positions = get_all_positions()

if not all_positions:
    st.info("No orders yet. Execute signals or add positions from the Portfolio page.")
    st.stop()

# Apply filters
filtered = [
    p for p in all_positions
    if p.source in src_filter and p.status in status_filter
]

if not filtered:
    st.info("No orders match the selected filters.")
    st.stop()

# ── Summary metrics ───────────────────────────────────────────────────────────
open_pos  = [p for p in all_positions if p.status == "OPEN"]
closed_pos = [p for p in all_positions if p.status == "CLOSED"]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Orders", len(all_positions))
m2.metric("Open",   len(open_pos))
m3.metric("Closed", len(closed_pos))

total_realised = sum(realised_pnl(p) for p in closed_pos)
m4.metric(
    "Total Realised P&L",
    f"₹{total_realised:+,.0f}",
    delta=f"{'▲' if total_realised >= 0 else '▼'} {abs(total_realised):,.0f}",
    delta_color="normal" if total_realised >= 0 else "inverse",
)

st.divider()

# ── By strategy breakdown ─────────────────────────────────────────────────────
tags = sorted({p.strategy_tag for p in all_positions if p.strategy_tag})
if tags:
    st.subheader("P&L by Strategy")
    strat_rows = []
    for tag in tags:
        tag_pos = [p for p in closed_pos if p.strategy_tag == tag]
        pnl_sum = sum(realised_pnl(p) for p in tag_pos)
        wins = sum(1 for p in tag_pos if realised_pnl(p) > 0)
        strat_rows.append({
            "Strategy": tag,
            "Closed Trades": len(tag_pos),
            "Win Rate": f"{wins/len(tag_pos)*100:.0f}%" if tag_pos else "—",
            "Total P&L (₹)": f"{pnl_sum:+,.0f}",
        })
    st.dataframe(pd.DataFrame(strat_rows), use_container_width=True, hide_index=True)
    st.divider()

# ── Order table ───────────────────────────────────────────────────────────────
st.subheader(f"Orders ({len(filtered)} shown)")

rows = []
for p in sorted(filtered, key=lambda x: x.entry_time, reverse=True):
    pnl_disp = (
        f"₹{realised_pnl(p):+,.0f}" if p.status == "CLOSED"
        else "—"
    )
    rows.append({
        "ID": p.id,
        "Entry Time": p.entry_time[:16].replace("T", " "),
        "Symbol": p.symbol,
        "Expiry": p.expiry,
        "Strike": int(p.strike),
        "Type": p.opt_type,
        "Action": p.action,
        "Lots": p.quantity,
        "Entry ₹": f"{p.entry_price:,.2f}",
        "Exit ₹": f"{p.exit_price:,.2f}" if p.exit_price else "—",
        "P&L": pnl_disp,
        "Status": p.status,
        "Source": p.source,
        "Strategy": p.strategy_tag or "—",
    })

df = pd.DataFrame(rows)

def _colour_row(row):
    if row["Status"] == "OPEN":
        return ["background-color: #1a2a1a"] * len(row)
    pnl_str = row.get("P&L", "—")
    if pnl_str and pnl_str != "—":
        pnl_val = float(pnl_str.replace("₹", "").replace(",", "").replace("+", ""))
        if pnl_val > 0:
            return ["background-color: #0d2b0d"] * len(row)
        elif pnl_val < 0:
            return ["background-color: #2b0d0d"] * len(row)
    return [""] * len(row)

st.dataframe(df.style.apply(_colour_row, axis=1), use_container_width=True, hide_index=True)

st.divider()

# ── Close open positions ───────────────────────────────────────────────────────
open_filtered = [p for p in filtered if p.status == "OPEN"]
if open_filtered:
    st.subheader("Close Open Orders")
    for p in open_filtered:
        with st.expander(f"{p.action} {p.symbol} {p.opt_type} {int(p.strike)} exp:{p.expiry}  [entry: ₹{p.entry_price:,.2f}]"):
            col_a, col_b, col_c = st.columns([2, 2, 1])
            exit_px = col_a.number_input(
                "Exit price ₹", 0.01, 99999.0, float(p.entry_price), step=0.5,
                key=f"ord_ep_{p.id}"
            )
            est_pnl = (exit_px - p.entry_price) * p.quantity
            from config import INDICES as _IDX
            _lot = _IDX[p.symbol].lot_size if p.symbol in _IDX else 1
            sign = 1 if p.action == "BUY" else -1
            est_pnl_inr = (exit_px - p.entry_price) * p.quantity * _lot * sign
            col_b.metric("Est. P&L", f"₹{est_pnl_inr:+,.0f}")
            if col_c.button("Close", key=f"ord_cls_{p.id}", type="primary"):
                close_position(p.id, exit_px)
                st.success(f"Closed position {p.id}.")
                st.rerun()

st.divider()

# ── GTT Exit Orders ───────────────────────────────────────────────────────────
try:
    from broker.gtt_manager import GTTManager
    _HAS_GTT = True
except ImportError:
    _HAS_GTT = False

if _HAS_GTT and open_filtered:
    with st.expander("⚡ Set GTT Exit Orders (Good Till Triggered)"):
        st.caption("Place target + stop-loss orders that persist until triggered. Paper mode stores GTTs locally.")
        _token = getattr(client, "_token", "") if client else ""
        _gtt_mgr = GTTManager(_token) if _token else GTTManager("")
        for p in open_filtered:
            st.markdown(f"**{p.symbol} {p.opt_type} {int(p.strike)} exp:{p.expiry}** — Entry ₹{p.entry_price:.2f}")
            _g1, _g2, _g3 = st.columns(3)
            _tgt_px  = _g1.number_input("Target ₹", 0.01, 99999.0, float(p.entry_price * 1.5), step=0.5, key=f"gtt_tgt_{p.id}")
            _sl_px   = _g2.number_input("Stop ₹",   0.01, 99999.0, float(p.entry_price * 0.5), step=0.5, key=f"gtt_sl_{p.id}")
            _exit_tx = "SELL" if p.action == "BUY" else "BUY"
            if _g3.button("Place GTT", key=f"gtt_place_{p.id}", type="primary"):
                try:
                    from config import INDICES as _IDX
                    _ikey = f"NSE_FO|{p.symbol}_{p.expiry}_{int(p.strike)}_{p.opt_type}"
                    _lot  = _IDX[p.symbol].lot_size if p.symbol in _IDX else 75
                    _gtt_order = _gtt_mgr.place_gtt(
                        instrument_key=_ikey,
                        trigger_price=_tgt_px,
                        limit_price=_tgt_px,
                        qty=p.quantity * _lot,
                        transaction_type=_exit_tx,
                        position_id=p.id,
                    )
                    st.success(f"GTT placed — target ₹{_tgt_px:.2f}  |  ID: {_gtt_order.id[:8]}")
                except Exception as _ge:
                    st.error(f"GTT failed: {_ge}")
            _existing = _gtt_mgr.list_gtts(position_id=p.id)
            if _existing:
                for _g in _existing:
                    st.caption(f"  → GTT {_g.id[:8]}: {_g.status} @ ₹{_g.trigger_price:.2f}")

st.divider()

# ── Tax P&L Report ────────────────────────────────────────────────────────────
with st.expander("🧾 Tax P&L Report"):
    st.caption("Simplified P&L statement for ITR-3 filing. F&O income = business income under Section 43(5).")
    try:
        from reports.tax_report import generate_tax_report, to_csv
        _fy = st.selectbox("Financial Year", ["2025-26", "2024-25"], key="tax_fy")
        if st.button("Generate Report", key="gen_tax"):
            _all_pos = get_all_positions()
            _df_tax, _summary = generate_tax_report(_all_pos, _fy)
            if _df_tax.empty:
                st.info(f"No closed trades in FY {_fy}.")
            else:
                _t1, _t2, _t3, _t4 = st.columns(4)
                _t1.metric("Turnover", f"₹{_summary['turnover']:,.0f}")
                _t2.metric("Gross P&L", f"₹{_summary['gross_pnl']:+,.0f}")
                _t3.metric("STT Est.", f"₹{_summary['stt_total']:,.0f}")
                _t4.metric("Net P&L", f"₹{_summary['net_pnl']:+,.0f}")
                st.dataframe(_df_tax, use_container_width=True, hide_index=True)
                st.download_button(
                    "⬇ Download CSV", to_csv(_df_tax),
                    file_name=f"FO_PnL_{_fy}.csv", mime="text/csv",
                )
                st.caption("⚠️ STT estimate applies 0.125% to settlement value — actual STT depends on exercise vs squaring off. Consult your CA.")
    except ImportError:
        st.caption("Tax report module not yet installed.")

st.caption("⚠️  P&L is gross — excludes brokerage, STT (0.125% on exercise), and exchange charges.")
