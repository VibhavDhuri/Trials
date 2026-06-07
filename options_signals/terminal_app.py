"""
Rich terminal dashboard — quick live monitoring.
Usage: python terminal_app.py [--index NIFTY] [--expiry 2025-06-26] [--offline]
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import List, Optional

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import os
sys.path.insert(0, os.path.dirname(__file__))

from auth.upstox_auth import get_stored_token, validate_token, AUTH_INSTRUCTIONS
from config import INDICES, IST
from data.market_data import MarketDataFetcher
from data.options_chain import OptionsChainFetcher
from data.upstox_client import UpstoxClient
from analysis.iv_analysis import analyze_iv_environment
from analysis.oi_analysis import analyze_oi
from analysis.signals import Signal, Direction, Confidence, generate_signals
from utils.helpers import is_market_open, market_status, now_ist, format_inr, dte_label

console = Console()

_DIR_STYLES = {
    Direction.BULLISH:     "bold green",
    Direction.BEARISH:     "bold red",
    Direction.NEUTRAL:     "bold yellow",
    Direction.RANGE_BOUND: "bold cyan",
    Direction.MIXED:       "bold magenta",
}
_CONF_STYLES = {
    Confidence.HIGH:   "green",
    Confidence.MEDIUM: "yellow",
    Confidence.LOW:    "dim",
}
_REFRESH_SECS = 30


def _header(symbol: str, spot_data: dict, offline: bool) -> Panel:
    cfg = INDICES[symbol]
    price = spot_data.get("last_price", 0)
    ohlc = spot_data.get("ohlc", {})
    chg = spot_data.get("net_change", 0)
    chg_col = "green" if chg >= 0 else "red"
    ms = market_status()
    ts = now_ist().strftime("%H:%M:%S IST")
    mode = "[yellow]OFFLINE[/]" if offline else "[green]LIVE[/]"

    body = (
        f"[bold white]{price:,.2f}[/]  [{chg_col}]{chg:+.2f}%[/]  |  {ms}  {ts}  {mode}\n"
        f"O:{ohlc.get('open',0):,.0f}  H:{ohlc.get('high',0):,.0f}  "
        f"L:{ohlc.get('low',0):,.0f}  PC:{ohlc.get('close',0):,.0f}  "
        f"Lot: {cfg.lot_size}"
    )
    return Panel(body, title=f"[bold]{cfg.display_name}[/]", border_style="blue")


def _signals_table(signals: List[Signal]) -> Table:
    t = Table(title="Top Signals", box=box.SIMPLE_HEAVY, highlight=True, expand=True)
    t.add_column("Expiry / DTE", style="cyan", no_wrap=True, width=16)
    t.add_column("Direction", justify="center", width=12)
    t.add_column("Conf", justify="center", width=8)
    t.add_column("Strategy", min_width=20)
    t.add_column("IV Rank", justify="right", width=10)
    t.add_column("PCR", justify="right", width=7)
    t.add_column("Max Pain", justify="right", width=10)
    t.add_column("1-SD Move", justify="right", width=16)

    sorted_sigs = sorted(
        signals,
        key=lambda s: ({"HIGH": 0, "MEDIUM": 1, "LOW": 2}[s.confidence.value], s.expiry_date),
    )[:5]

    for sig in sorted_sigs:
        t.add_row(
            f"{sig.expiry_date}\n[dim]{dte_label(sig.expiry_date)}[/]",
            Text(sig.direction.value, style=_DIR_STYLES.get(sig.direction, "")),
            Text(sig.confidence.value, style=_CONF_STYLES.get(sig.confidence, "")),
            sig.strategy,
            f"{sig.iv_rank:.0f}/100",
            f"{sig.pcr_oi:.2f}",
            f"{sig.max_pain:,.0f}",
            f"±{sig.expected_move_pts:.0f}pts ({sig.expected_move_pct:.1f}%)",
        )

    if not sorted_sigs:
        t.add_row("[dim]—[/]", "[dim]—[/]", "[dim]—[/]", "[dim]No signals[/]",
                  "[dim]—[/]", "[dim]—[/]", "[dim]—[/]", "[dim]—[/]")
    return t


def _chain_table(chain_df, spot: float, max_pain: float) -> Table:
    t = Table(title="ATM Options Chain (±5 strikes)", box=box.SIMPLE, highlight=True, expand=True)
    for col in ("Strike", "CE Bid", "CE LTP", "CE Ask", "CE IV%", "CE OI",
                "CE Δ", "CE Θ", "│",
                "PE Θ", "PE Δ", "PE OI", "PE IV%", "PE Bid", "PE LTP", "PE Ask"):
        justify = "center" if col == "│" else "right"
        t.add_column(col, justify=justify, no_wrap=True)

    if chain_df.empty:
        return t

    atm_dist = (chain_df["strike"] - spot).abs()
    nearby_strikes = sorted(chain_df.loc[atm_dist.nsmallest(22).index, "strike"].unique())[:11]

    # Compute strike gap from CE strikes only (avoids mixed CE/PE interleave)
    ce_strikes = sorted(chain_df[chain_df["opt_type"] == "CE"]["strike"].unique())
    if len(ce_strikes) >= 2:
        gaps = [ce_strikes[i + 1] - ce_strikes[i] for i in range(len(ce_strikes) - 1)]
        strike_gap = sorted(gaps)[len(gaps) // 2]
    else:
        strike_gap = 50

    for k in nearby_strikes:
        ce = chain_df[(chain_df["strike"] == k) & (chain_df["opt_type"] == "CE")]
        pe = chain_df[(chain_df["strike"] == k) & (chain_df["opt_type"] == "PE")]

        def v(df, col, fmt="{:.1f}"):
            if df.empty or col not in df.columns:
                return "—"
            val = df[col].values[0]
            try:
                return fmt.format(float(val))
            except Exception:
                return str(val)

        is_atm = abs(k - spot) < strike_gap * 0.6
        is_mp = abs(k - max_pain) < strike_gap * 0.6

        label = f"{'→' if is_atm else ' '}{int(k)}{'◆' if is_mp else ' '}"
        k_style = "bold underline" if is_atm else ("yellow" if is_mp else "")

        t.add_row(
            Text(label, style=k_style),
            v(ce, "bid"),
            Text(v(ce, "ltp", "{:.2f}"), style="green"),
            v(ce, "ask"),
            v(ce, "iv", "{:.1f}"),
            f"{float(ce['oi'].values[0]):,.0f}" if not ce.empty else "—",
            v(ce, "delta", "{:.3f}"),
            v(ce, "theta", "{:.1f}"),
            "│",
            v(pe, "theta", "{:.1f}"),
            v(pe, "delta", "{:.3f}"),
            f"{float(pe['oi'].values[0]):,.0f}" if not pe.empty else "—",
            v(pe, "iv", "{:.1f}"),
            v(pe, "bid"),
            Text(v(pe, "ltp", "{:.2f}"), style="red"),
            v(pe, "ask"),
        )
    return t


def _top_signal_detail(sig: Signal) -> Panel:
    lines = [f"[bold]{sig.strategy}[/] — {sig.strategy_brief}", ""]
    for r in sig.reasons:
        lines.append(f"  • {r}")
    if sig.recommended_strikes:
        lines.append(
            "\nRecommended: [bold]"
            + ", ".join(str(int(s)) for s in sig.recommended_strikes)
            + "[/]"
        )
    dir_style = _DIR_STYLES.get(sig.direction, "white").replace("bold ", "")
    return Panel(
        "\n".join(lines),
        title=f"[bold]Signal Detail — {sig.expiry_date}  ({dte_label(sig.expiry_date)})[/]",
        border_style=dir_style,
    )


def _footer(oi_result, iv_env, last_updated: str) -> Panel:
    items = [
        f"PCR(OI): [bold]{oi_result.pcr_oi:.2f}[/]",
        f"PCR(Vol): [bold]{oi_result.pcr_volume:.2f}[/]",
        f"Max Pain: [bold]{oi_result.max_pain:,.0f}[/]",
        f"IV Rank: [bold]{iv_env.iv_rank:.0f}/100[/]",
        f"ATM IV: [bold]{iv_env.atm_iv*100:.1f}%[/]",
        f"Regime: [bold]{iv_env.regime}[/]",
        f"Updated: [dim]{last_updated}[/]",
    ]
    return Panel("  |  ".join(items), border_style="dim")


def _build_display(
    symbol: str,
    expiry: Optional[str],
    offline: bool,
    mdf: MarketDataFetcher,
    ocf: OptionsChainFetcher,
) -> Group:
    spot_data = mdf.get_spot(symbol)
    spot = float(spot_data.get("last_price", 0))

    expiries = ocf.get_expiries(symbol)
    if not expiries:
        return Group(Panel("[red]No expiry dates found.[/]"))

    target_expiry = expiry or expiries[0]
    if target_expiry not in expiries:
        target_expiry = expiries[0]

    chain_df = ocf.get_chain_df(symbol, target_expiry, spot)
    iv_52wh, iv_52wl = mdf.get_historical_iv_range(symbol)
    iv_env = analyze_iv_environment(chain_df, spot, iv_52wh, iv_52wl)
    oi_result = analyze_oi(chain_df, spot)

    all_signals: List[Signal] = []
    for exp in expiries[:4]:
        df = ocf.get_chain_df(symbol, exp, spot)
        if not df.empty:
            iv_e = analyze_iv_environment(df, spot, iv_52wh, iv_52wl)
            oi_e = analyze_oi(df, spot)
            all_signals.extend(generate_signals(df, iv_e, oi_e, spot, exp))

    last_upd = now_ist().strftime("%H:%M:%S IST")

    renderables = [
        _header(symbol, spot_data, offline),
        _signals_table(all_signals),
        _chain_table(chain_df, spot, oi_result.max_pain),
    ]

    if all_signals:
        top = sorted(all_signals, key=lambda s: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[s.confidence.value])[0]
        renderables.append(_top_signal_detail(top))

    renderables.append(_footer(oi_result, iv_env, last_upd))
    return Group(*renderables)


def run(symbol: str, expiry: Optional[str], offline: bool, once: bool) -> None:
    token = get_stored_token()
    if not offline and token and validate_token(token):
        client: Optional[UpstoxClient] = UpstoxClient(token)
        is_live = True
    else:
        client = None
        if not offline:
            console.print(AUTH_INSTRUCTIONS)
        offline = True
        is_live = False

    mdf = MarketDataFetcher(client, offline)
    ocf = OptionsChainFetcher(client, offline)

    if once:
        console.print(_build_display(symbol, expiry, offline, mdf, ocf))
        return

    with Live(console=console, refresh_per_second=1, screen=True) as live:
        while True:
            try:
                live.update(_build_display(symbol, expiry, offline, mdf, ocf))
            except KeyboardInterrupt:
                break
            except Exception as e:
                live.update(Panel(f"[red]Error: {e}[/]\nRetrying..."))

            time.sleep(_REFRESH_SECS if is_live and is_market_open() else 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Options Trading Signals — Terminal Dashboard")
    parser.add_argument("--index", default="NIFTY", choices=list(INDICES.keys()))
    parser.add_argument("--expiry", default=None, help="Expiry date YYYY-MM-DD (default: nearest)")
    parser.add_argument("--offline", action="store_true", help="Force offline/sample-data mode")
    parser.add_argument("--once", action="store_true", help="Print once and exit")
    args = parser.parse_args()
    run(args.index, args.expiry, args.offline, args.once)


if __name__ == "__main__":
    main()
