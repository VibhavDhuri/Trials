"""
Streamlit web dashboard — full options trading signals interface.
Run: streamlit run app.py
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from typing import List, Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

sys.path.insert(0, os.path.dirname(__file__))

from auth.upstox_auth import get_stored_token, validate_token, AUTH_INSTRUCTIONS, build_auth_url
from config import INDICES, IST
from data.market_data import MarketDataFetcher
from data.options_chain import OptionsChainFetcher
from data.upstox_client import UpstoxClient
from analysis.iv_analysis import analyze_iv_environment
from analysis.oi_analysis import analyze_oi
from analysis.signals import Signal, Direction, Confidence, generate_signals
from analysis.strategy_advisor import build_strategy_details, StrategyDetails
from utils.helpers import (
    is_market_open, market_status, now_ist, format_inr, dte_label, days_to_expiry
)

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Options Trading Signals",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

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

# ── Auto-refresh during market hours ─────────────────────────────────────────
_refresh_interval = 30_000 if is_market_open() else 120_000
st_autorefresh(interval=_refresh_interval, key="market_refresh")

# ── Auth / client setup (cached per session) ─────────────────────────────────
@st.cache_resource(show_spinner=False)
def _build_client():
    token = get_stored_token()
    if token and validate_token(token):
        return UpstoxClient(token), False  # (client, offline)
    return None, True


def _build_fetchers(offline: bool, client: Optional[UpstoxClient]):
    mdf = MarketDataFetcher(client, offline)
    ocf = OptionsChainFetcher(client, offline)
    return mdf, ocf


# ── Data loading (cached with TTL) ───────────────────────────────────────────
@st.cache_data(ttl=30, show_spinner="Fetching market data...")
def load_spot(symbol: str, _offline: bool):
    client, offline = _build_client()
    mdf = MarketDataFetcher(client, offline)
    return mdf.get_spot(symbol), now_ist().strftime("%H:%M:%S IST")


@st.cache_data(ttl=30, show_spinner="Loading options chain...")
def load_chain(symbol: str, expiry: str, spot: float, _offline: bool):
    client, offline = _build_client()
    _, ocf = _build_fetchers(offline, client)
    return ocf.get_chain_df(symbol, expiry, spot)


@st.cache_data(ttl=300, show_spinner="Computing IV history...")
def load_iv_range(symbol: str, _offline: bool):
    client, offline = _build_client()
    mdf = MarketDataFetcher(client, offline)
    return mdf.get_historical_iv_range(symbol)


@st.cache_data(ttl=600, show_spinner="Loading expiry dates...")
def load_expiries(symbol: str, _offline: bool):
    client, offline = _build_client()
    _, ocf = _build_fetchers(offline, client)
    return ocf.get_expiries(symbol)


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("📈 Options Signals")
    st.markdown("---")

    client_obj, is_offline = _build_client()

    if is_offline:
        st.warning("**OFFLINE MODE** — Sample data  \nSet `UPSTOX_ACCESS_TOKEN` in `.env` for live data.")
        with st.expander("How to authenticate"):
            st.code(AUTH_INSTRUCTIONS, language="text")
        if st.button("Generate Auth URL"):
            try:
                st.code(build_auth_url())
            except Exception:
                st.error("Set UPSTOX_API_KEY in .env first.")
    else:
        st.success("**LIVE** — Connected to Upstox")

    ms = market_status()
    ms_color = {"LIVE": "green", "PRE-OPEN": "orange", "CLOSED": "gray"}.get(ms, "gray")
    st.markdown(f"Market: :{ms_color}[**{ms}**]")

    st.markdown("---")
    symbol = st.selectbox(
        "Index",
        options=list(INDICES.keys()),
        format_func=lambda k: INDICES[k].display_name,
    )

    expiries = load_expiries(symbol, is_offline)
    if not expiries:
        st.error("No expiry dates available.")
        st.stop()

    expiry_labels = [f"{e}  ({dte_label(e)})" for e in expiries]
    expiry_idx = st.selectbox("Expiry", range(len(expiries)), format_func=lambda i: expiry_labels[i])
    selected_expiry = expiries[expiry_idx]

    st.markdown("---")
    signal_filter = st.multiselect(
        "Filter signals",
        options=["BULLISH", "BEARISH", "NEUTRAL", "RANGE_BOUND", "MIXED"],
        default=["BULLISH", "BEARISH", "NEUTRAL", "RANGE_BOUND", "MIXED"],
    )
    show_all_expiries = st.checkbox("Signals for all expiries", value=False)

    st.markdown("---")
    st.caption(f"Auto-refresh every {'30s' if is_market_open() else '2m'}")


# ── Load data ─────────────────────────────────────────────────────────────────
spot_data, last_updated = load_spot(symbol, is_offline)
spot = spot_data.get("last_price", 0.0)
ohlc = spot_data.get("ohlc", {})
net_chg = spot_data.get("net_change", 0.0)

chain_df = load_chain(symbol, selected_expiry, spot, is_offline)
iv_52wh, iv_52wl = load_iv_range(symbol, is_offline)
iv_env = analyze_iv_environment(chain_df, spot, iv_52wh, iv_52wl)
oi_result = analyze_oi(chain_df, spot)
signals = generate_signals(chain_df, iv_env, oi_result, spot, selected_expiry)

# Load signals for all expiries if requested
if show_all_expiries:
    for exp in expiries[1:6]:  # cap at 6 to avoid rate limits
        df_e = load_chain(symbol, exp, spot, is_offline)
        if not df_e.empty:
            iv_e = analyze_iv_environment(df_e, spot, iv_52wh, iv_52wl)
            oi_e = analyze_oi(df_e, spot)
            signals.extend(generate_signals(df_e, iv_e, oi_e, spot, exp))

# Filter signals
if signal_filter:
    signals = [s for s in signals if s.direction.value in signal_filter]

cfg = INDICES[symbol]

# ── Header ────────────────────────────────────────────────────────────────────
col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 2])
with col1:
    chg_arrow = "▲" if net_chg >= 0 else "▼"
    chg_colour = "green" if net_chg >= 0 else "red"
    st.markdown(
        f"### {cfg.display_name}  "
        f"`{spot:,.2f}`  "
        f"<span style='color:{chg_colour}'>{chg_arrow} {net_chg:+.2f}%</span>",
        unsafe_allow_html=True,
    )
    st.caption(f"O: {ohlc.get('open',0):,.0f}  H: {ohlc.get('high',0):,.0f}  "
               f"L: {ohlc.get('low',0):,.0f}  PC: {ohlc.get('close',0):,.0f}")
with col2:
    st.metric("IV Rank", f"{iv_env.iv_rank:.0f}/100")
with col3:
    st.metric("ATM IV", f"{iv_env.atm_iv*100:.1f}%")
with col4:
    st.metric("PCR (OI)", f"{oi_result.pcr_oi:.2f}")
with col5:
    st.caption(f"Last updated: **{last_updated}**" +
               ("  |  🟡 OFFLINE" if is_offline else ""))

st.divider()

# ── Section 1: Active Signals ─────────────────────────────────────────────────
st.subheader("Active Signals")

if not signals:
    st.info("No signals generated. Try enabling more signal filters or selecting a different expiry.")
else:
    sorted_sigs = sorted(
        signals,
        key=lambda s: ({"HIGH": 0, "MEDIUM": 1, "LOW": 2}[s.confidence.value], s.expiry_date),
    )
    cols_per_row = 2
    for i in range(0, min(len(sorted_sigs), 6), cols_per_row):
        row_sigs = sorted_sigs[i: i + cols_per_row]
        cols = st.columns(cols_per_row)
        for j, sig in enumerate(row_sigs):
            with cols[j]:
                conf_col = _CONF_COLOR[sig.confidence]
                dir_emoji = _DIR_EMOJI.get(sig.direction, "⚪")
                st.markdown(
                    f"""
                    <div style="border:2px solid {conf_col};border-radius:10px;padding:12px;margin-bottom:8px">
                        <h4 style="margin:0">{dir_emoji} {sig.direction.value}
                        <span style="background:{conf_col};color:black;border-radius:4px;padding:2px 6px;font-size:0.75em;margin-left:8px">{sig.confidence.value}</span>
                        </h4>
                        <p style="margin:4px 0;color:#aaa">{sig.expiry_date} &nbsp;({dte_label(sig.expiry_date)})</p>
                        <p style="margin:4px 0"><b>Strategy:</b> {sig.strategy}</p>
                        <p style="margin:4px 0;font-size:0.85em;color:#ccc">{sig.strategy_brief}</p>
                        <hr style="border-color:#444;margin:8px 0">
                        <table style="width:100%;font-size:0.85em">
                          <tr><td>ATM Strike</td><td align="right"><b>{sig.atm_strike:,.0f}</b></td>
                              <td>Max Pain</td><td align="right"><b>{sig.max_pain:,.0f}</b></td></tr>
                          <tr><td>IV Rank</td><td align="right"><b>{sig.iv_rank:.0f}/100</b></td>
                              <td>ATM IV</td><td align="right"><b>{sig.atm_iv_pct:.1f}%</b></td></tr>
                          <tr><td>PCR (OI)</td><td align="right"><b>{sig.pcr_oi:.2f}</b></td>
                              <td>1-SD Move</td><td align="right"><b>±{sig.expected_move_pts:.0f}pts</b></td></tr>
                        </table>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                with st.expander("Reasoning & Strategy Details"):
                    st.markdown("**Signal Sources:**")
                    for r in sig.reasons:
                        st.markdown(f"- {r}")

                    if sig.recommended_strikes:
                        st.markdown(
                            f"**Recommended Strike(s):** {', '.join(str(int(s)) for s in sig.recommended_strikes)}"
                        )

                    if not chain_df.empty:
                        det: StrategyDetails = build_strategy_details(sig, chain_df, symbol)
                        if det.legs:
                            st.markdown(f"**{det.name} — Legs:**")
                            legs_df = pd.DataFrame(det.legs)
                            st.dataframe(legs_df[["action", "opt_type", "strike", "ltp", "iv", "delta"]],
                                         use_container_width=True, hide_index=True)
                            cols2 = st.columns(3)
                            cols2[0].metric("Max Profit", format_inr(det.max_profit) if det.max_profit else "Unlimited")
                            cols2[1].metric("Max Loss", format_inr(det.max_loss) if det.max_loss else "Unlimited")
                            cols2[2].metric("Net Premium", format_inr(det.net_premium * cfg.lot_size))

                            if det.breakevens:
                                be_str = " / ".join(f"{b:,.0f}" for b in det.breakevens)
                                st.markdown(f"**Breakeven(s):** {be_str}")
                            if det.risk_reward:
                                st.markdown(f"**Risk/Reward:** {det.risk_reward:.2f}:1")
                            st.caption(det.disclaimer)

st.divider()

# ── Section 2: Options Chain ──────────────────────────────────────────────────
st.subheader(f"Options Chain — {selected_expiry}  ({dte_label(selected_expiry)})")

if chain_df.empty:
    st.warning("No options chain data available.")
else:
    # Build display table
    ce = chain_df[chain_df["opt_type"] == "CE"].set_index("strike")
    pe = chain_df[chain_df["opt_type"] == "PE"].set_index("strike")
    strikes = sorted(set(ce.index) | set(pe.index))

    rows = []
    for k in strikes:
        c = ce.loc[k] if k in ce.index else pd.Series(dtype=float)
        p = pe.loc[k] if k in pe.index else pd.Series(dtype=float)

        def g(s, col, fmt="{:.2f}"):
            val = s.get(col, 0) if not s.empty else 0
            try:
                return fmt.format(val)
            except Exception:
                return str(val)

        is_atm = abs(k - spot) < (ce.index.to_series().diff().abs().median() * 0.6)
        is_mp = abs(k - oi_result.max_pain) < 1

        rows.append({
            "Strike": f"{'→' if is_atm else ''}{int(k)}{'◆' if is_mp else ''}",
            "CE_OI": g(c, "oi", "{:,.0f}"),
            "CE_OI_Chg": g(c, "oi_chg", "{:+,.0f}"),
            "CE_IV": g(c, "iv", "{:.1f}%"),
            "CE_Delta": g(c, "delta", "{:.3f}"),
            "CE_Bid": g(c, "bid", "{:.1f}"),
            "CE_LTP": g(c, "ltp", "{:.2f}"),
            "CE_Ask": g(c, "ask", "{:.1f}"),
            "CE_Theta": g(c, "theta", "{:.2f}"),
            "│": "│",
            "PE_Theta": g(p, "theta", "{:.2f}"),
            "PE_Bid": g(p, "bid", "{:.1f}"),
            "PE_LTP": g(p, "ltp", "{:.2f}"),
            "PE_Ask": g(p, "ask", "{:.1f}"),
            "PE_Delta": g(p, "delta", "{:.3f}"),
            "PE_IV": g(p, "iv", "{:.1f}%"),
            "PE_OI_Chg": g(p, "oi_chg", "{:+,.0f}"),
            "PE_OI": g(p, "oi", "{:,.0f}"),
        })

    chain_display = pd.DataFrame(rows)

    def _highlight_chain(row):
        k_str = row["Strike"].replace("→", "").replace("◆", "")
        try:
            k = int(k_str)
        except ValueError:
            return [""] * len(row)
        is_atm = abs(k - spot) < 60
        is_mp = abs(k - oi_result.max_pain) < 1
        base_ce = "background-color: #0d2b0d" if is_atm else ("background-color: #1a1a00" if is_mp else "")
        base_pe = "background-color: #2b0d0d" if is_atm else ("background-color: #1a1a00" if is_mp else "")

        styles = []
        for col in row.index:
            if col.startswith("CE_"):
                styles.append(f"color:#90ee90;{base_ce}")
            elif col.startswith("PE_"):
                styles.append(f"color:#ff9999;{base_pe}")
            elif col == "Strike":
                s = "font-weight:bold;"
                if is_atm:
                    s += "background-color:#004400;"
                elif is_mp:
                    s += "background-color:#444400;"
                styles.append(s)
            else:
                styles.append("")
        return styles

    st.markdown(
        "_→ ATM strike  |  ◆ Max Pain strike  |  "
        "<span style='color:#90ee90'>■</span> CE (Calls)  |  "
        "<span style='color:#ff9999'>■</span> PE (Puts)_",
        unsafe_allow_html=True,
    )
    styled = chain_display.style.apply(_highlight_chain, axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True, height=420)

st.divider()

# ── Section 3: OI Analysis ────────────────────────────────────────────────────
st.subheader("OI Analysis")

if not chain_df.empty:
    col_oi1, col_oi2 = st.columns([3, 1])

    with col_oi1:
        # OI bar chart
        oi_plot = pd.DataFrame({
            "Strike": list(oi_result.call_oi_by_strike.index) + list(oi_result.put_oi_by_strike.index),
            "OI": list(oi_result.call_oi_by_strike.values) + list(oi_result.put_oi_by_strike.values),
            "Type": ["CE"] * len(oi_result.call_oi_by_strike) + ["PE"] * len(oi_result.put_oi_by_strike),
        })

        fig_oi = px.bar(
            oi_plot, x="Strike", y="OI", color="Type", barmode="group",
            color_discrete_map={"CE": "#2ecc71", "PE": "#e74c3c"},
            title=f"Open Interest by Strike — {selected_expiry}",
        )
        fig_oi.add_vline(x=spot, line_dash="dash", line_color="white",
                         annotation_text=f"Spot {spot:,.0f}", annotation_position="top right")
        fig_oi.add_vline(x=oi_result.max_pain, line_dash="dot", line_color="yellow",
                         annotation_text=f"Max Pain {oi_result.max_pain:,.0f}",
                         annotation_position="top left")
        fig_oi.update_layout(template="plotly_dark", height=400)
        st.plotly_chart(fig_oi, use_container_width=True)

    with col_oi2:
        st.metric("PCR (OI)", f"{oi_result.pcr_oi:.3f}")
        st.metric("PCR (Volume)", f"{oi_result.pcr_volume:.3f}")
        st.metric("Max Pain", f"{oi_result.max_pain:,.0f}")
        st.metric("Distance", f"{oi_result.max_pain_distance:+.0f} pts")
        st.caption(f"Signal: **{oi_result.pcr_oi_signal}**")
        st.info(oi_result.pcr_oi_note)

        if oi_result.support_levels:
            st.markdown(f"**Support:** {', '.join(str(int(s)) for s in oi_result.support_levels[:3])}")
        if oi_result.resistance_levels:
            st.markdown(f"**Resistance:** {', '.join(str(int(r)) for r in oi_result.resistance_levels[:3])}")

st.divider()

# ── Section 4: IV Analysis ────────────────────────────────────────────────────
st.subheader("IV Analysis")

if not chain_df.empty:
    col_iv1, col_iv2 = st.columns([2, 1])

    with col_iv1:
        # IV smile chart (one expiry)
        ce_iv = chain_df[chain_df["opt_type"] == "CE"][["strike", "iv", "delta"]].copy()
        pe_iv = chain_df[chain_df["opt_type"] == "PE"][["strike", "iv", "delta"]].copy()
        ce_iv["Type"] = "CE"
        pe_iv["Type"] = "PE"
        iv_smile = pd.concat([ce_iv, pe_iv])

        fig_smile = px.line(
            iv_smile, x="strike", y="iv", color="Type",
            color_discrete_map={"CE": "#2ecc71", "PE": "#e74c3c"},
            title=f"Volatility Smile — {selected_expiry}",
            labels={"iv": "IV (%)", "strike": "Strike"},
        )
        fig_smile.add_vline(x=spot, line_dash="dash", line_color="white",
                            annotation_text="Spot")
        fig_smile.update_layout(template="plotly_dark", height=350)
        st.plotly_chart(fig_smile, use_container_width=True)

    with col_iv2:
        st.markdown(f"**IV Environment: {iv_env.regime}**")

        # IV Rank gauge
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=iv_env.iv_rank,
            title={"text": "IV Rank"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "#3498db"},
                "steps": [
                    {"range": [0, 30], "color": "#1a3a1a"},
                    {"range": [30, 70], "color": "#3a3a1a"},
                    {"range": [70, 100], "color": "#3a1a1a"},
                ],
                "threshold": {"line": {"color": "white", "width": 3}, "value": iv_env.iv_rank},
            },
        ))
        fig_gauge.update_layout(template="plotly_dark", height=220, margin=dict(t=40, b=10))
        st.plotly_chart(fig_gauge, use_container_width=True)

        st.metric("ATM IV", f"{iv_env.atm_iv*100:.1f}%")
        st.metric("IV Percentile", f"{iv_env.iv_percentile:.0f}th")
        if iv_env.hv_21d:
            st.metric("21d HV", f"{iv_env.hv_21d*100:.1f}%")
        if iv_env.iv_vs_hv:
            st.metric("IV/HV Ratio", f"{iv_env.iv_vs_hv:.2f}x")
        st.metric("Put Skew", f"{iv_env.skew*100:+.1f}%")
        st.caption(iv_env.regime_note)

st.divider()

# ── Section 5: Greeks Heatmap ─────────────────────────────────────────────────
st.subheader("Greeks Heatmap")

if not chain_df.empty:
    greek_tab = st.tabs(["Delta", "Gamma", "Theta", "Vega"])

    for i, greek in enumerate(["delta", "gamma", "theta", "vega"]):
        with greek_tab[i]:
            g_ce = chain_df[chain_df["opt_type"] == "CE"][["strike", greek]].rename(columns={greek: "CE"})
            g_pe = chain_df[chain_df["opt_type"] == "PE"][["strike", greek]].rename(columns={greek: "PE"})
            g_merged = g_ce.merge(g_pe, on="strike", how="outer").sort_values("strike")

            fig_g = go.Figure()
            fig_g.add_trace(go.Scatter(x=g_merged["strike"], y=g_merged["CE"],
                                       name="CE", line=dict(color="#2ecc71")))
            fig_g.add_trace(go.Scatter(x=g_merged["strike"], y=g_merged["PE"],
                                       name="PE", line=dict(color="#e74c3c")))
            fig_g.add_vline(x=spot, line_dash="dash", line_color="white",
                            annotation_text="Spot")
            fig_g.update_layout(
                template="plotly_dark", height=280,
                title=f"{greek.capitalize()} across strikes",
                xaxis_title="Strike", yaxis_title=greek.capitalize(),
            )
            st.plotly_chart(fig_g, use_container_width=True)

st.divider()
st.caption(
    "Disclaimer: This tool is for informational purposes only. "
    "It does not constitute financial advice. Options trading involves significant risk. "
    "Past signals do not guarantee future performance. Always conduct your own research."
)
