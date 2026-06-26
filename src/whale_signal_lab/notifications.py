from __future__ import annotations

from contextlib import contextmanager
import json
import socket
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib import error, request

from .config import TelegramConfig
from .models import Direction, PaperOrder, Signal, TradePlan


class _Response(Protocol):
    def __enter__(self) -> "_Response": ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    def read(self) -> bytes: ...


UrlOpen = Callable[..., _Response]


@dataclass
class TelegramNotifier:
    enabled: bool
    bot_token: str
    chat_id: str
    notify_entries: bool = True
    notify_exits: bool = False
    timeout_sec: float = 5.0
    api_ip: str = ""
    urlopen: UrlOpen = request.urlopen
    last_error: str = ""
    sent_count: int = 0

    @classmethod
    def from_config(cls, config: TelegramConfig) -> "TelegramNotifier":
        return cls(
            enabled=config.is_enabled,
            bot_token=config.bot_token,
            chat_id=config.target_chat_id,
            notify_entries=config.notify_entries,
            notify_exits=config.notify_exits,
            timeout_sec=config.timeout_sec,
            api_ip=config.api_ip,
        )

    def status(self) -> dict[str, object]:
        if not self.enabled:
            state = "disabled"
        elif not self.bot_token:
            state = "missing_bot_token"
        elif not self.chat_id:
            state = "missing_chat_id"
        elif self.last_error:
            state = "error"
        else:
            state = "ready"
        return {
            "enabled": self.enabled,
            "state": state,
            "chat_id": self.chat_id if self.chat_id.startswith("@") else ("configured" if self.chat_id else ""),
            "notify_entries": self.notify_entries,
            "notify_exits": self.notify_exits,
            "sent_count": self.sent_count,
            "last_error": self.last_error,
        }

    def notify_entry(
        self,
        order: PaperOrder,
        signal: Signal | None,
        plan: TradePlan | None,
        *,
        mode: str,
        tick: int,
        equity: float,
    ) -> bool:
        if not self.notify_entries:
            return False
        return self.send_text(format_entry_message(order, signal, plan, mode=mode, tick=tick, equity=equity))

    def notify_exit(
        self,
        order: PaperOrder,
        plan: TradePlan | None,
        *,
        mode: str,
        tick: int,
        equity: float,
    ) -> bool:
        if not self.notify_exits:
            return False
        return self.send_text(format_exit_message(order, plan, mode=mode, tick=tick, equity=equity))

    def send_text(self, text: str) -> bool:
        self.last_error = ""
        if not self.enabled:
            return False
        if not self.bot_token:
            self.last_error = "TELEGRAM_BOT_TOKEN is not set."
            return False
        if not self.chat_id:
            self.last_error = "TELEGRAM_CHAT_ID is not set."
            return False

        payload = json.dumps(
            {
                "chat_id": self.chat_id,
                "text": text[:4096],
                "disable_web_page_preview": True,
            }
        ).encode("utf-8")
        req = request.Request(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with _temporary_host_override("api.telegram.org", self.api_ip):
                with self.urlopen(req, timeout=self.timeout_sec) as response:
                    raw = response.read()
        except (OSError, error.URLError) as exc:
            self.last_error = f"Telegram send failed: {exc}"
            return False

        try:
            data = json.loads(raw.decode("utf-8") if raw else "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = {}
        if data and data.get("ok") is False:
            self.last_error = f"Telegram rejected message: {data.get('description', 'unknown error')}"
            return False
        self.sent_count += 1
        return True


def format_entry_message(
    order: PaperOrder,
    signal: Signal | None,
    plan: TradePlan | None,
    *,
    mode: str,
    tick: int,
    equity: float,
) -> str:
    token = order.symbol.upper()
    side = (plan.side if plan else signal.direction if signal else order.side).value
    entry = _money(order.fill_price)
    take_profit = _money(plan.take_profit_price) if plan else "N/A"
    stop_loss = _money(plan.stop_price) if plan else "N/A"
    volume = _money(order.notional)
    leverage = _leverage(order.leverage)
    margin = _money(order.margin_used)
    return (
        f"{token} {side} - ENTRY[{entry}] - TP[{take_profit}] - SL[{stop_loss}] "
        f"- VOL[${volume}] - LEV[{leverage}] - MARGIN[${margin}]"
    )


def format_exit_message(
    order: PaperOrder,
    plan: TradePlan | None,
    *,
    mode: str,
    tick: int,
    equity: float,
) -> str:
    token = order.symbol.upper()
    side = plan.side.value if plan else ("SHORT" if order.side == Direction.LONG else "LONG")
    exit_price = _money(order.fill_price)
    pnl = _signed_money(order.realized_pnl)
    pnl_pct = _signed_pct((order.realized_pnl / order.margin_used * 100.0) if order.margin_used else 0.0)
    volume = _money(order.closed_notional or order.notional)
    leverage = _leverage(order.leverage)
    reason = order.reason.upper()
    return (
        f"{token} {side} CLOSE - EXIT[{exit_price}] - PNL[{pnl}] - ROI[{pnl_pct}] "
        f"- VOL[${volume}] - LEV[{leverage}] - REASON[{reason}]"
    )


def _money(value: float) -> str:
    return f"{value:,.8f}".rstrip("0").rstrip(".")


def _signed_money(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}${_money(abs(value))}"


def _signed_pct(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}{_money(abs(value))}%"


def _leverage(value: float) -> str:
    return f"{_money(value)}x"


def _number(value: float, digits: int) -> str:
    return f"{value:,.{digits}f}".rstrip("0").rstrip(".")


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


@contextmanager
def _temporary_host_override(host: str, ip: str):
    if not ip:
        yield
        return

    original_getaddrinfo = socket.getaddrinfo

    def patched_getaddrinfo(
        query_host: str,
        port: int | str | None,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ):
        if query_host == host:
            return original_getaddrinfo(ip, port, family, type, proto, flags)
        return original_getaddrinfo(query_host, port, family, type, proto, flags)

    socket.getaddrinfo = patched_getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo
