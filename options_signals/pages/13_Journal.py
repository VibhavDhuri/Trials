"""
Trade Journal — notes, tags, conviction and mood per trade.
"""
from __future__ import annotations

import os
import sys
import datetime

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import IST
from journal.journal import (
    add_entry,
    get_all_entries,
    delete_entry,
    insights,
    COMMON_TAGS,
    MOOD_OPTIONS,
    JournalEntry,
)
from positions.tracker import get_all_positions
from utils.helpers import now_ist

st.set_page_config(page_title="Trade Journal", page_icon="📓", layout="wide")

client  = st.session_state.get("client")
offline = st.session_state.get("offline", True)

# ---------------------------------------------------------------------------
# Mood emoji map
# ---------------------------------------------------------------------------
MOOD_EMOJI: dict[str, str] = {
    "DISCIPLINED": "🎯",
    "CONFIDENT":   "😊",
    "UNCERTAIN":   "😐",
    "FOMO":        "😰",
    "REVENGE":     "😤",
}

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
all_entries  = get_all_entries()
all_positions = get_all_positions()

unique_symbols = sorted({e.symbol for e in all_entries if e.symbol})
pos_labels = ["No position"] + [
    f"{p.id} — {p.symbol} {p.expiry} {p.strike} {p.opt_type}"
    for p in all_positions
]

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("📓 Trade Journal")

    sym_filter = st.selectbox(
        "Symbol Filter",
        ["All"] + unique_symbols,
        key="jnl_sym_filter",
    )
    tag_filter = st.multiselect(
        "Tag Filter",
        options=COMMON_TAGS,
        key="jnl_tag_filter",
    )
    mood_filter = st.multiselect(
        "Mood Filter",
        options=MOOD_OPTIONS,
        key="jnl_mood_filter",
    )

    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
st.title("📓 Trade Journal")
st.markdown("Log your thoughts, conviction, and mood for every trade.")
st.divider()

# ---------------------------------------------------------------------------
# Add Entry Form
# ---------------------------------------------------------------------------
st.subheader("Add New Entry")
with st.form("journal_add_form", clear_on_submit=True):
    form_c1, form_c2 = st.columns(2)

    with form_c1:
        sel_pos_label = st.selectbox(
            "Position (optional)",
            pos_labels,
            key="jnl_form_pos",
        )
        # Auto-fill symbol from position
        if sel_pos_label != "No position":
            pos_id_str = sel_pos_label.split(" — ")[0]
            pos_obj = next((p for p in all_positions if p.id == pos_id_str), None)
            auto_symbol = pos_obj.symbol if pos_obj else ""
        else:
            pos_id_str = ""
            auto_symbol = ""

        form_symbol = st.text_input(
            "Symbol",
            value=auto_symbol,
            placeholder="e.g. NIFTY, BANKNIFTY",
            key="jnl_form_symbol",
        )
        form_date = st.date_input(
            "Date",
            value=datetime.date.today(),
            key="jnl_form_date",
        )
        form_tags = st.multiselect(
            "Tags",
            options=COMMON_TAGS,
            key="jnl_form_tags",
        )

    with form_c2:
        form_notes = st.text_area(
            "Notes",
            placeholder="What was your thesis? Entry/exit rationale…",
            height=120,
            key="jnl_form_notes",
        )
        form_conviction = st.slider(
            "Conviction (1=Low, 5=High)",
            min_value=1,
            max_value=5,
            value=3,
            key="jnl_form_conviction",
        )
        form_mood = st.selectbox(
            "Mood",
            options=MOOD_OPTIONS,
            key="jnl_form_mood",
        )

    submitted = st.form_submit_button("💾 Save Entry", type="primary")
    if submitted:
        if not form_symbol.strip():
            st.error("Symbol is required.")
        else:
            add_entry(
                position_id=pos_id_str,
                symbol=form_symbol.strip().upper(),
                date=form_date.isoformat(),
                tags=list(form_tags),
                notes=form_notes.strip(),
                conviction=int(form_conviction),
                mood=form_mood,
                pnl_at_close=None,
            )
            st.success("Journal entry saved!")
            st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Insights Panel (shown only if ≥3 entries with pnl_at_close set)
# ---------------------------------------------------------------------------
scored_entries = [e for e in all_entries if e.pnl_at_close is not None]
if len(scored_entries) >= 3:
    st.subheader("Insights")
    insight_data = insights(all_entries)

    ins_c1, ins_c2, ins_c3 = st.columns(3)

    with ins_c1:
        st.metric(
            "Avg Conviction — Winners",
            f"{insight_data['avg_conviction_winners']:.2f} ★",
        )
        st.metric(
            "Avg Conviction — Losers",
            f"{insight_data['avg_conviction_losers']:.2f} ★",
        )

    with ins_c2:
        st.markdown("**Top Winning Tags**")
        for tag in insight_data.get("top_tags_winning", [])[:3]:
            st.markdown(
                f'<span style="background:#1a5c1a;color:#7fff7f;border-radius:10px;'
                f'padding:2px 10px;margin:2px;display:inline-block;">{tag}</span>',
                unsafe_allow_html=True,
            )

    with ins_c3:
        st.markdown("**Top Losing Tags**")
        for tag in insight_data.get("top_tags_losing", [])[:3]:
            st.markdown(
                f'<span style="background:#5c1a1a;color:#ff7f7f;border-radius:10px;'
                f'padding:2px 10px;margin:2px;display:inline-block;">{tag}</span>',
                unsafe_allow_html=True,
            )

    st.divider()

# ---------------------------------------------------------------------------
# Journal Feed
# ---------------------------------------------------------------------------
st.subheader("Journal Feed")

# Apply filters
def _passes_filter(entry: JournalEntry) -> bool:
    if sym_filter != "All" and entry.symbol != sym_filter:
        return False
    if tag_filter and not any(t in entry.tags for t in tag_filter):
        return False
    if mood_filter and entry.mood not in mood_filter:
        return False
    return True


feed_entries = [e for e in all_entries if _passes_filter(e)]

if not feed_entries:
    st.info("No journal entries yet — or none match your filters. Use the form above to add your first entry!")
else:
    # Initialise delete confirmation state
    if "jnl_delete_confirm" not in st.session_state:
        st.session_state["jnl_delete_confirm"] = None

    for entry in feed_entries:
        mood_em = MOOD_EMOJI.get(entry.mood, "")
        date_disp = entry.date if isinstance(entry.date, str) else str(entry.date)

        # Header row
        hdr_col, del_col = st.columns([8, 1])
        with hdr_col:
            pnl_txt = ""
            if entry.pnl_at_close is not None:
                colour = "green" if entry.pnl_at_close >= 0 else "red"
                sign   = "+" if entry.pnl_at_close >= 0 else ""
                pnl_txt = (
                    f' &nbsp;|&nbsp; <span style="color:{colour}; font-weight:bold;">'
                    f'₹{sign}{entry.pnl_at_close:,.2f}</span>'
                )
            st.markdown(
                f"**{date_disp}** &nbsp;|&nbsp; **{entry.symbol}** "
                f"&nbsp;|&nbsp; {mood_em} {entry.mood}{pnl_txt}",
                unsafe_allow_html=True,
            )
        with del_col:
            if st.session_state["jnl_delete_confirm"] == entry.id:
                if st.button("✅ Confirm", key=f"jnl_del_confirm_{entry.id}"):
                    delete_entry(entry.id)
                    st.session_state["jnl_delete_confirm"] = None
                    st.rerun()
                if st.button("❌ Cancel", key=f"jnl_del_cancel_{entry.id}"):
                    st.session_state["jnl_delete_confirm"] = None
                    st.rerun()
            else:
                if st.button("🗑️", key=f"jnl_del_btn_{entry.id}", help="Delete this entry"):
                    st.session_state["jnl_delete_confirm"] = entry.id
                    st.rerun()

        # Tags
        if entry.tags:
            tags_html = " ".join(
                f'<span style="background:#2a2a4a;color:#aac4ff;border-radius:8px;'
                f'padding:1px 8px;font-size:0.8em;margin:1px;display:inline-block;">'
                f'{tag}</span>'
                for tag in entry.tags
            )
            st.markdown(tags_html, unsafe_allow_html=True)

        # Conviction stars
        stars = "★" * entry.conviction + "☆" * (5 - entry.conviction)
        st.markdown(
            f'<span style="color:#f5c518; font-size:1.1em;">{stars}</span>',
            unsafe_allow_html=True,
        )

        # Notes
        if entry.notes:
            st.markdown(f"_{entry.notes}_")

        st.markdown("---")
