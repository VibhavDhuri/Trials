"""
Alert notification backends.

Available notifiers:
  TerminalNotifier  — prints to rich console (always works)
  LogFileNotifier   — appends to data_store/alerts.log (always works)
  EmailNotifier     — sends email via SMTP (requires .env config)
  TelegramNotifier  — sends Telegram message (requires .env config)

Configure email:    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_TO
Configure Telegram: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
from __future__ import annotations

import datetime
import os
import smtplib
import ssl
from email.mime.text import MIMEText
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


class EmailNotifier:
    """
    Send alert emails via SMTP. Configure with env vars:
      SMTP_HOST       (e.g. smtp.gmail.com)
      SMTP_PORT       (e.g. 587)
      SMTP_USER       (your email address)
      SMTP_PASSWORD   (app password — for Gmail, create one in Google Account → Security)
      ALERT_EMAIL_TO  (recipient; defaults to SMTP_USER if not set)
    Uses STARTTLS encryption.
    """
    def __init__(self) -> None:
        self._host     = os.getenv("SMTP_HOST", "")
        self._port     = int(os.getenv("SMTP_PORT", "587"))
        self._user     = os.getenv("SMTP_USER", "")
        self._password = os.getenv("SMTP_PASSWORD", "")
        self._to       = os.getenv("ALERT_EMAIL_TO", self._user)

    def is_configured(self) -> bool:
        return bool(self._host and self._user and self._password)

    def notify(self, rules: List[AlertRule]) -> None:
        if not self.is_configured() or not rules:
            return
        now_str = datetime.datetime.now(IST).strftime("%d %b %Y %H:%M:%S IST")
        lines = [f"Options Signals — {len(rules)} alert(s) fired at {now_str}\n"]
        for r in rules:
            lines.append(f"• {r.label}  (value: {r.last_value},  threshold: {r.threshold})")
        body = "\n".join(lines)
        msg = MIMEText(body)
        msg["Subject"] = f"[Options Alert] {rules[0].label}"
        msg["From"]    = self._user
        msg["To"]      = self._to
        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(self._host, self._port, timeout=10) as srv:
                srv.ehlo()
                srv.starttls(context=ctx)
                srv.login(self._user, self._password)
                srv.sendmail(self._user, self._to, msg.as_string())
        except Exception as exc:
            _LOG_FILE.parent.mkdir(exist_ok=True)
            with _LOG_FILE.open("a") as f:
                f.write(f"{datetime.datetime.now(IST).isoformat()}  EMAIL_ERROR  {exc}\n")


class TelegramNotifier:
    """
    Send alert messages via Telegram Bot API. Configure with env vars:
      TELEGRAM_BOT_TOKEN  (get from @BotFather on Telegram)
      TELEGRAM_CHAT_ID    (your numeric chat ID — start your bot, then call
                           https://api.telegram.org/bot<TOKEN>/getUpdates)
    """
    _API = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self) -> None:
        self._token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    def is_configured(self) -> bool:
        return bool(self._token and self._chat_id)

    def notify(self, rules: List[AlertRule]) -> None:
        if not self.is_configured() or not rules:
            return
        import requests
        now_str = datetime.datetime.now(IST).strftime("%H:%M IST")
        lines = [f"\U0001f4e2 *Options Alert* — {now_str}"]
        for r in rules:
            # Escape special Markdown V2 chars
            label = str(r.label).replace(".", "\\.").replace("-", "\\-").replace("(", "\\(").replace(")", "\\)")
            lines.append(f"• {label}  \\(value: {r.last_value}, threshold: {r.threshold}\\)")
        text = "\n".join(lines)
        try:
            requests.post(
                self._API.format(token=self._token),
                json={"chat_id": self._chat_id, "text": text, "parse_mode": "MarkdownV2"},
                timeout=10,
            )
        except Exception as exc:
            _LOG_FILE.parent.mkdir(exist_ok=True)
            with _LOG_FILE.open("a") as f:
                f.write(f"{datetime.datetime.now(IST).isoformat()}  TELEGRAM_ERROR  {exc}\n")


def build_notifiers() -> list:
    """Return all configured notifiers. Terminal + log file always included."""
    notifiers: list = [TerminalNotifier(), LogFileNotifier()]
    email = EmailNotifier()
    if email.is_configured():
        notifiers.append(email)
    tg = TelegramNotifier()
    if tg.is_configured():
        notifiers.append(tg)
    return notifiers
