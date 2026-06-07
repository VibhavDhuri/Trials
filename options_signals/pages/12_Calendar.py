"""
Economic & Events Calendar — upcoming RBI, Fed, F&O expiry, earnings dates.
"""
from __future__ import annotations

import os
import sys
import datetime
import calendar as _calendar
from collections import defaultdict

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import IST
from data.events_calendar import (
    get_upcoming_events,
    get_events_in_month,
    get_next_n_events,
    Event,
)
from utils.helpers import now_ist

st.set_page_config(page_title="Events Calendar", page_icon="📅", layout="wide")

client  = st.session_state.get("client")
offline = st.session_state.get("offline", True)

# ---------------------------------------------------------------------------
# Colour map
# ---------------------------------------------------------------------------
IMPACT_COLOUR: dict[str, str] = {
    "HIGH":   "#ff4444",
    "MEDIUM": "#ffaa00",
    "LOW":    "#888888",
}
IMPACT_EMOJI: dict[str, str] = {
    "HIGH":   "🔴",
    "MEDIUM": "🟠",
    "LOW":    "⚪",
}

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("📅 Events Calendar")
    days_ahead = st.slider(
        "Days Ahead",
        min_value=7,
        max_value=90,
        value=30,
        step=1,
        key="cal_days_ahead",
    )

    all_events_for_filter = get_upcoming_events(days_ahead=90)
    all_types = sorted({e.event_type for e in all_events_for_filter})

    event_type_filter = st.multiselect(
        "Event Types",
        options=all_types,
        default=all_types,
        key="cal_type_filter",
    )

    st.caption(f"IST: {now_ist().strftime('%d %b %Y  %H:%M:%S')}")

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
st.title("📅 Events Calendar")
st.markdown("Upcoming RBI, Fed, F&O expiry, earnings, and market holidays.")
st.divider()

# ---------------------------------------------------------------------------
# Load events
# ---------------------------------------------------------------------------
all_upcoming = get_upcoming_events(days_ahead=days_ahead)

# Apply type filter
filtered_events = [
    e for e in all_upcoming
    if (not event_type_filter or e.event_type in event_type_filter)
]

# ---------------------------------------------------------------------------
# Metric strip
# ---------------------------------------------------------------------------
high_count   = sum(1 for e in filtered_events if e.impact == "HIGH")
medium_count = sum(1 for e in filtered_events if e.impact == "MEDIUM")
low_count    = sum(1 for e in filtered_events if e.impact == "LOW")
total_count  = len(filtered_events)

mc1, mc2, mc3, mc4 = st.columns(4)
mc1.metric("🔴 HIGH Impact", high_count)
mc2.metric("🟠 MEDIUM Impact", medium_count)
mc3.metric("⚪ LOW Impact", low_count)
mc4.metric("📅 Total Events", total_count)

st.divider()

# ---------------------------------------------------------------------------
# Next 3 Events
# ---------------------------------------------------------------------------
st.subheader("Next 3 Upcoming Events")
next_3 = get_next_n_events(3)
today_date = datetime.date.today()

for event in next_3:
    colour = IMPACT_COLOUR.get(event.impact, "#888888")
    days_away = (event.date - today_date).days
    days_label = (
        "Today" if days_away == 0
        else "Tomorrow" if days_away == 1
        else f"In {days_away} days"
    )
    st.markdown(
        f"""
        <div style="
            border-left: 4px solid {colour};
            background: rgba(255,255,255,0.05);
            border-radius: 6px;
            padding: 10px 16px;
            margin-bottom: 10px;
        ">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-weight:bold; font-size:1.05em;">
                    {IMPACT_EMOJI.get(event.impact, '')} {event.description}
                </span>
                <span style="
                    background:{colour};
                    color:white;
                    border-radius:12px;
                    padding:2px 10px;
                    font-size:0.8em;
                    font-weight:bold;
                ">{event.impact}</span>
            </div>
            <div style="color:#aaa; margin-top:4px; font-size:0.9em;">
                📆 {event.date.strftime('%a, %d %b %Y')}
                &nbsp;&nbsp;|&nbsp;&nbsp;
                🕐 {days_label}
                &nbsp;&nbsp;|&nbsp;&nbsp;
                🏷️ {event.event_type}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.divider()

# ---------------------------------------------------------------------------
# Timeline grouped by date
# ---------------------------------------------------------------------------
st.subheader(f"Timeline — Next {days_ahead} Days")

if not filtered_events:
    st.info("No events match the selected filters.")
else:
    grouped: dict[datetime.date, list[Event]] = defaultdict(list)
    for ev in filtered_events:
        grouped[ev.date].append(ev)

    for date in sorted(grouped.keys()):
        day_events = grouped[date]
        date_str = date.strftime("%a, %d %b %Y")
        days_away_tl = (date - today_date).days
        label_sfx = " ← Today" if days_away_tl == 0 else ""

        st.markdown(f"**{date_str}{label_sfx}**")

        for ev in day_events:
            colour  = IMPACT_COLOUR.get(ev.impact, "#888888")
            emoji   = IMPACT_EMOJI.get(ev.impact, "⚪")
            badge   = (
                f'<span style="background:{colour}; color:white; border-radius:8px;'
                f' padding:1px 8px; font-size:0.75em; margin-left:6px;">'
                f'{ev.impact}</span>'
            )
            type_tag = (
                f'<span style="background:#333; color:#ccc; border-radius:8px;'
                f' padding:1px 8px; font-size:0.75em; margin-left:4px;">'
                f'{ev.event_type}</span>'
            )
            st.markdown(
                f"{emoji} {ev.description}{badge}{type_tag}",
                unsafe_allow_html=True,
            )
        st.markdown("---")

# ---------------------------------------------------------------------------
# Month Calendar View (expander)
# ---------------------------------------------------------------------------
with st.expander("📆 Month Calendar View"):
    now_ist_dt = now_ist()
    year_  = now_ist_dt.year
    month_ = now_ist_dt.month

    month_events = get_events_in_month(year_, month_)
    by_day: dict[int, list[Event]] = defaultdict(list)
    for ev in month_events:
        if not event_type_filter or ev.event_type in event_type_filter:
            by_day[ev.date.day].append(ev)

    cal = _calendar.monthcalendar(year_, month_)
    month_name = datetime.date(year_, month_, 1).strftime("%B %Y")
    st.markdown(f"### {month_name}")

    header_row = "| Mo | Tu | We | Th | Fr | Sa | Su |"
    sep_row    = "|:--:|:--:|:--:|:--:|:--:|:--:|:--:|"
    rows_md    = [header_row, sep_row]

    for week in cal:
        cells = []
        for day in week:
            if day == 0:
                cells.append("   ")
            else:
                day_evs = by_day.get(day, [])
                if day_evs:
                    max_impact = (
                        "HIGH" if any(e.impact == "HIGH" for e in day_evs)
                        else "MEDIUM" if any(e.impact == "MEDIUM" for e in day_evs)
                        else "LOW"
                    )
                    em = IMPACT_EMOJI.get(max_impact, "⚪")
                    cells.append(f"**{day}**{em}")
                else:
                    cells.append(str(day))
        rows_md.append("| " + " | ".join(cells) + " |")

    st.markdown("\n".join(rows_md))
    st.caption("🔴 HIGH  🟠 MEDIUM  ⚪ LOW impact event on that date.")

st.divider()
st.caption("Calendar data is hardcoded — works offline. Dates are in IST.")
