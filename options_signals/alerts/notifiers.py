"""
Alert notification backends.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import List

from alerts.alert_engine import AlertRule
from config import IST

_LOG_FILE = Path(__file__).parent.parent / "data_store" / "alerts.log"


class TerminalNotifier:
    def notify(self, rules: List[AlertRule]) -> None:
        from rich.console import Console
        c = Console()
        for r in rules:
            c.print(
                f"[bold red]ALERT FIRED[/] [{datetime.datetime.now(IST).strftime('%H:%M:%S IST')}] "
                f"{r.label}  (current value: {r.last_value})"
            )


class LogFileNotifier:
    def notify(self, rules: List[AlertRule]) -> None:
        _LOG_FILE.parent.mkdir(exist_ok=True)
        with _LOG_FILE.open("a") as f:
            for r in rules:
                f.write(
                    f"{datetime.datetime.now(IST).isoformat()}  ALERT  {r.label}  "
                    f"condition={r.condition_type}  threshold={r.threshold}  "
                    f"value={r.last_value}\n"
                )
