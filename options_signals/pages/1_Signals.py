"""
Signals dashboard — options chain, IV/OI analysis, Greeks heatmap, alerts.
(Moved from original app.py into its own page.)
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import INDICES, IST
from data.market_data import MarketDataFetcher
from data.options_chain import OptionsChainFetcher
from analysis.iv_analysis import analyze_iv_environment
from analysis.oi_analysis import analyze_oi
from analysis.signals import Signal, Direction, Confidence, generate_signals
from analysis.strategy_advisor import build_strategy_details
from alerts.alert_engine import (
    MarketSnapshot, check_alerts, load_rules, add_rule, remove_rule, ConditionType
)
from alerts.notifiers import build_notifiers
from utils.helpers import is_market_open, market_status, now_ist, format_inr, dte_label
from broker.order_manager import execute_paper_or_live, is_live_trading_enabled, OrderManager

# New feature modules (imported lazily to keep startup fast)
try:
    from data.vix_data import get_vix, interpret_vix, expected_daily_move_pct
    _HAS_VIX = True
except ImportError:
    _HAS_VIX = False

try:
    from analysis.vol_surface import compute_term_structure, term_structure_fig, hv_cone_fig, compute_hv_cone, vol_surface_fig
    _HAS_VOLSURFACE = True
except ImportError:
    _HAS_VOLSURFACE = False

try:
    from data.rollover import compute_rollover, get_sample_rollover
    _HAS_ROLLOVER = True
except ImportError:
    _HAS_ROLLOVER = False

try:
    from data.fii_dii import get_fii_data, interpret_fii
    _HAS_FII = True
except ImportError:
    _HAS_FII = False

try:
    from data.vix_history import get_vix_history, vix_history_fig
    _HAS_VIX_HISTORY = True
except ImportError:
    _HAS_VIX_HISTORY = False

try:
    from analysis.options_flow import detect_flow_signals, flow_summary, flow_table_fig
    _HAS_FLOW = True
except ImportError:
    _HAS_FLOW = False

st.set_page_config(page_title="Signals", page_icon="📊", layout="wide")

_refresh_ms = 30_000 if is_market_open() else 120_000
st_autorefresh(interval=_refresh_ms, key="sig_refresh")

_DIR_EMOJI = {
    Direction.BULLISH:     "🟢",
    Direction.BEARISH:     "🔴",
    Direction.NEUTRAL:     "🟡",
    Direction.RANGE_BOUND: "🔵",
    Direction.MIXED:       "🟣",
}
_CONF_COLOR = {
    Confidence.HIGH:   "#00C851",
    Confidence.MEDIUM: "#FFBB33",
    Confidence.LOW:    "#888888",
}

client   = st.session_state.get("client")
offline  = st.session_state.get("offline", True)

# ── Sidebar controls ──────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Settings")
    symbol = st.selectbox("Index", list(INDICES.keys()),
                          format_func=lambda k: INDICES[k].display_name)
    signal_filter = st.multiselect(
        "Signal filter",
        ["BULLISH","BEARISH","NEUTRAL","RANGE_BOUND","MIXED"],
        default=["BULLISH","BEARISH","NEUTRAL","RANGE_BOUND","MIXED"],
    )
    show_all = st.checkbox("Signals for all expiries", False)

    st.divider()
    st.markdown("### Alerts")
    with st.expander("Add Alert Rule"):
        a_cond  = st.selectbox("Condition", [c.value for c in ConditionType])
        a_thresh = st.number_input("Threshold", value=1.0, step=0.1)
        a_label  = st.text_input("Label (optional)")
        if st.button("Add Alert"):
            add_rule(symbol, a_cond, a_thresh, a_label)
            st.success("Alert added.")

    rules = load_rules()
    active_rules = [r for r in rules if r.index == symbol and r.active]
    if active_rules:
        st.markdown(f"**{len(active_rules)} active alert(s):**")
        for r in active_rules:
            c1, c2 = st.columns([4,1])
            c1.caption(f"{r.label} — last: {r.last_value}")
            if c2.button("✕", key=f"del_{r.id}"):
                remove_rule(r.id)
                st.rerun()

# ── Data loading ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=30, show_spinner="Loading data...")
def _load(symbol, _offline):
    mdf = MarketDataFetcher(st.session_state.get("client"), _offline)
    ocf = OptionsChainFetcher(st.session_state.get("client"), _offline)
    spot_data = mdf.get_spot(symbol)
    expiries  = ocf.get_expiries(symbol)
    iv_range  = mdf.get_historical_iv_range(symbol)
    return spot_data, expiries, iv_range

spot_data, expiries, (iv_52wh, iv_52wl) = _load(symbol, offline)
spot = float(spot_data.get("last_price", 0))
ohlc = spot_data.get("ohlc", {})
net_chg = float(spot_data.get("net_change", 0))

if not expiries:
    st.error("No expiry dates. Check authentication or try offline mode.")
    st.stop()

exp_labels = [f"{e} ({dte_label(e)})" for e in expiries]
exp_idx = st.sidebar.selectbox("Expiry", range(len(expiries)),
                               format_func=lambda i: exp_labels[i])
selected_expiry = expiries[exp_idx]

@st.cache_data(ttl=30)
def _chain(symbol, expiry, spot, _offline):
    ocf = OptionsChainFetcher(st.session_state.get("client"), _offline)
    return ocf.get_chain_df(symbol, expiry, spot)

chain_df = _chain(symbol, selected_expiry, spot, offline)
iv_env   = analyze_iv_environment(chain_df, spot, iv_52wh, iv_52wl)
oi_res   = analyze_oi(chain_df, spot)
signals  = generate_signals(chain_df, iv_env, oi_res, spot, selected_expiry)

if show_all:
    for exp in expiries[1:5]:
        df_e = _chain(symbol, exp, spot, offline)
        if not df_e.empty:
            iv_e = analyze_iv_environment(df_e, spot, iv_52wh, iv_52wl)
            oi_e = analyze_oi(df_e, spot)
            signals.extend(generate_signals(df_e, iv_e, oi_e, spot, exp))

if signal_filter:
    signals = [s for s in signals if s.direction.value in signal_filter]

cfg = INDICES[symbol]

# ── Check alerts ──────────────────────────────────────────────────────────────
snapshot = MarketSnapshot(
    index=symbol, spot=spot, pcr_oi=oi_res.pcr_oi,
    iv_rank=iv_env.iv_rank, max_pain=oi_res.max_pain,
    signal_direction=signals[0].direction.value if signals else "NEUTRAL",
)
fired = check_alerts(snapshot)
if fired:
    for _n in build_notifiers():
        _n.notify(fired)
    for r in fired:
        st.warning(f"🔔 **ALERT FIRED:** {r.label}  (value: {r.last_value:.2f})")

last_upd = now_ist().strftime("%H:%M:%S IST")

# ── Header ────────────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns([3,1,1,1,2])
with c1:
    chg_col = "green" if net_chg >= 0 else "red"
    st.markdown(
        f"### {cfg.display_name}  `{spot:,.2f}`  "
        f"<span style='color:{chg_col}'>{'+' if net_chg>=0 else ''}{net_chg:.2f}%</span>",
        unsafe_allow_html=True,
    )
    st.caption(f"O:{ohlc.get('open',0):,.0f}  H:{ohlc.get('high',0):,.0f}  "
               f"L:{ohlc.get('low',0):,.0f}  PC:{ohlc.get('close',0):,.0f}")
c2.metric("IV Rank",   f"{iv_env.iv_rank:.0f}/100")
c3.metric("ATM IV",    f"{iv_env.atm_iv*100:.1f}%")
c4.metric("PCR",       f"{oi_res.pcr_oi:.2f}")
c5.caption(f"Updated: **{last_upd}**" + ("  🟡 OFFLINE" if offline else ""))

# ── India VIX strip ───────────────────────────────────────────────────────────
if _HAS_VIX:
    try:
        @st.cache_data(ttl=60, show_spinner=False)
        def _load_vix(_offline):
            return get_vix(None if _offline else st.session_state.get("client"))
        vix_data = _load_vix(offline)
        _vix_regime, _vix_col = interpret_vix(vix_data.current)
        _daily_move = expected_daily_move_pct(vix_data.current)
        _vix_sign = "+" if vix_data.day_change_pct >= 0 else ""
        st.markdown(
            f"""<div style="background:#1a1a2e;border-radius:8px;padding:8px 16px;margin-bottom:8px;display:flex;gap:32px;align-items:center">
            <span>🌡 <b>India VIX</b></span>
            <span style="font-size:1.3em;color:{_vix_col}"><b>{vix_data.current:.2f}</b></span>
            <span style="color:{_vix_col}">{_vix_sign}{vix_data.day_change_pct:.2f}% today</span>
            <span style="color:#aaa">Regime: <b>{_vix_regime}</b></span>
            <span style="color:#aaa">Expected daily ±move: <b>{_daily_move:.2f}%</b></span>
            <span style="color:#555;font-size:0.85em">52w: {vix_data.week_low:.1f} – {vix_data.week_high:.1f}</span>
            </div>""",
            unsafe_allow_html=True,
        )
    except Exception:
        pass

# ── VIX 30-day history chart ──────────────────────────────────────────────────
if _HAS_VIX_HISTORY:
    try:
        @st.cache_data(ttl=3600, show_spinner=False)
        def _load_vix_history(_offline):
            return get_vix_history(None if _offline else st.session_state.get("client"))
        _vhist = _load_vix_history(offline)
        if _vhist:
            with st.expander("📉 India VIX — 30-Day History", expanded=False):
                _vhist_fig = vix_history_fig(_vhist)
                st.plotly_chart(_vhist_fig, use_container_width=True)
    except Exception:
        pass

st.divider()

# ── Signals ───────────────────────────────────────────────────────────────────
st.subheader("Active Signals")
sorted_sigs = sorted(signals, key=lambda s: ({"HIGH":0,"MEDIUM":1,"LOW":2}[s.confidence.value], s.expiry_date))

if not sorted_sigs:
    st.info("No signals match the current filter.")
else:
    for i in range(0, min(len(sorted_sigs), 6), 2):
        cols = st.columns(2)
        for j, sig in enumerate(sorted_sigs[i:i+2]):
            with cols[j]:
                cc = _CONF_COLOR[sig.confidence]
                em = _DIR_EMOJI.get(sig.direction,"⚪")
                st.markdown(
                    f"""<div style="border:2px solid {cc};border-radius:10px;padding:12px;margin-bottom:8px">
                    <h4 style="margin:0">{em} {sig.direction.value}
                    <span style="background:{cc};color:black;border-radius:4px;padding:2px 6px;font-size:0.75em;margin-left:8px">{sig.confidence.value}</span></h4>
                    <p style="margin:4px 0;color:#aaa">{sig.expiry_date} ({dte_label(sig.expiry_date)})</p>
                    <p style="margin:4px 0"><b>{sig.strategy}</b></p>
                    <p style="font-size:0.85em;color:#ccc">{sig.strategy_brief}</p>
                    <hr style="border-color:#444;margin:8px 0">
                    <table style="width:100%;font-size:0.85em">
                      <tr><td>ATM</td><td align="right"><b>{sig.atm_strike:,.0f}</b></td>
                          <td>Max Pain</td><td align="right"><b>{sig.max_pain:,.0f}</b></td></tr>
                      <tr><td>IV Rank</td><td align="right"><b>{sig.iv_rank:.0f}/100</b></td>
                          <td>PCR</td><td align="right"><b>{sig.pcr_oi:.2f}</b></td></tr>
                      <tr><td>1-SD Move</td><td align="right" colspan="3"><b>±{sig.expected_move_pts:.0f}pts ({sig.expected_move_pct:.1f}%)</b></td></tr>
                    </table></div>""",
                    unsafe_allow_html=True,
                )
                with st.expander("Reasoning & Details"):
                    for r in sig.reasons:
                        st.markdown(f"- {r}")
                    if sig.recommended_strikes:
                        st.markdown(f"**Recommended:** {', '.join(str(int(s)) for s in sig.recommended_strikes)}")
                    det = build_strategy_details(sig, chain_df, symbol)
                    if det.legs:
                        st.markdown(f"**{det.name} — Legs:**")
                        st.dataframe(pd.DataFrame(det.legs)[["action","opt_type","strike","ltp","iv","delta"]],
                                     use_container_width=True, hide_index=True)
                        cx = st.columns(3)
                        cx[0].metric("Max Profit", format_inr(det.max_profit) if det.max_profit else "∞")
                        cx[1].metric("Max Loss",   format_inr(det.max_loss)   if det.max_loss   else "∞")
                        cx[2].metric("Net Premium", format_inr(det.net_premium * cfg.lot_size))
                        if det.breakevens:
                            st.markdown(f"**Breakeven(s):** {' / '.join(f'{b:,.0f}' for b in det.breakevens)}")
                        st.caption(det.disclaimer)

                        # ── Execute Signal ──────────────────────────────────
                        st.divider()
                        _live = is_live_trading_enabled()
                        _trade_mode = "🔴 LIVE ORDER" if _live else "📋 Paper Trade"
                        st.caption(f"Trade mode: **{_trade_mode}**")
                        if _live:
                            st.warning("Live trading enabled — real money at risk.")
                        _qty = st.number_input(
                            "Quantity (lots)", 1, 50, 1, key=f"sig_qty_{i}_{j}"
                        )
                        if st.button(
                            f"Execute Signal ({_trade_mode})",
                            key=f"exec_{i}_{j}",
                            use_container_width=True,
                        ):
                            st.session_state[f"exec_confirm_{i}_{j}"] = True

                        if st.session_state.get(f"exec_confirm_{i}_{j}"):
                            st.warning(
                                f"⚠️ Execute **{sig.direction.value}** on **{symbol}** "
                                f"— {len(det.legs)} leg(s) in {_trade_mode} mode?"
                            )
                            _ec1, _ec2 = st.columns(2)
                            if _ec1.button("✅ Confirm", key=f"exec_yes_{i}_{j}"):
                                _mgr = None
                                if _live and client:
                                    _mgr = OrderManager(client._token)
                                _exec_ok, _exec_fails, _mode_used = 0, [], "PAPER"
                                for _leg in det.legs:
                                    try:
                                        _ikey = (
                                            f"NSE_FO|{symbol}_{sig.expiry_date}"
                                            f"_{int(_leg['strike'])}_{_leg['opt_type']}"
                                        )
                                        _mode_used, _pos = execute_paper_or_live(
                                            manager=_mgr,
                                            instrument_key=_ikey,
                                            symbol=symbol,
                                            expiry=sig.expiry_date,
                                            strike=float(_leg["strike"]),
                                            opt_type=_leg["opt_type"],
                                            action=_leg["action"],
                                            quantity=_qty,
                                            ltp=float(_leg.get("ltp") or 0),
                                            strategy_tag=sig.strategy,
                                            source="SIGNAL",
                                        )
                                        if _pos:
                                            _exec_ok += 1
                                    except Exception as _e:
                                        _exec_fails.append(str(_e))
                                if _exec_ok:
                                    st.success(
                                        f"✅ {_exec_ok} leg(s) added in **{_mode_used}** mode."
                                        " View in Portfolio or Orders page ▶"
                                    )
                                    st.session_state.pop("portfolio_ltp_map", None)
                                for _fm in _exec_fails:
                                    st.error(f"❌ {_fm}")
                                st.session_state[f"exec_confirm_{i}_{j}"] = False
                            if _ec2.button("❌ Cancel", key=f"exec_no_{i}_{j}"):
                                st.session_state[f"exec_confirm_{i}_{j}"] = False
                                st.rerun()

st.divider()

# ── Options Chain ─────────────────────────────────────────────────────────────
st.subheader(f"Options Chain — {selected_expiry} ({dte_label(selected_expiry)})")
if not chain_df.empty:
    ce = chain_df[chain_df["opt_type"]=="CE"].set_index("strike")
    pe = chain_df[chain_df["opt_type"]=="PE"].set_index("strike")
    rows = []
    for k in sorted(set(ce.index)|set(pe.index)):
        c = ce.loc[k] if k in ce.index else pd.Series(dtype=float)
        p = pe.loc[k] if k in pe.index else pd.Series(dtype=float)
        def g(s,col,fmt="{:.2f}"):
            v = s.get(col,0) if not s.empty else 0
            try: return fmt.format(float(v))
            except: return "—"
        is_atm = abs(k-spot) < cfg.strike_gap*0.6
        is_mp  = abs(k-oi_res.max_pain) < cfg.strike_gap*0.6
        rows.append({
            "Strike": f"{'→' if is_atm else ' '}{int(k)}{'◆' if is_mp else ' '}",
            "CE OI": g(c,"oi","{:,.0f}"), "CE ΔOI": g(c,"oi_chg","{:+,.0f}"),
            "CE IV": g(c,"iv","{:.1f}%"), "CE Δ": g(c,"delta","{:.3f}"),
            "CE Bid": g(c,"bid"), "CE LTP": g(c,"ltp"), "CE Ask": g(c,"ask"),
            "CE Θ": g(c,"theta","{:.1f}"), "│": "│",
            "PE Θ": g(p,"theta","{:.1f}"), "PE Bid": g(p,"bid"),
            "PE LTP": g(p,"ltp"), "PE Ask": g(p,"ask"),
            "PE Δ": g(p,"delta","{:.3f}"), "PE IV": g(p,"iv","{:.1f}%"),
            "PE ΔOI": g(p,"oi_chg","{:+,.0f}"), "PE OI": g(p,"oi","{:,.0f}"),
        })
    disp = pd.DataFrame(rows)

    def _hl(row):
        k_str = row["Strike"].strip().replace("→","").replace("◆","").replace(" ","")
        try: k = int(k_str)
        except: return [""] * len(row)
        is_atm = abs(k-spot) < cfg.strike_gap*0.6
        is_mp  = abs(k-oi_res.max_pain) < cfg.strike_gap*0.6
        styles = []
        for col in row.index:
            if col.startswith("CE"):   s = f"color:#90ee90;{'background:#004400' if is_atm else ('background:#1a1a00' if is_mp else '')}"
            elif col.startswith("PE"): s = f"color:#ff9999;{'background:#2b0d0d' if is_atm else ('background:#1a1a00' if is_mp else '')}"
            elif col == "Strike":      s = "font-weight:bold;" + ("background:#004400;" if is_atm else ("background:#444400;" if is_mp else ""))
            else: s = ""
            styles.append(s)
        return styles

    st.caption("→ ATM  ◆ Max Pain  🟢 CE  🔴 PE")
    st.dataframe(disp.style.apply(_hl, axis=1), use_container_width=True, hide_index=True, height=400)

st.divider()

# ── OI Analysis ───────────────────────────────────────────────────────────────
st.subheader("OI Analysis")
if not chain_df.empty:
    co1, co2 = st.columns([3,1])
    with co1:
        oi_plot = pd.DataFrame({
            "Strike": list(oi_res.call_oi_by_strike.index)+list(oi_res.put_oi_by_strike.index),
            "OI":     list(oi_res.call_oi_by_strike.values)+list(oi_res.put_oi_by_strike.values),
            "Type":   ["CE"]*len(oi_res.call_oi_by_strike)+["PE"]*len(oi_res.put_oi_by_strike),
        })
        fig_oi = px.bar(oi_plot, x="Strike", y="OI", color="Type", barmode="group",
                        color_discrete_map={"CE":"#2ecc71","PE":"#e74c3c"})
        fig_oi.add_vline(x=spot,             line_dash="dash", line_color="white",  annotation_text="Spot")
        fig_oi.add_vline(x=oi_res.max_pain,  line_dash="dot",  line_color="yellow", annotation_text="Max Pain")
        fig_oi.update_layout(template="plotly_dark", height=380, title="Open Interest by Strike")
        st.plotly_chart(fig_oi, use_container_width=True)
    with co2:
        st.metric("PCR (OI)",  f"{oi_res.pcr_oi:.3f}")
        st.metric("Max Pain",  f"{oi_res.max_pain:,.0f}")
        st.metric("Distance",  f"{oi_res.max_pain_distance:+.0f}pts")
        st.info(oi_res.pcr_oi_note)
        if oi_res.support_levels:   st.markdown(f"**Support:** {', '.join(str(int(s)) for s in oi_res.support_levels[:3])}")
        if oi_res.resistance_levels: st.markdown(f"**Resistance:** {', '.join(str(int(r)) for r in oi_res.resistance_levels[:3])}")

# ── Rollover Analysis ─────────────────────────────────────────────────────────
if _HAS_ROLLOVER and len(expiries) >= 2:
    with st.expander("📊 Rollover Analysis"):
        try:
            @st.cache_data(ttl=120, show_spinner=False)
            def _load_rollover(sym, exp1, exp2, sp, _offline):
                ocf = OptionsChainFetcher(st.session_state.get("client"), _offline)
                df1 = ocf.get_chain_df(sym, exp1, sp)
                df2 = ocf.get_chain_df(sym, exp2, sp)
                if df1.empty or df2.empty:
                    return get_sample_rollover(exp1, exp2)
                return compute_rollover(df1, df2, sp, cfg.strike_gap)
            rv = _load_rollover(symbol, selected_expiry, expiries[min(1, len(expiries)-1)], spot, offline)
            rc1, rc2, rc3 = st.columns(3)
            rc1.metric("Rollover %", f"{rv.rollover_pct:.1f}%")
            rc2.metric("IV Cost (pp)", f"{rv.iv_cost_pp:+.2f}")
            rc3.metric("Next Expiry", rv.next_expiry)
            st.caption(rv.interpretation)
        except Exception as _e:
            st.caption(f"Rollover data unavailable: {_e}")

st.divider()

# ── IV Analysis ───────────────────────────────────────────────────────────────
st.subheader("IV Analysis")
if not chain_df.empty:
    ci1, ci2 = st.columns([2,1])
    with ci1:
        iv_smile = pd.concat([
            chain_df[chain_df["opt_type"]=="CE"][["strike","iv"]].assign(Type="CE"),
            chain_df[chain_df["opt_type"]=="PE"][["strike","iv"]].assign(Type="PE"),
        ])
        fig_smile = px.line(iv_smile, x="strike", y="iv", color="Type",
                            color_discrete_map={"CE":"#2ecc71","PE":"#e74c3c"},
                            title=f"Volatility Smile — {selected_expiry}",
                            labels={"iv":"IV (%)","strike":"Strike"})
        fig_smile.add_vline(x=spot, line_dash="dash", line_color="white", annotation_text="Spot")
        fig_smile.update_layout(template="plotly_dark", height=320)
        st.plotly_chart(fig_smile, use_container_width=True)
    with ci2:
        fig_g = go.Figure(go.Indicator(
            mode="gauge+number", value=iv_env.iv_rank,
            title={"text":"IV Rank"},
            gauge={"axis":{"range":[0,100]},"bar":{"color":"#3498db"},
                   "steps":[{"range":[0,30],"color":"#1a3a1a"},{"range":[30,70],"color":"#3a3a1a"},{"range":[70,100],"color":"#3a1a1a"}]},
        ))
        fig_g.update_layout(template="plotly_dark", height=200, margin=dict(t=40,b=10))
        st.plotly_chart(fig_g, use_container_width=True)
        st.metric("ATM IV",      f"{iv_env.atm_iv*100:.1f}%")
        st.metric("21d HV",      f"{iv_env.hv_21d*100:.1f}%" if iv_env.hv_21d else "N/A")
        st.metric("IV/HV Ratio", f"{iv_env.iv_vs_hv:.2f}x"   if iv_env.iv_vs_hv else "N/A")
        st.metric("Put Skew",    f"{iv_env.skew*100:+.1f}%")

# ── Volatility Structure ──────────────────────────────────────────────────────
if _HAS_VOLSURFACE:
    with st.expander("📈 Volatility Term Structure & HV Cone"):
        try:
            @st.cache_data(ttl=120, show_spinner=False)
            def _load_chains_for_structure(sym, exps, sp, _offline):
                ocf = OptionsChainFetcher(st.session_state.get("client"), _offline)
                out = {}
                for e in exps[:6]:
                    df = ocf.get_chain_df(sym, e, sp)
                    if not df.empty:
                        out[e] = df
                return out
            chains_map = _load_chains_for_structure(symbol, expiries, spot, offline)
            if len(chains_map) >= 2:
                vs_col1, vs_col2 = st.columns(2)
                pts = compute_term_structure(chains_map, spot)
                with vs_col1:
                    st.plotly_chart(term_structure_fig(pts), use_container_width=True)
                with vs_col2:
                    hist_data = st.session_state.get("_hist_closes_" + symbol)
                    if hist_data is None and not offline and client:
                        try:
                            import datetime as _dt
                            from data.market_data import MarketDataFetcher as _MDF
                            _mdf = _MDF(client, offline=False)
                            hist_data = _mdf.get_historical_closes(symbol, days=80)
                            st.session_state["_hist_closes_" + symbol] = hist_data
                        except Exception:
                            hist_data = None
                    hv_dict = compute_hv_cone(hist_data) if hist_data is not None and len(hist_data) > 20 else {}
                    if hv_dict:
                        st.plotly_chart(hv_cone_fig(hv_dict, iv_env.atm_iv * 100), use_container_width=True)
                    else:
                        st.caption("HV Cone requires historical closes — available in live mode.")
                st.caption("Vol Surface (3D)")
                try:
                    vs_fig = vol_surface_fig(chains_map, spot)
                    st.plotly_chart(vs_fig, use_container_width=True)
                except Exception:
                    pass
            else:
                st.caption("Term structure requires data for ≥2 expiries.")
        except Exception as _e:
            st.caption(f"Vol structure unavailable: {_e}")

st.divider()

# ── Greeks Heatmap ────────────────────────────────────────────────────────────
st.subheader("Greeks Heatmap")
if not chain_df.empty:
    tabs = st.tabs(["Delta","Gamma","Theta","Vega"])
    for i, greek in enumerate(["delta","gamma","theta","vega"]):
        with tabs[i]:
            g_ce = chain_df[chain_df["opt_type"]=="CE"][["strike",greek]].rename(columns={greek:"CE"})
            g_pe = chain_df[chain_df["opt_type"]=="PE"][["strike",greek]].rename(columns={greek:"PE"})
            merged = g_ce.merge(g_pe, on="strike", how="outer").sort_values("strike")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=merged["strike"],y=merged["CE"],name="CE",line=dict(color="#2ecc71")))
            fig.add_trace(go.Scatter(x=merged["strike"],y=merged["PE"],name="PE",line=dict(color="#e74c3c")))
            fig.add_vline(x=spot, line_dash="dash", line_color="white")
            fig.update_layout(template="plotly_dark", height=260, title=greek.capitalize())
            st.plotly_chart(fig, use_container_width=True)

# ── Institutional Positioning (FII/DII) ──────────────────────────────────────
if _HAS_FII:
    with st.expander("🏦 Institutional Positioning (FII/DII)"):
        try:
            @st.cache_data(ttl=1800, show_spinner=False)
            def _load_fii():
                return get_fii_data()
            fii = _load_fii()
            fi1, fi2, fi3, fi4 = st.columns(4)
            arrow = lambda v: "↑" if v > 0 else "↓"
            fi1.metric("FII Net Futures", f"{arrow(fii.fii_net_futures)} {abs(fii.fii_net_futures):,.0f}",
                       delta_color="normal" if fii.fii_net_futures > 0 else "inverse")
            fi2.metric("FII Net Calls", f"{arrow(fii.fii_net_calls)} {abs(fii.fii_net_calls):,.0f}",
                       delta_color="normal" if fii.fii_net_calls > 0 else "inverse")
            fi3.metric("FII Net Puts", f"{arrow(fii.fii_net_puts)} {abs(fii.fii_net_puts):,.0f}",
                       delta_color="normal" if fii.fii_net_puts > 0 else "inverse")
            fi4.metric("DII Net Futures", f"{arrow(fii.dii_net_futures)} {abs(fii.dii_net_futures):,.0f}",
                       delta_color="normal" if fii.dii_net_futures > 0 else "inverse")
            st.caption(f"📋 {interpret_fii(fii)}  |  Source: {fii.source}  |  Date: {fii.date}")
        except Exception as _e:
            st.caption(f"FII/DII data unavailable: {_e}")

# ── Options Flow / Unusual OI Activity ───────────────────────────────────────
if _HAS_FLOW and not chain_df.empty:
    with st.expander("🌊 Options Flow & Unusual OI Activity"):
        try:
            flow_signals = detect_flow_signals(chain_df, top_n=10)
            fsumm = flow_summary(flow_signals)
            _fa, _fb, _fc = st.columns(3)
            _fa.metric("Bullish Flow Signals", fsumm["bullish_count"])
            _fb.metric("Bearish Flow Signals", fsumm["bearish_count"])
            _fc.metric("Net Bias", fsumm["net_bias"])
            if flow_signals:
                ftab = flow_table_fig(flow_signals)
                st.plotly_chart(ftab, use_container_width=True)
            else:
                st.info("No unusual flow detected in current chain data.")
        except Exception as _fe:
            st.caption(f"Options flow unavailable: {_fe}")

st.divider()
st.caption("⚠️ Informational only. Not financial advice. Options trading involves significant risk.")
