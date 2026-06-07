"""
Watchlist — user-configurable list of instruments with live price fetching.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

from data.upstox_client import UpstoxClient
from store.local_store import load, save

_STORE_KEY = "watchlist"


@dataclass
class WatchlistItem:
    symbol: str
    instrument_key: str
    display_name: str


DEFAULT_WATCHLIST: list[WatchlistItem] = [
    WatchlistItem("NIFTY",     "NSE_INDEX|Nifty 50",         "Nifty 50"),
    WatchlistItem("BANKNIFTY", "NSE_INDEX|Nifty Bank",       "Bank Nifty"),
    WatchlistItem("VIX",       "NSE_INDEX|India VIX",        "India VIX"),
    WatchlistItem("FINNIFTY",  "NSE_INDEX|Nifty Fin Service", "Fin Nifty"),
]


def load_watchlist() -> list[WatchlistItem]:
    raw: list[dict] = load(_STORE_KEY, [])
    if not raw:
        return list(DEFAULT_WATCHLIST)
    return [WatchlistItem(**item) for item in raw]


def save_watchlist(items: list[WatchlistItem]) -> None:
    save(_STORE_KEY, [asdict(i) for i in items])


def add_to_watchlist(item: WatchlistItem) -> None:
    items = load_watchlist()
    symbols = {i.symbol for i in items}
    if item.symbol not in symbols:
        items.append(item)
        save_watchlist(items)


def remove_from_watchlist(symbol: str) -> None:
    items = load_watchlist()
    items = [i for i in items if i.symbol != symbol]
    save_watchlist(items)


def fetch_prices(
    client: Optional[UpstoxClient],
    items: list[WatchlistItem],
) -> list[dict]:
    _SAMPLE_PRICES: dict[str, tuple[float, float]] = {
        "NIFTY":     (24350.5, 0.45),
        "BANKNIFTY": (52100.2, -0.31),
        "VIX":       (14.5,    2.11),
        "FINNIFTY":  (23800.0, 0.62),
    }

    if client is None:
        results: list[dict] = []
        for item in items:
            ltp, chg = _SAMPLE_PRICES.get(item.symbol, (1000.0, 0.0))
            results.append(
                {
                    "symbol": item.symbol,
                    "display_name": item.display_name,
                    "ltp": ltp,
                    "change_pct": chg,
                }
            )
        return results

    try:
        keys = [i.instrument_key for i in items]
        quotes = client.get_market_quotes(keys)
        results = []
        for item in items:
            data = quotes.get(item.instrument_key, {})
            if not data:
                for k, v in quotes.items():
                    if item.symbol.lower() in k.lower():
                        data = v
                        break
            ltp = float(data.get("last_price", 0))
            close = float(data.get("close_price", 1) or 1)
            change_pct = (ltp / close - 1) * 100 if close else 0.0
            results.append(
                {
                    "symbol": item.symbol,
                    "display_name": item.display_name,
                    "ltp": ltp,
                    "change_pct": change_pct,
                }
            )
        return results
    except Exception:
        return fetch_prices(None, items)
