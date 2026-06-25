from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whale_signal_lab.models import Direction, WalletActivity
from whale_signal_lab.smart_money import SmartMoneyClusterEngine


class SmartMoneyClusterEngineTest(unittest.TestCase):
    def test_cluster_signal_emits_when_wallets_align(self) -> None:
        engine = SmartMoneyClusterEngine(
            wallet_limit=10_000,
            window_sec=240,
            min_cluster_wallets=5,
            min_cluster_usd=50_000,
        )
        now = datetime.now(UTC)
        activities = [
            WalletActivity(
                chain="bsc",
                wallet=f"0x{index:040x}",
                symbol="BTCUSDT",
                token_symbol="BTC",
                direction=Direction.LONG,
                usd_value=20_000,
                tx_count=1,
                timestamp=now,
                cluster_hint="test_cluster",
            )
            for index in range(8)
        ]

        signals = engine.ingest(activities)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].symbol, "BTCUSDT")
        self.assertEqual(signals[0].direction, Direction.LONG)
        self.assertEqual(signals[0].wallet_count, 8)
        self.assertGreater(signals[0].score, 0.0)


if __name__ == "__main__":
    unittest.main()
