from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whale_signal_lab.adapters.binance_futures import _sentiment_score


class BinanceFuturesSentimentTest(unittest.TestCase):
    def test_sentiment_combines_top_trader_taker_and_crowd_contrarian(self) -> None:
        bullish = _sentiment_score(global_ratio=0.8, top_ratio=1.6, taker_ratio=1.4)
        bearish = _sentiment_score(global_ratio=1.4, top_ratio=0.7, taker_ratio=0.8)

        self.assertGreater(bullish, 0.0)
        self.assertLess(bearish, 0.0)


if __name__ == "__main__":
    unittest.main()
