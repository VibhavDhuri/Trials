"""
Strategy Scheduler — configure and monitor conditional / time-based strategy execution.
"""
from __future__ import annotations

import os
import sys

import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import INDICES
from utils.helpers import now_ist

st.set_page_config(page_title="Strategy Scheduler", page_icon="🕐", layout="wide")

try:
    from automation.scheduler import (
        ScheduledStrategy, load_schedules, save_schedules,
        check_conditions, is_due, execute_strategy,
    )
    _HAS_SCHED = True
except ImportError as _e:
    _HAS_SCHED = False
    _SCHED_ERR = str(_e)

with st.sidebar:
    st.title("🕐 Strategy Scheduler")
    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")
    st.divider()
    st.info(
        "Schedule strategies to auto-execute when market conditions are met. "
        "Run `python automation/scheduler.py` in the background to activate execution."
    )

st.title("🕐 Strategy Scheduler")

if not _HAS_SCHED:
    st.error(f"Scheduler module unavailable: {_SCHED_ERR}")
    st.stop()

client  = st.session_state.get("client")
offline = st.session_state.get("offline", True)

STRATEGY_TYPES = [
    "SHORT_STRADDLE", "SHORT_STRANGLE", "IRON_CONDOR",
    "BULL_SPREAD", "BEAR_SPREAD", "LONG_STRADDLE",
]
FREQUENCIES = ["daily", "weekly", "once"]
DAYS_OF_WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri"]

# ── Add new schedule ──────────────────────────────────────────────────────────
st.subheader("Add New Scheduled Strategy")
with st.form("add_schedule_form"):
    _a1, _a2, _a3 = st.columns(3)
    _s_name   = _a1.text_input("Name", value="My Schedule", placeholder="e.g. Weekly Iron Condor")
    _s_sym    = _a2.selectbox("Index", list(INDICES.keys()))
    _s_type   = _a3.selectbox("Strategy", STRATEGY_TYPES)

    _b1, _b2, _b3, _b4 = st.columns(4)
    _s_freq   = _b1.selectbox("Frequency", FREQUENCIES)
    _s_time   = _b2.text_input("Time (IST HH:MM)", value="09:25")
    _s_expiry = _b3.text_input("Target Expiry (YYYY-MM-DD)", value="")
    _s_qty    = _b4.number_input("Lots per leg", 1, 20, 1)

    st.markdown("**Conditions** *(leave 0 to skip)*")
    _cc1, _cc2, _cc3, _cc4 = st.columns(4)
    _c_min_vix   = _cc1.number_input("Min VIX",       0.0, 50.0, 0.0, step=0.5)
    _c_max_vix   = _cc2.number_input("Max VIX",       0.0, 50.0, 0.0, step=0.5)
    _c_min_ivr   = _cc3.number_input("Min IV Rank %", 0.0, 100.0, 0.0, step=5.0)
    _c_max_ivr   = _cc4.number_input("Max IV Rank %", 0.0, 100.0, 0.0, step=5.0)
    _cc5, _cc6   = st.columns(2)
    _c_min_pcr   = _cc5.number_input("Min PCR",       0.0, 5.0, 0.0, step=0.05)
    _c_max_pcr   = _cc6.number_input("Max PCR",       0.0, 5.0, 0.0, step=0.05)

    _s_dry = st.checkbox("Dry-run (simulate only — do not add to portfolio)", value=True)
    _s_notes = st.text_area("Notes", height=60)

    if st.form_submit_button("Save Schedule", type="primary"):
        import uuid, datetime as _dt
        conditions: dict = {}
        if _c_min_vix > 0: conditions["min_vix"] = _c_min_vix
        if _c_max_vix > 0: conditions["max_vix"] = _c_max_vix
        if _c_min_ivr > 0: conditions["min_iv_rank"] = _c_min_ivr
        if _c_max_ivr > 0: conditions["max_iv_rank"] = _c_max_ivr
        if _c_min_pcr > 0: conditions["min_pcr"] = _c_min_pcr
        if _c_max_pcr > 0: conditions["max_pcr"] = _c_max_pcr

        new_sched = ScheduledStrategy(
            id=str(uuid.uuid4())[:8],
            name=_s_name,
            symbol=_s_sym,
            strategy_type=_s_type,
            expiry=_s_expiry or None,
            quantity=int(_s_qty),
            conditions=conditions,
            schedule={
                "frequency": _s_freq,
                "time_ist": _s_time,
                "days_of_week": [0,1,2,3,4],
            },
            dry_run=_s_dry,
            notes=_s_notes,
            enabled=True,
        )
        schedules = load_schedules()
        schedules.append(new_sched)
        save_schedules(schedules)
        st.success(f"Schedule '{_s_name}' saved.")
        st.rerun()

st.divider()

# ── Existing schedules ────────────────────────────────────────────────────────
st.subheader("Scheduled Strategies")
schedules = load_schedules()

if not schedules:
    st.info("No strategies scheduled yet. Add one above.")
else:
    # Build live market snapshot for condition checking
    try:
        from data.market_data import MarketDataFetcher
        from data.vix_data import get_vix
        _mdf = MarketDataFetcher(client, offline=offline)
        _vix = get_vix(client if not offline else None)
        _snapshot = {"vix": _vix.current}
    except Exception:
        _snapshot = {}

    for sched in schedules:
        _cond_ok, _cond_reason = check_conditions(sched, _snapshot)
        _due_now = is_due(sched)
        _status_tag = "✅ Conditions met" if _cond_ok else f"⏸ {_cond_reason}"
        _due_tag    = "🔔 DUE NOW" if _due_now else "⏰ Waiting"

        with st.expander(
            f"{'🟢' if sched.enabled else '⚫'} **{sched.name}** — "
            f"{sched.symbol} {sched.strategy_type} | {_due_tag} | {_status_tag}",
            expanded=False,
        ):
            _ei1, _ei2, _ei3, _ei4 = st.columns(4)
            _ei1.caption(f"**Strategy:** {sched.strategy_type}")
            _ei2.caption(f"**Symbol:** {sched.symbol}")
            _ei3.caption(f"**Frequency:** {sched.schedule.get('frequency','daily')}")
            _ei4.caption(f"**Time:** {sched.schedule.get('time_ist','09:25')} IST")

            if sched.conditions:
                _cond_str = " | ".join(f"{k}={v}" for k, v in sched.conditions.items())
                st.caption(f"Conditions: {_cond_str}")
            if sched.notes:
                st.caption(f"Notes: {sched.notes}")
            if sched.last_run:
                st.caption(f"Last executed: {sched.last_run[:16]} IST")

            _mode_tag = "DRY-RUN" if sched.dry_run else "LIVE"
            if sched.dry_run:
                st.info(f"Mode: **{_mode_tag}** — positions will NOT be added to portfolio.")
            else:
                st.warning(f"Mode: **{_mode_tag}** — positions WILL be added to portfolio.")

            _sb1, _sb2, _sb3 = st.columns(3)

            # Manual trigger
            if _sb1.button("▶ Run Now", key=f"run_{sched.id}", type="primary"):
                try:
                    _ok, _msg = execute_strategy(sched, _snapshot)
                    if _ok:
                        st.success(f"Executed: {_msg}")
                    else:
                        st.error(f"Not executed: {_msg}")
                    # Refresh saved schedules (last_run updated)
                    st.rerun()
                except Exception as _ex:
                    st.error(f"Error: {_ex}")

            # Toggle enabled
            _toggle_lbl = "⏸ Disable" if sched.enabled else "▶ Enable"
            if _sb2.button(_toggle_lbl, key=f"tog_{sched.id}"):
                sched.enabled = not sched.enabled
                save_schedules(schedules)
                st.rerun()

            # Delete
            if _sb3.button("🗑 Delete", key=f"del_{sched.id}"):
                schedules = [s for s in schedules if s.id != sched.id]
                save_schedules(schedules)
                st.success("Schedule deleted.")
                st.rerun()

st.divider()

# ── Background runner instructions ───────────────────────────────────────────
with st.expander("🖥 Running the Scheduler in Background"):
    st.markdown("""
**Start the background scheduler daemon:**

```bash
# From the options_signals directory:
python automation/scheduler.py --interval 60

# Dry-run mode (no positions added):
python automation/scheduler.py --dry-run --interval 60

# Offline mode (simulated market data):
python automation/scheduler.py --offline --interval 60
```

The scheduler checks every `--interval` seconds (default 60). When a strategy's conditions
are met and its scheduled time arrives (±5 min window), it executes automatically.

**Logs** are written to stdout with ISO timestamps. Redirect to a file:
```bash
python automation/scheduler.py --interval 60 >> scheduler.log 2>&1 &
```
""")

st.caption(
    "⚠️ Scheduled execution adds positions to the paper portfolio by default (dry_run=True). "
    "Disable dry-run only after thorough testing."
)
