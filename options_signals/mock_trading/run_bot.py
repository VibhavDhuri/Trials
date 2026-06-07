"""
Autonomous paper-trading bot.

Run as a standalone process:
    python mock_trading/run_bot.py [--index NIFTY] [--offline] [--interval 300]

The bot:
  1. Every `interval` seconds during market hours, fetches options data
  2. Generates signals for the nearest 2 expiries
  3. Places paper trades on HIGH-confidence signals (max 1 per expiry per direction)
  4. Exits positions when stop-loss or expiry conditions are met
  5. Logs all activity to data_store/paper_trades.json

Stop the bot with Ctrl+C. Start/stop from the Streamlit Mock Trading page.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import INDICES, RISK_FREE_RATE
from auth.upstox_auth import get_stored_token, validate_token
from data.upstox_client import UpstoxClient
from data.market_data import MarketDataFetcher
from data.options_chain import OptionsChainFetcher
from analysis.iv_analysis import analyze_iv_environment
from analysis.oi_analysis import analyze_oi
from analysis.signals import generate_signals, Direction, Confidence
from analysis.greeks import bs_price
from mock_trading.paper_engine import (
    place_bot_trade, check_and_exit_positions, get_trade_log
)
from utils.helpers import is_market_open, now_ist, days_to_expiry
from store.local_store import save

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("paper_bot")

_RUNNING = True
_MAX_OPEN_PER_EXPIRY = 1   # max 1 bot position per expiry × direction


def _signal_handler(sig, frame):
    global _RUNNING
    log.info("Stopping bot...")
    _RUNNING = False


signal.signal(signal.SIGINT,  _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def _already_open(symbol: str, expiry: str, direction: str) -> bool:
    """True if we already have an open BOT position for this expiry + direction."""
    from positions.tracker import get_open_positions
    opt_type = "CE" if direction == "BULLISH" else "PE"
    return any(
        p.symbol == symbol and p.expiry == expiry and p.opt_type == opt_type and p.source == "BOT"
        for p in get_open_positions()
    )


def _current_prices(chain_df) -> dict:
    """Build {(symbol, expiry, strike, opt_type): ltp} from chain DataFrame."""
    if chain_df.empty:
        return {}
    return {
        (r["spot"], r["expiry"], r["strike"], r["opt_type"]): r["ltp"]
        for _, r in chain_df.iterrows()
        if "spot" in r and r["ltp"] > 0
    }


def run_once(symbol: str, mdf: MarketDataFetcher, ocf: OptionsChainFetcher) -> None:
    """One scan-and-trade cycle."""
    spot_data = mdf.get_spot(symbol)
    spot = float(spot_data.get("last_price", 0))
    if spot <= 0:
        log.warning("No spot price for %s — skipping", symbol)
        return

    iv_52wh, iv_52wl = mdf.get_historical_iv_range(symbol)
    expiries = ocf.get_expiries(symbol)[:2]

    all_prices = {}
    for exp in expiries:
        chain_df = ocf.get_chain_df(symbol, exp, spot)
        if chain_df.empty:
            continue

        # Build price lookup for stop-loss checking
        for _, row in chain_df.iterrows():
            all_prices[(symbol, row["expiry"], row["strike"], row["opt_type"])] = row["ltp"]

        iv_env  = analyze_iv_environment(chain_df, spot, iv_52wh, iv_52wl)
        oi_res  = analyze_oi(chain_df, spot)
        signals = generate_signals(chain_df, iv_env, oi_res, spot, exp)

        for sig in signals:
            if sig.confidence != Confidence.HIGH:
                continue
            if sig.direction in (Direction.MIXED, Direction.NEUTRAL):
                continue

            direction = sig.direction.value
            if _already_open(symbol, exp, direction):
                log.info("Already have open %s %s position — skipping", symbol, direction)
                continue

            opt_type = "CE" if direction == "BULLISH" else "PE"
            cfg      = INDICES[symbol]
            gap      = cfg.strike_gap

            # Find ATM option rows for this type
            side_df = chain_df[chain_df["opt_type"] == opt_type].copy()
            if side_df.empty:
                continue
            side_df = side_df.sort_values("atm_distance")

            atm_row = side_df.iloc[0]
            atm_strike = float(atm_row["strike"])
            atm_ltp    = float(atm_row["ltp"])
            if atm_ltp <= 0:
                continue

            # OTM strike one gap away from ATM (short leg of spread)
            otm_strike = atm_strike + gap if direction == "BULLISH" else atm_strike - gap
            otm_rows = side_df[abs(side_df["strike"] - otm_strike) < gap * 0.6]

            if not otm_rows.empty:
                # Place a vertical spread: buy ATM, sell OTM
                otm_ltp = float(otm_rows.iloc[0]["ltp"])
                strategy_label = (
                    "Bull Call Spread" if direction == "BULLISH" else "Bear Put Spread"
                )
                place_bot_trade(
                    symbol=symbol, expiry=exp,
                    strike=atm_strike, opt_type=opt_type,
                    action="BUY", ltp=atm_ltp,
                    strategy_tag=strategy_label,
                )
                if otm_ltp > 0:
                    place_bot_trade(
                        symbol=symbol, expiry=exp,
                        strike=otm_strike, opt_type=opt_type,
                        action="SELL", ltp=otm_ltp,
                        strategy_tag=strategy_label,
                    )
                log.info(
                    "BOT SPREAD: %s %s BUY %d@%.2f / SELL %d@%.2f  net=%.2f  exp=%s",
                    symbol, opt_type, int(atm_strike), atm_ltp,
                    int(otm_strike), otm_ltp, atm_ltp - otm_ltp, exp,
                )
            else:
                # No OTM available — fall back to naked long option
                place_bot_trade(
                    symbol=symbol, expiry=exp,
                    strike=atm_strike, opt_type=opt_type,
                    action="BUY", ltp=atm_ltp,
                    strategy_tag=sig.strategy,
                )
                log.info(
                    "BOT TRADE: %s %s %s@%.2f exp=%s strategy=%s",
                    symbol, opt_type, int(atm_strike), atm_ltp, exp, sig.strategy,
                )

    # Check exits
    exits = check_and_exit_positions(all_prices)
    for ex in exits:
        log.info("BOT EXIT: %s %s@%.2f pnl=%.2f", ex["symbol"], ex["strike"], ex["exit_price"], ex["pnl_gross"])

    # Write bot status
    save("bot_status", {
        "last_run": now_ist().isoformat(),
        "symbol":   symbol,
        "spot":     spot,
        "running":  True,
    })


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper Trading Bot")
    parser.add_argument("--index",    default="NIFTY", choices=list(INDICES.keys()))
    parser.add_argument("--offline",  action="store_true")
    parser.add_argument("--interval", type=int, default=300, help="Seconds between scans (default 300)")
    args = parser.parse_args()

    symbol = args.index
    log.info("Paper bot starting for %s (interval=%ds, offline=%s)", symbol, args.interval, args.offline)

    client = None
    if not args.offline:
        token = get_stored_token()
        if token and validate_token(token):
            client = UpstoxClient(token)
            log.info("Upstox client: LIVE")
        else:
            log.warning("No valid token — running in offline (sample data) mode")

    mdf = MarketDataFetcher(client, offline=(client is None))
    ocf = OptionsChainFetcher(client, offline=(client is None))

    while _RUNNING:
        if not is_market_open() and not args.offline:
            log.info("Market closed — sleeping 60s")
            time.sleep(60)
            continue

        try:
            run_once(symbol, mdf, ocf)
        except Exception as e:
            log.error("Error in scan cycle: %s", e)

        log.info("Sleeping %ds until next scan...", args.interval)
        for _ in range(args.interval):
            if not _RUNNING:
                break
            time.sleep(1)

    save("bot_status", {"last_run": now_ist().isoformat(), "running": False})
    log.info("Bot stopped.")


if __name__ == "__main__":
    main()
