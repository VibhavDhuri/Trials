"""
Auto-exit watcher — standalone process that monitors open positions and fires auto-exit rules.
Usage: python positions/run_watcher.py [--offline] [--interval 60]
"""
from __future__ import annotations

import argparse
import datetime
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from positions.auto_exit import check_exits, mark_triggered, get_active_rules
from positions.tracker import get_open_positions, close_position


def _iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_ltp_map_offline(positions: list) -> dict:
    ltp_map: dict = {}
    for pos in positions:
        key = (pos.symbol, pos.expiry, pos.strike, pos.opt_type)
        simulated_ltp = pos.entry_price * (1 + random.gauss(0, 0.03))
        ltp_map[key] = max(simulated_ltp, 0.05)
    return ltp_map


def _build_ltp_map_live(positions: list, index: str) -> dict:
    ltp_map: dict = {}
    try:
        from store.local_store import load as _load
        token_data = _load("auth_token", {})
        access_token = token_data.get("access_token", "")
        if not access_token:
            return _build_ltp_map_offline(positions)

        from data.upstox_client import UpstoxClient
        from config import INDICES

        client = UpstoxClient(access_token)
        cfg = INDICES.get(index)
        if cfg is None:
            return _build_ltp_map_offline(positions)

        expiry_set: set[str] = {pos.expiry for pos in positions}
        for expiry in expiry_set:
            try:
                chain = client.get_option_chain(cfg.instrument_key, expiry)
                if not chain:
                    continue
                for row in chain:
                    strike = row.get("strike_price") or row.get("strike")
                    for opt_type in ("CE", "PE"):
                        ltp_key = row.get(f"{opt_type.lower()}_ltp") or row.get("last_price")
                        if strike and ltp_key:
                            ltp_map[(index, expiry, float(strike), opt_type)] = float(ltp_key)
            except Exception:
                pass
    except Exception:
        return _build_ltp_map_offline(positions)
    return ltp_map


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-exit watcher for open positions")
    parser.add_argument("--offline",  action="store_true", help="Simulate LTP offline")
    parser.add_argument("--interval", type=int, default=60, help="Check interval in seconds")
    parser.add_argument("--index",    type=str, default="NIFTY", help="Index symbol")
    args = parser.parse_args()

    print(f"{_iso_now()} Watcher started — offline={args.offline}, interval={args.interval}s, index={args.index}")

    while True:
        try:
            positions = get_open_positions()
            active_rules = get_active_rules()

            if not positions or not active_rules:
                print(f"{_iso_now()} No open positions or active rules — sleeping")
                time.sleep(args.interval)
                continue

            if args.offline:
                ltp_map = _build_ltp_map_offline(positions)
            else:
                ltp_map = _build_ltp_map_live(positions, args.index)

            triggered = check_exits(positions, ltp_map)

            for rule, pos, exit_ltp in triggered:
                closed = close_position(pos.id, exit_ltp)
                mark_triggered(rule.id)
                if closed:
                    print(
                        f"{_iso_now()} TRIGGERED rule={rule.id} pos={pos.id} "
                        f"symbol={pos.symbol} strike={pos.strike} {pos.opt_type} "
                        f"exit_ltp={exit_ltp:.2f}"
                    )
                else:
                    print(
                        f"{_iso_now()} WARNING: could not close pos={pos.id} (already closed?)"
                    )

        except Exception as exc:
            print(f"{_iso_now()} ERROR: {exc}")

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
