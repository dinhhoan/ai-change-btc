from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whale_signal_lab.backtesting import run_backtest_on_candles
from whale_signal_lab.config import LabConfig


class BacktestingTest(unittest.TestCase):
    def test_backtest_replays_candles_without_network(self) -> None:
        config = LabConfig()
        candles = []
        start = 1_782_000_000_000
        price = 100.0
        for index in range(80):
            price *= 1.001 if index < 45 else 0.999
            candles.append(
                {
                    "symbol": "BTCUSDT",
                    "interval": "5m",
                    "open_time_ms": start + index * 300_000,
                    "close_time_ms": start + (index + 1) * 300_000,
                    "open": price * 0.999,
                    "high": price * 1.002,
                    "low": price * 0.998,
                    "close": price,
                    "volume_quote": 1_000_000.0,
                    "taker_buy_quote": 720_000.0 if index < 45 else 280_000.0,
                }
            )

        result = run_backtest_on_candles(config, candles)

        self.assertIn("performance", result)
        self.assertIn("orders_by_symbol", result)
        self.assertIn("BTCUSDT", result["orders_by_symbol"])


if __name__ == "__main__":
    unittest.main()
