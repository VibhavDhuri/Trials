from dataclasses import dataclass
from typing import Dict
import pytz

IST = pytz.timezone("Asia/Kolkata")

MARKET_OPEN_HOUR, MARKET_OPEN_MIN = 9, 15
MARKET_CLOSE_HOUR, MARKET_CLOSE_MIN = 15, 30

RISK_FREE_RATE = 0.065  # ~6.5% Indian 10-year G-Sec, used for BS pricing

# NSE 2025 trading holidays (dates when expiry shifts to previous trading day)
NSE_HOLIDAYS_2025 = {
    "2025-01-26",  # Republic Day
    "2025-03-14",  # Holi
    "2025-03-31",  # Id ul Fitr
    "2025-04-10",  # Ram Navami
    "2025-04-14",  # Ambedkar Jayanti
    "2025-04-18",  # Good Friday
    "2025-05-01",  # Maharashtra Day
    "2025-08-15",  # Independence Day
    "2025-08-27",  # Ganesh Chaturthi
    "2025-10-02",  # Gandhi Jayanti
    "2025-10-21",  # Diwali Balipratipada
    "2025-11-05",  # Gurunanak Jayanti
    "2025-12-25",  # Christmas
}

BSE_HOLIDAYS_2025 = NSE_HOLIDAYS_2025  # mostly the same for BSE

UPSTOX_API_BASE = "https://api.upstox.com/v2"
UPSTOX_AUTH_DIALOG = "https://api.upstox.com/v2/login/authorization/dialog"
UPSTOX_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"

# Upstox instrument keys
INSTRUMENT_KEYS = {
    "NIFTY":      "NSE_INDEX|Nifty 50",
    "BANKNIFTY":  "NSE_INDEX|Nifty Bank",
    "FINNIFTY":   "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
    "SENSEX":     "BSE_INDEX|SENSEX",
}


@dataclass
class IndexConfig:
    display_name: str
    instrument_key: str
    lot_size: int
    strike_gap: int
    expiry_weekday: int   # 0=Mon,1=Tue,2=Wed,3=Thu,4=Fri
    exchange: str
    holiday_set: frozenset


INDICES: Dict[str, IndexConfig] = {
    "NIFTY": IndexConfig(
        display_name="Nifty 50",
        instrument_key="NSE_INDEX|Nifty 50",
        lot_size=75,
        strike_gap=50,
        expiry_weekday=3,   # Thursday
        exchange="NSE",
        holiday_set=frozenset(NSE_HOLIDAYS_2025),
    ),
    "BANKNIFTY": IndexConfig(
        display_name="Bank Nifty",
        instrument_key="NSE_INDEX|Nifty Bank",
        lot_size=15,
        strike_gap=100,
        expiry_weekday=2,   # Wednesday
        exchange="NSE",
        holiday_set=frozenset(NSE_HOLIDAYS_2025),
    ),
    "SENSEX": IndexConfig(
        display_name="Sensex",
        instrument_key="BSE_INDEX|SENSEX",
        lot_size=20,
        strike_gap=100,
        expiry_weekday=4,   # Friday
        exchange="BSE",
        holiday_set=frozenset(BSE_HOLIDAYS_2025),
    ),
    "FINNIFTY": IndexConfig(
        display_name="Fin Nifty",
        instrument_key="NSE_INDEX|Nifty Fin Service",
        lot_size=65,
        strike_gap=50,
        expiry_weekday=1,   # Tuesday
        exchange="NSE",
        holiday_set=frozenset(NSE_HOLIDAYS_2025),
    ),
    "MIDCPNIFTY": IndexConfig(
        display_name="MidCap Nifty",
        instrument_key="NSE_INDEX|NIFTY MID SELECT",
        lot_size=50,
        strike_gap=25,
        expiry_weekday=0,   # Monday
        exchange="NSE",
        holiday_set=frozenset(NSE_HOLIDAYS_2025),
    ),
}
