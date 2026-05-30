"""
NSE F&O Bhav Copy downloader + nselib fallback.

NSE publishes end-of-day settlement data for all F&O contracts as daily CSV files.
These contain ACTUAL historical options prices — not Black-Scholes estimates.

Two URL formats (NSE changed the schema on 8 July 2024):

OLD format (before 8 Jul 2024):
  https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{YYYY}/{MON}/fo{DD}{MON}{YYYY}bhav.csv.zip
  Columns: INSTRUMENT, SYMBOL, EXPIRY_DT, STRIKE_PR, OPTION_TYP, OPEN, HIGH, LOW, CLOSE,
           SETTLE_PR, CONTRACTS, VAL_INLAKH, OPEN_INT, CHG_IN_OI, TIMESTAMP

NEW UDiFF format (8 Jul 2024 onwards):
  https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{YYYYMMDD}_F_0000.csv.zip
  Columns: BizDt, TckrSymb, XpryDt, StrkPric, OptnTp, OpnPric, HghPric, LwPric,
           ClsPric, LastPric, SttlmPric, OpnIntrst, ChngInOpnIntrst, TtlTrfVal, etc.

NSE requires a live browser session cookie to avoid 403s.
We establish the session by hitting nseindia.com first.

Fallback: nselib (`pip install nselib`) — fetches NSE option price/volume without
         session management. Recommended if bhav copy downloads fail.

Optional dependency: jugaad-data (`pip install jugaad-data`) — also fetches bhav copy
                     but uncertain if fully updated for post-July 2024 UDiFF format.
"""
from __future__ import annotations

import datetime
import io
import logging
import time
import zipfile
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

log = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent.parent / "data_store" / "bhav_cache"
_SESSION: Optional[requests.Session] = None

# NSE UDiFF bhav (post July 2024)
_NEW_URL = (
    "https://nsearchives.nseindia.com/content/fo/"
    "BhavCopy_NSE_FO_0_0_0_{date}_F_0000.csv.zip"
)
# NSE legacy bhav (pre July 2024)
_OLD_URL = (
    "https://nsearchives.nseindia.com/content/historical/DERIVATIVES"
    "/{year}/{mon}/fo{dd}{mon}{year}bhav.csv.zip"
)

_CUTOFF_NEW = datetime.date(2024, 7, 8)   # new UDiFF format starts here

_INDEX_SYMBOLS = {
    "NIFTY": "NIFTY", "BANKNIFTY": "BANKNIFTY",
    "SENSEX": "SENSEX", "FINNIFTY": "FINNIFTY", "MIDCPNIFTY": "MIDCPNIFTY",
}


def _get_session() -> requests.Session:
    """Return a requests.Session with NSE cookies (established lazily)."""
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.nseindia.com/",
        })
        try:
            _SESSION.get("https://www.nseindia.com", timeout=10)
            time.sleep(0.5)
        except Exception:
            pass
    return _SESSION


def _cache_path(date: datetime.date) -> Path:
    return _CACHE_DIR / f"fo_bhav_{date.strftime('%Y%m%d')}.parquet"


def _url_for_date(date: datetime.date) -> str:
    if date >= _CUTOFF_NEW:
        return _NEW_URL.format(date=date.strftime("%Y%m%d"))
    mon = date.strftime("%b").upper()
    dd  = date.strftime("%d")
    yr  = date.strftime("%Y")
    return _OLD_URL.format(year=yr, mon=mon, dd=dd)


def _parse_old(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise the pre-July-2024 column names."""
    df.columns = [c.strip() for c in df.columns]
    df = df[df["INSTRUMENT"].isin(["OPTIDX", "OPTSTK"])].copy()
    return df.rename(columns={
        "SYMBOL":    "symbol", "EXPIRY_DT": "expiry",
        "STRIKE_PR": "strike", "OPTION_TYP": "opt_type",
        "OPEN": "open", "HIGH": "high", "LOW": "low", "CLOSE": "close",
        "SETTLE_PR": "settle", "CONTRACTS": "contracts",
        "OPEN_INT": "oi", "CHG_IN_OI": "oi_chg",
    })


def _parse_new(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise the post-July-2024 UDiFF column names (NSE Circular 62424)."""
    df.columns = [c.strip() for c in df.columns]
    # Filter to options rows — FinInstrmTp column uses "OPT" prefix in UDiFF
    if "FinInstrmTp" in df.columns:
        df = df[df["FinInstrmTp"].isin(["OPTIDX", "OPTSTK", "OPT"])].copy()
    return df.rename(columns={
        "TckrSymb":          "symbol",
        "XpryDt":            "expiry",
        "StrkPric":          "strike",
        "OptnTp":            "opt_type",   # CE / PE
        "OpnPric":           "open",
        "HighPric":          "high",       # note: HighPric not HghPric
        "LowPric":           "low",        # note: LowPric not LwPric
        "ClsgPric":          "close",      # note: ClsgPric not ClsPric
        "LastPric":          "last",
        "SttlmPric":         "settle",
        "TtlTradgVol":       "contracts",  # total trading volume
        "OpnIntrst":         "oi",
        "ChngInOpnIntrst":   "oi_chg",
        "TtlTrfVal":         "trade_value",
        "TradDt":            "trade_date",
    })


def _download_bhav(date: datetime.date) -> Optional[pd.DataFrame]:
    url = _url_for_date(date)
    try:
        resp = _get_session().get(url, timeout=20)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning("Bhav download failed for %s: %s", date, e)
        return None

    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            with z.open(z.namelist()[0]) as f:
                raw = pd.read_csv(f)
    except Exception as e:
        log.warning("Bhav parse failed for %s: %s", date, e)
        return None

    parse = _parse_new if date >= _CUTOFF_NEW else _parse_old
    df = parse(raw)
    if df.empty:
        return None

    # Normalise types
    df["date"]   = date
    df["strike"] = pd.to_numeric(df.get("strike", 0), errors="coerce")
    df["close"]  = pd.to_numeric(df.get("close",  df.get("settle", 0)), errors="coerce")
    df["settle"] = pd.to_numeric(df.get("settle", df.get("close",  0)), errors="coerce")
    df["oi"]     = pd.to_numeric(df.get("oi", 0), errors="coerce").fillna(0)
    # Expiry → YYYY-MM-DD
    try:
        df["expiry"] = pd.to_datetime(df["expiry"], dayfirst=True).dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return df[["date","symbol","expiry","strike","opt_type","open","high","low","close","settle","oi","oi_chg"]].copy()


def _load_or_download(date: datetime.date, delay: float = 1.5) -> Optional[pd.DataFrame]:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp = _cache_path(date)
    if cp.exists():
        try:
            return pd.read_parquet(cp)
        except Exception:
            cp.unlink(missing_ok=True)

    df = _download_bhav(date)
    if df is not None and not df.empty:
        df.to_parquet(cp, index=False)
    time.sleep(delay if df is not None else 0.3)
    return df


def _nselib_fallback(
    symbol: str,
    start: datetime.date,
    end: datetime.date,
    opt_type: Optional[str] = None,
) -> pd.DataFrame:
    """Use nselib to fetch historical option price/volume data (no session needed)."""
    try:
        from nselib import capital_market  # pip install nselib
        nse_sym = _INDEX_SYMBOLS.get(symbol, symbol)
        instrument = "OPTIDX" if symbol in _INDEX_SYMBOLS else "OPTSTK"
        frames = []
        for ot in (["CE", "PE"] if opt_type is None else [opt_type]):
            try:
                df = capital_market.option_price_volume_data(
                    symbol=nse_sym,
                    instrument=instrument,
                    option_type=ot,
                    from_date=start.strftime("%d-%m-%Y"),
                    to_date=end.strftime("%d-%m-%Y"),
                )
                if df is not None and not df.empty:
                    df["symbol"]   = nse_sym
                    df["opt_type"] = ot
                    frames.append(df)
            except Exception as e:
                log.debug("nselib %s %s: %s", nse_sym, ot, e)
        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames, ignore_index=True)
        # Normalise column names from nselib (columns vary by version — check dynamically)
        col_map = {c: c.lower() for c in out.columns}
        out = out.rename(columns=col_map)
        return out
    except ImportError:
        log.info("nselib not installed — run: pip install nselib")
        return pd.DataFrame()


def fetch_options_history(
    symbol: str,
    start_date: datetime.date,
    end_date: datetime.date,
    expiry: Optional[str] = None,
    opt_type: Optional[str] = None,
    use_nselib_fallback: bool = True,
) -> pd.DataFrame:
    """
    Fetch historical options EOD data for `symbol` between start_date and end_date.

    Tries NSE bhav copy first; falls back to nselib if bhav download fails.

    symbol    — 'NIFTY', 'BANKNIFTY', 'RELIANCE', etc.
    expiry    — optional filter, e.g. '2024-06-27'
    opt_type  — optional filter: 'CE' or 'PE'
    """
    nse_sym = _INDEX_SYMBOLS.get(symbol, symbol)
    frames = []
    bhav_ok = False

    current = start_date
    while current <= end_date:
        if current.weekday() < 5:  # weekdays only
            df = _load_or_download(current)
            if df is not None and not df.empty:
                bhav_ok = True
                sub = df[df["symbol"] == nse_sym]
                if expiry:
                    sub = sub[sub["expiry"] == expiry]
                if opt_type:
                    sub = sub[sub["opt_type"] == opt_type]
                if not sub.empty:
                    frames.append(sub)
        current += datetime.timedelta(days=1)

    if not bhav_ok and use_nselib_fallback:
        log.info("Bhav copy unavailable — trying nselib fallback")
        return _nselib_fallback(symbol, start_date, end_date, opt_type)

    return (
        pd.concat(frames, ignore_index=True)
        .sort_values(["date", "expiry", "strike", "opt_type"])
        if frames else pd.DataFrame()
    )


def is_available() -> bool:
    """Quick connectivity check to NSE archives."""
    try:
        r = _get_session().head(
            "https://nsearchives.nseindia.com/", timeout=5
        )
        return r.status_code < 500
    except Exception:
        return False
