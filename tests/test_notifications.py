from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whale_signal_lab.models import Direction, PaperOrder, PricePathPoint, Signal, TradePlan, utc_now
from whale_signal_lab.notifications import TelegramNotifier, format_entry_message, format_exit_message


class _FakeResponse:
    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"ok": true}'


def _signal() -> Signal:
    return Signal(
        symbol="BTCUSDT",
        direction=Direction.LONG,
        confidence=0.82,
        score=0.31,
        price=100.0,
        horizon_sec=900,
        components={"volatility_penalty": 0.012, "shock_risk": 0.004},
        rationale="gate pass",
        expected_path=[PricePathPoint(900, 103.0, 99.0, 103.0)],
        generated_at=utc_now(),
    )


def _order() -> PaperOrder:
    return PaperOrder(
        symbol="BTCUSDT",
        side=Direction.LONG,
        quantity=20.0,
        fill_price=100.2,
        notional=2004.0,
        fee=1.5,
        reason="test",
        timestamp=utc_now(),
        leverage=10.0,
        margin_used=200.4,
    )


class TelegramNotifierTest(unittest.TestCase):
    def test_format_entry_message_is_short_signal_template(self) -> None:
        plan = TradePlan("BTCUSDT", Direction.LONG, 100.2, 99.0, 103.6, 1.2, 3.0, 7)

        text = format_entry_message(_order(), _signal(), plan, mode="demo", tick=7, equity=10_100)

        self.assertEqual(
            text,
            "BTCUSDT LONG - ENTRY[100.2] - TP[103.6] - SL[99] - VOL[$2,004] - LEV[10x] - MARGIN[$200.4]",
        )

    def test_format_exit_message_includes_pnl(self) -> None:
        plan = TradePlan(
            "BTCUSDT",
            Direction.LONG,
            100.2,
            99.0,
            103.6,
            1.2,
            3.0,
            7,
            leverage=10.0,
            margin_used=200.4,
        )
        order = PaperOrder(
            symbol="BTCUSDT",
            side=Direction.SHORT,
            quantity=20.0,
            fill_price=103.6,
            notional=2072.0,
            fee=1.5,
            reason="take_profit_rr_hit",
            timestamp=utc_now(),
            leverage=10.0,
            margin_used=200.4,
            realized_pnl=66.5,
            closed_notional=2072.0,
        )

        text = format_exit_message(order, plan, mode="demo", tick=9, equity=10_166.5)

        self.assertEqual(
            text,
            "BTCUSDT LONG CLOSE - EXIT[103.6] - PNL[+$66.5] - ROI[+33.18363273%] - VOL[$2,072] - LEV[10x] - REASON[TAKE_PROFIT_RR_HIT]",
        )

    def test_send_text_posts_to_telegram_api(self) -> None:
        calls: list[tuple[str, dict, float]] = []

        def fake_urlopen(req, timeout: float):
            calls.append((req.full_url, json.loads(req.data.decode("utf-8")), timeout))
            return _FakeResponse()

        notifier = TelegramNotifier(
            enabled=True,
            bot_token="token",
            chat_id="@channel",
            timeout_sec=3.0,
            urlopen=fake_urlopen,
        )

        self.assertTrue(notifier.send_text("hello"))
        self.assertEqual(notifier.sent_count, 1)
        self.assertEqual(calls[0][0], "https://api.telegram.org/bottoken/sendMessage")
        self.assertEqual(calls[0][1]["chat_id"], "@channel")
        self.assertEqual(calls[0][1]["text"], "hello")
        self.assertEqual(calls[0][2], 3.0)

    def test_send_text_reports_missing_token_without_network_call(self) -> None:
        called = False

        def fake_urlopen(req, timeout: float):
            nonlocal called
            called = True
            return _FakeResponse()

        notifier = TelegramNotifier(
            enabled=True,
            bot_token="",
            chat_id="@channel",
            urlopen=fake_urlopen,
        )

        self.assertFalse(notifier.send_text("hello"))
        self.assertFalse(called)
        self.assertIn("TELEGRAM_BOT_TOKEN", notifier.last_error)


if __name__ == "__main__":
    unittest.main()
