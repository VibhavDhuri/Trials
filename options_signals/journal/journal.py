"""
Trade journal — per-trade notes, tags, conviction, and mood tracking.
"""
from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional

from store.local_store import load, save

COMMON_TAGS = [
    "trend-follow",
    "mean-revert",
    "event-trade",
    "hedge",
    "scalp",
    "overnight",
    "expiry-day",
    "breakout",
    "range-bound",
]

MOOD_OPTIONS = ["DISCIPLINED", "CONFIDENT", "UNCERTAIN", "FOMO", "REVENGE"]

_STORE_KEY = "journal"


@dataclass
class JournalEntry:
    id: str
    position_id: str
    symbol: str
    date: str
    tags: list[str]
    notes: str
    conviction: int
    mood: str
    pnl_at_close: Optional[float]
    created_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_entries() -> list[JournalEntry]:
    raw: list[dict] = load(_STORE_KEY, [])
    entries: list[JournalEntry] = []
    for item in raw:
        item.setdefault("pnl_at_close", None)
        entries.append(JournalEntry(**item))
    return entries


def save_entries(entries: list[JournalEntry]) -> None:
    save(_STORE_KEY, [asdict(e) for e in entries])


def add_entry(
    position_id: str,
    symbol: str,
    date: str,
    tags: list[str],
    notes: str,
    conviction: int,
    mood: str,
    pnl_at_close: Optional[float] = None,
) -> JournalEntry:
    entry = JournalEntry(
        id=str(uuid.uuid4()),
        position_id=position_id,
        symbol=symbol,
        date=date,
        tags=tags,
        notes=notes,
        conviction=conviction,
        mood=mood,
        pnl_at_close=pnl_at_close,
        created_at=_now_iso(),
    )
    entries = load_entries()
    entries.append(entry)
    save_entries(entries)
    return entry


def update_entry(entry_id: str, **kwargs: object) -> Optional[JournalEntry]:
    entries = load_entries()
    for i, e in enumerate(entries):
        if e.id == entry_id:
            updated = asdict(e)
            updated.update({k: v for k, v in kwargs.items() if k in updated})
            entries[i] = JournalEntry(**updated)
            save_entries(entries)
            return entries[i]
    return None


def delete_entry(entry_id: str) -> bool:
    entries = load_entries()
    new_entries = [e for e in entries if e.id != entry_id]
    if len(new_entries) == len(entries):
        return False
    save_entries(new_entries)
    return True


def get_entries_for_position(position_id: str) -> list[JournalEntry]:
    return [e for e in load_entries() if e.position_id == position_id]


def get_all_entries() -> list[JournalEntry]:
    entries = load_entries()
    entries.sort(key=lambda e: e.created_at, reverse=True)
    return entries


def search_entries(query: str) -> list[JournalEntry]:
    q = query.lower()
    results: list[JournalEntry] = []
    for e in load_entries():
        if q in e.notes.lower() or any(q in tag.lower() for tag in e.tags):
            results.append(e)
    return results


def insights(entries: list[JournalEntry]) -> dict:
    scored = [e for e in entries if e.pnl_at_close is not None]
    winners = [e for e in scored if e.pnl_at_close > 0]  # type: ignore[operator]
    losers  = [e for e in scored if e.pnl_at_close <= 0]  # type: ignore[operator]

    avg_conviction_winners = (
        sum(e.conviction for e in winners) / len(winners) if winners else 0.0
    )
    avg_conviction_losers = (
        sum(e.conviction for e in losers) / len(losers) if losers else 0.0
    )

    winner_tags: list[str] = []
    for e in winners:
        winner_tags.extend(e.tags)
    loser_tags: list[str] = []
    for e in losers:
        loser_tags.extend(e.tags)

    top_tags_winning = [tag for tag, _ in Counter(winner_tags).most_common(5)]
    top_tags_losing  = [tag for tag, _ in Counter(loser_tags).most_common(5)]

    return {
        "avg_conviction_winners": avg_conviction_winners,
        "avg_conviction_losers": avg_conviction_losers,
        "top_tags_winning": top_tags_winning,
        "top_tags_losing": top_tags_losing,
    }
