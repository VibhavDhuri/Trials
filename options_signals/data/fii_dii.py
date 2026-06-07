"""
NSE participant-wise F&O open interest data (FII/DII/Pro/Client).
Published daily by NSE CCIL. Requires NSE session cookie.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, asdict
from io import StringIO
from typing import Optional

import pandas as pd
import requests

from store.local_store import load, save


@dataclass
class FIIData:
    date: str
    fii_net_futures: float
    fii_net_calls: float
    fii_net_puts: float
    dii_net_futures: float
    pro_net_futures: float
    source: str


_SAMPLE = FIIData(
    date="sample",
    fii_net_futures=12500,
    fii_net_calls=-3200,
    fii_net_puts=5800,
    dii_net_futures=-2100,
    pro_net_futures=-8400,
    source="sample",
)

_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.nseindia.com/",
    "Accept-Language": "en-US,en;q=0.9",
}


def _fetch_participant_oi(date: datetime.date) -> Optional[pd.DataFrame]:
    date_str = date.strftime("%d%b%Y").upper()
    url = f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{date_str}.csv"
    session = requests.Session()
    try:
        session.get("https://www.nseindia.com/", headers=_NSE_HEADERS, timeout=10)
        resp = session.get(url, headers=_NSE_HEADERS, timeout=15)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        df.columns = [str(c).strip() for c in df.columns]
        return df
    except Exception:
        return None


def _parse_row(df: pd.DataFrame, client_type: str) -> Optional[pd.Series]:
    first_col = df.columns[0]
    mask = df[first_col].astype(str).str.contains(client_type, case=False, na=False)
    matches = df[mask]
    if matches.empty:
        return None
    return matches.iloc[0]


def _safe_float(val: object) -> float:
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def get_fii_data(days_back: int = 1) -> FIIData:
    today = datetime.date.today()
    for offset in range(days_back + 2):
        target_date = today - datetime.timedelta(days=offset)
        cache_key = f"fii_{target_date.isoformat()}"
        cached = load(cache_key, None)
        if cached is not None:
            return FIIData(**cached)

        df = _fetch_participant_oi(target_date)
        if df is None:
            continue

        fii_row = _parse_row(df, "FII")
        dii_row = _parse_row(df, "DII")
        pro_row = _parse_row(df, "Pro")

        if fii_row is None:
            continue

        def _net(row: Optional[pd.Series], long_idx: int, short_idx: int) -> float:
            if row is None:
                return 0.0
            try:
                return _safe_float(row.iloc[long_idx]) - _safe_float(row.iloc[short_idx])
            except IndexError:
                return 0.0

        fii_net_futures = _net(fii_row, 1, 2)
        fii_net_calls   = _net(fii_row, 3, 4)
        fii_net_puts    = _net(fii_row, 5, 6)
        dii_net_futures = _net(dii_row, 1, 2)
        pro_net_futures = _net(pro_row, 1, 2)

        result = FIIData(
            date=target_date.isoformat(),
            fii_net_futures=fii_net_futures,
            fii_net_calls=fii_net_calls,
            fii_net_puts=fii_net_puts,
            dii_net_futures=dii_net_futures,
            pro_net_futures=pro_net_futures,
            source="nse",
        )
        save(cache_key, asdict(result))
        return result

    return _SAMPLE


def interpret_fii(data: FIIData) -> str:
    parts: list[str] = []
    if data.fii_net_futures > 0:
        parts.append("FII net long futures: bullish posture")
    else:
        parts.append("FII net short futures: bearish posture")
    if data.fii_net_puts > 0:
        parts.append("net long puts: hedging downside")
    elif data.fii_net_calls > 0:
        parts.append("net long calls: bullish options bias")
    else:
        parts.append("net short options: premium collection mode")
    return "; ".join(parts) + "."
