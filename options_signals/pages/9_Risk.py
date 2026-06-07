"""
Risk Management — position sizing, daily loss limits, circuit breaker.
"""
from __future__ import annotations

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import INDICES
from risk.manager import (
    RiskSettings, load_settings, save_settings,
    position_size, daily_pnl_realised, risk_report,
)
from utils.helpers import now_ist

st.set_page_config(page_title="Risk Management", page_icon="🛡", layout="wide")

with st.sidebar:
    st.title("🛡 Risk Management")
    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")
    st.divider()
    st.info(
        "Configure position sizing and daily loss limits here. "
        "The circuit breaker status is shown on the dashboard — "
        "respect it to protect your capital."
    )

st.title("🛡 Risk Management")

settings = load_settings()

# ── Settings form ─────────────────────────────────────────────────────────────
st.subheader("Risk Settings")
with st.form("risk_settings_form"):
    c1, c2 = st.columns(2)
    capital = c1.number_input(
        "Total Capital (₹)",
        min_value=10_000.0, max_value=100_000_000.0,
        value=float(settings.capital), step=10_000.0,
        help="Your total trading capital. Used to compute per-trade risk budget.",
    )
    risk_per_trade = c2.number_input(
        "Max Risk per Trade (%)",
        min_value=0.1, max_value=20.0,
        value=float(settings.risk_per_trade_pct), step=0.1,
        help="Maximum % of capital you are willing to lose on a single trade.",
    )
    daily_limit = c1.number_input(
        "Daily Loss Limit (%)",
        min_value=0.5, max_value=20.0,
        value=float(settings.daily_loss_limit_pct), step=0.5,
        help="Circuit breaker: stop trading for the day if cumulative loss exceeds this %.",
    )
    max_pos = c2.number_input(
        "Max Open Positions",
        min_value=1, max_value=20,
        value=int(settings.max_open_positions), step=1,
        help="Maximum number of simultaneous open positions.",
    )
    if st.form_submit_button("Save Settings", type="primary"):
        new_s = RiskSettings(
            capital=capital,
            risk_per_trade_pct=risk_per_trade,
            daily_loss_limit_pct=daily_limit,
            max_open_positions=max_pos,
        )
        save_settings(new_s)
        settings = new_s
        st.success("Settings saved.")

st.divider()

# ── Current risk status ───────────────────────────────────────────────────────
st.subheader("Current Risk Status")

today_pnl = daily_pnl_realised()
report = risk_report(settings, today_pnl)

col1, col2, col3, col4 = st.columns(4)

col1.metric(
    "Daily P&L (Realised)",
    f"₹{today_pnl:+,.0f}",
    delta_color="normal" if today_pnl >= 0 else "inverse",
)
col2.metric(
    "Daily Loss Limit",
    f"₹{report['daily_loss_limit_inr']:,.0f}",
    f"{report['daily_loss_used_pct']:.1f}% used",
    delta_color="normal" if report["daily_loss_used_pct"] < 80 else "inverse",
)
col3.metric(
    "Open Positions",
    f"{report['open_positions']} / {report['max_positions']}",
    delta_color="normal" if not report["positions_limit_hit"] else "inverse",
)
col4.metric(
    "Risk Budget / Trade",
    f"₹{report['risk_per_trade_inr']:,.0f}",
)

# Circuit breaker alert
if report["circuit_breaker"]:
    st.error(
        "🚨 **CIRCUIT BREAKER ACTIVE** — Daily loss limit breached.  \n"
        "Do not place any new trades today. Review your open positions and consider closing them."
    )
elif report["daily_loss_used_pct"] >= 80:
    st.warning(
        f"⚠️ **{report['daily_loss_used_pct']:.0f}% of daily loss limit used.**  \n"
        "Approach new positions with caution."
    )
elif report["positions_limit_hit"]:
    st.warning(
        f"⚠️ **Maximum open positions ({report['max_positions']}) reached.**  \n"
        "Close an existing position before adding new ones."
    )
else:
    st.success("✅ All risk limits within acceptable range.")

# Daily loss progress bar
st.markdown("**Daily Loss Limit Usage:**")
bar_val = min(report["daily_loss_used_pct"] / 100.0, 1.0)
bar_color = "red" if bar_val >= 1 else ("orange" if bar_val >= 0.8 else "green")
st.progress(bar_val, text=f"{report['daily_loss_used_pct']:.1f}%")

st.divider()

# ── Position sizing calculator ─────────────────────────────────────────────────
st.subheader("Position Size Calculator")
st.caption(
    "Calculates the max number of lots you can buy such that your maximum loss "
    "(entire premium paid) stays within your risk budget per trade."
)

with st.container():
    pc1, pc2, pc3, pc4 = st.columns(4)
    calc_symbol  = pc1.selectbox("Index", list(INDICES.keys()), key="risk_sym")
    calc_premium = pc2.number_input("Option Premium (₹)", 1.0, 5000.0, 100.0, step=1.0)
    calc_capital = pc3.number_input(
        "Capital (₹)", 10_000.0, 100_000_000.0,
        float(settings.capital), step=10_000.0, key="risk_cap"
    )
    calc_risk    = pc4.number_input(
        "Risk % per Trade", 0.1, 20.0, float(settings.risk_per_trade_pct), step=0.1
    )

    if st.button("Calculate", type="primary"):
        cfg = INDICES[calc_symbol]
        lots = position_size(calc_capital, calc_risk, calc_premium, cfg.lot_size)
        max_loss    = calc_premium * lots * cfg.lot_size
        notional    = calc_premium * lots * cfg.lot_size
        budget      = calc_capital * calc_risk / 100

        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Recommended Lots", str(lots))
        r2.metric("Max Loss (full premium)", f"₹{max_loss:,.0f}")
        r3.metric("Risk Budget", f"₹{budget:,.0f}")
        r4.metric("Lot Size", str(cfg.lot_size))

        st.caption(
            f"At ₹{calc_premium:.2f} premium × {lots} lot(s) × {cfg.lot_size} lot size "
            f"= ₹{max_loss:,.0f} max loss — "
            f"{max_loss/calc_capital*100:.2f}% of capital."
        )

st.divider()

# ── Auto-Hedge Advisor ────────────────────────────────────────────────────────
st.subheader("Portfolio Delta & Auto-Hedge Advisor")

try:
    from analysis.hedge_advisor import suggest_hedge, portfolio_net_delta, HedgeSuggestion
    from positions.tracker import get_open_positions as _get_open
    from data.options_chain import OptionsChainFetcher as _OCF
    from data.market_data import MarketDataFetcher as _MDF
    _HAS_HEDGE = True
except ImportError:
    _HAS_HEDGE = False

if _HAS_HEDGE:
    _ope = _get_open()
    _hedge_threshold = st.slider("Delta hedge threshold (lots-equivalent)", 1.0, 50.0, 10.0, step=1.0,
                                  help="Suggest a hedge when |net portfolio delta| exceeds this value.")
    if _ope:
        _hedge_sym = st.selectbox("Compute delta for", list({p.symbol for p in _ope}), key="hedge_sym")
        _hedge_exp = st.selectbox("Expiry", sorted({p.expiry for p in _ope if p.symbol == _hedge_sym}), key="hedge_exp")

        @st.cache_data(ttl=60, show_spinner=False)
        def _load_hedge_chain(sym, exp, _off):
            import pandas as pd
            if _off or not st.session_state.get("client"):
                return pd.DataFrame()
            _ocf = _OCF(st.session_state.get("client"), offline=False)
            _mdf = _MDF(st.session_state.get("client"), offline=False)
            _sp = float(_mdf.get_spot(sym).get("last_price", 22500) or 22500)
            return _ocf.get_chain_df(sym, exp, _sp), _sp

        _hc_result = _load_hedge_chain(_hedge_sym, _hedge_exp, offline)
        if isinstance(_hc_result, tuple):
            _hchain, _hspot = _hc_result
        else:
            _hchain, _hspot = _hc_result, 22500.0

        _sug = suggest_hedge(_ope, _hspot, _hchain, threshold=_hedge_threshold)
        _nd = _sug.net_delta_before

        _hc1, _hc2 = st.columns(2)
        _hc1.metric("Net Portfolio Delta", f"{_nd:+.2f}", help="Sum of (delta × qty × lot_size × sign) across all open positions")
        _hc2.metric("Threshold", f"±{_hedge_threshold:.0f}")

        if _sug.needed:
            st.warning(
                f"⚠️ **{_sug.reason}**  \n"
                f"Suggested: {_sug.action} **{_sug.instrument_desc}** × {_sug.quantity} lot(s)  \n"
                f"Estimated cost: ₹{_sug.estimated_cost_inr:,.0f}  |  Net delta after: {_sug.net_delta_after:+.2f}"
            )
            if st.button("Add Hedge to Portfolio", type="primary"):
                from positions.tracker import add_position as _add_pos
                _add_pos(
                    symbol=_hedge_sym, expiry=_hedge_exp,
                    strike=float(_hspot), opt_type="PE" if _sug.action == "BUY" and _nd > 0 else "CE",
                    action=_sug.action, quantity=_sug.quantity, entry_price=0.0,
                    source="MANUAL", strategy_tag="Auto-Hedge",
                )
                st.success(f"Hedge added to portfolio. Update entry price in Portfolio page.")
                st.session_state.pop("portfolio_ltp_map", None)
        else:
            st.success(f"✅ {_sug.reason}")
    else:
        st.info("No open positions — delta hedging not required.")
else:
    st.caption("Auto-hedge advisor module not available.")

st.divider()

# ── Risk guidelines ───────────────────────────────────────────────────────────
with st.expander("Risk Management Guidelines"):
    st.markdown(f"""
**1. Position Sizing**
- Never risk more than **{settings.risk_per_trade_pct:.1f}%** of capital on a single trade.
- For long options: max loss = premium paid × lots × lot size.
- Risk budget per trade: ₹{settings.risk_per_trade_pct/100*settings.capital:,.0f}

**2. Daily Loss Limit**
- Stop trading for the day if cumulative loss exceeds **{settings.daily_loss_limit_pct:.1f}%** of capital (₹{settings.daily_loss_limit_pct/100*settings.capital:,.0f}).
- This prevents revenge trading and emotional decisions.

**3. Portfolio Concentration**
- Keep maximum **{settings.max_open_positions}** open positions at a time.
- Avoid overlapping directional bets (e.g. 3 bullish positions simultaneously).

**4. STT Warning**
- STT on options exercise = 0.125% of settlement value (intrinsic × lot size).
- For deep ITM options near expiry, STT can exceed the gross profit.
- Always account for all costs (STT + brokerage + exchange charges).

**5. Options-Specific**
- Time decay (theta) accelerates in the last 5 trading days before expiry.
- Avoid holding 0DTE or 1DTE long options overnight.
- Use spreads to cap max loss when selling options.
""")

st.caption("⚠️  Risk controls are advisory — they do not automatically block order placement. Discipline is your responsibility.")
