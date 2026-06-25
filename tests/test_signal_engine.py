from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whale_signal_lab.features import FeatureAssembler
from whale_signal_lab.models import Direction, FeatureSnapshot, LongShortSnapshot, MarketTick, WhaleDirection, WhaleTransfer
from whale_signal_lab.signals import SignalEngine


class SignalEngineTest(unittest.TestCase):
    def test_signal_turns_long_when_momentum_and_whales_align(self) -> None:
        assembler = FeatureAssembler(stablecoins={"USDT", "USDC"})
        now = datetime.now(UTC)
        assembler.add_market_tick(
            MarketTick("BTCUSDT", 100.0, now, volume_quote=1_000_000, taker_buy_quote=650_000)
        )
        assembler.add_market_tick(
            MarketTick("BTCUSDT", 102.0, now, volume_quote=1_000_000, taker_buy_quote=700_000)
        )
        assembler.add_whale_transfer(
            WhaleTransfer(
                chain="ethereum",
                tx_hash="0x1",
                wallet="whale",
                counterparty="exchange",
                token_symbol="BTC",
                token_contract=None,
                amount=50,
                usd_value=5_000_000,
                direction=WhaleDirection.EXCHANGE_OUTFLOW,
                timestamp=now,
            )
        )
        assembler.add_long_short_snapshot(
            LongShortSnapshot(
                symbol="BTCUSDT",
                global_long_account=0.48,
                global_short_account=0.52,
                global_ratio=0.92,
                top_long_account=0.55,
                top_short_account=0.45,
                top_ratio=1.14,
                taker_buy_sell_ratio=1.12,
                taker_buy_volume=650_000,
                taker_sell_volume=580_000,
                open_interest_value=1_000_000_000,
                open_interest_change_pct=0.0025,
                sentiment_score=0.24,
                timestamp=now,
            )
        )

        signal = SignalEngine(whale_threshold_usd=1_000_000).evaluate(assembler.snapshot("BTCUSDT"))

        self.assertEqual(signal.direction, Direction.LONG)
        self.assertGreater(signal.confidence, 0.58)
        self.assertEqual(signal.components["gate_passed"], 1.0)
        self.assertGreater(signal.expected_path[-1].expected_price, signal.price)

    def test_strategy_gate_blocks_whale_only_signal(self) -> None:
        assembler = FeatureAssembler(stablecoins={"USDT", "USDC"})
        now = datetime.now(UTC)
        assembler.add_market_tick(
            MarketTick("BTCUSDT", 100.0, now, volume_quote=1_000_000, taker_buy_quote=500_000)
        )
        assembler.add_whale_transfer(
            WhaleTransfer(
                chain="ethereum",
                tx_hash="0x2",
                wallet="whale",
                counterparty="exchange",
                token_symbol="BTC",
                token_contract=None,
                amount=50,
                usd_value=5_000_000,
                direction=WhaleDirection.EXCHANGE_OUTFLOW,
                timestamp=now,
            )
        )
        assembler.add_long_short_snapshot(
            LongShortSnapshot(
                symbol="BTCUSDT",
                global_long_account=0.5,
                global_short_account=0.5,
                global_ratio=1.0,
                top_long_account=0.5,
                top_short_account=0.5,
                top_ratio=1.0,
                taker_buy_sell_ratio=1.0,
                taker_buy_volume=500_000,
                taker_sell_volume=500_000,
                open_interest_value=1_000_000_000,
                open_interest_change_pct=0.0,
                sentiment_score=0.0,
                timestamp=now,
            )
        )

        signal = SignalEngine(whale_threshold_usd=1_000_000).evaluate(assembler.snapshot("BTCUSDT"))

        self.assertEqual(signal.direction, Direction.FLAT)
        self.assertEqual(signal.components["gate_passed"], 0.0)
        self.assertIn("score/confidence below entry threshold", signal.rationale)

    def test_signal_blocks_when_derivatives_snapshot_is_stale(self) -> None:
        assembler = FeatureAssembler(stablecoins={"USDT"})
        now = datetime.now(UTC)
        assembler.add_market_tick(MarketTick("BTCUSDT", 100.0, now, volume_quote=1_000_000, taker_buy_quote=650_000))
        assembler.add_market_tick(MarketTick("BTCUSDT", 101.5, now, volume_quote=1_000_000, taker_buy_quote=720_000))
        assembler.add_whale_transfer(
            WhaleTransfer(
                chain="ethereum",
                tx_hash="0x3",
                wallet="whale",
                counterparty="exchange",
                token_symbol="BTC",
                token_contract=None,
                amount=50,
                usd_value=5_000_000,
                direction=WhaleDirection.EXCHANGE_OUTFLOW,
                timestamp=now,
            )
        )
        assembler.add_long_short_snapshot(
            LongShortSnapshot(
                symbol="BTCUSDT",
                global_long_account=0.49,
                global_short_account=0.51,
                global_ratio=0.96,
                top_long_account=0.56,
                top_short_account=0.44,
                top_ratio=1.16,
                taker_buy_sell_ratio=1.11,
                taker_buy_volume=700_000,
                taker_sell_volume=500_000,
                open_interest_value=1_000_000_000,
                open_interest_change_pct=0.002,
                sentiment_score=0.22,
                timestamp=datetime(2026, 6, 18, tzinfo=UTC),
            )
        )

        signal = SignalEngine().evaluate(assembler.snapshot("BTCUSDT"))

        self.assertEqual(signal.direction, Direction.FLAT)
        self.assertIn("derivatives 5m is stale", signal.rationale)

    def test_signal_allows_reduced_size_fallback_when_derivatives_are_stale(self) -> None:
        now = datetime.now(UTC)
        features = FeatureSnapshot(
            symbol="BTCUSDT",
            price=100.0,
            momentum_pct=0.010,
            realized_volatility=0.0004,
            buy_pressure=0.62,
            quote_volume=5_000_000,
            whale_net_usd=0.0,
            whale_event_count=0,
            generated_at=now,
            ema_fast=100.8,
            ema_slow=100.0,
            trend_score=0.12,
            rsi=60.0,
            smart_money_score=0.86,
            smart_money_sync=0.82,
            smart_money_wallets=80,
            smart_money_usd=2_000_000,
            smart_money_age_sec=20,
            derivatives_score=0.0,
            global_long_short_ratio=1.0,
            top_long_short_ratio=1.0,
            taker_buy_sell_ratio=1.0,
            open_interest_value=0.0,
            open_interest_change_pct=0.0,
            derivatives_age_sec=1200,
            higher_tf_trend_score=0.35,
            higher_tf_momentum_pct=0.005,
            market_regime="high_volatility",
            orderbook_imbalance=0.40,
            spread_bps=0.5,
            orderbook_age_sec=5,
        )

        signal = SignalEngine().evaluate(features)

        self.assertEqual(signal.direction, Direction.LONG)
        self.assertEqual(signal.components["derivatives_fresh"], 0.0)
        self.assertEqual(signal.components["degraded_derivatives_mode"], 1.0)
        self.assertIn("reduced-size derivatives fallback", signal.rationale)

    def test_signal_blocks_late_short_after_volatile_flush(self) -> None:
        now = datetime.now(UTC)
        features = FeatureSnapshot(
            symbol="SOLUSDT",
            price=70.0,
            momentum_pct=-0.006,
            realized_volatility=0.00045,
            buy_pressure=0.20,
            quote_volume=2_000_000,
            whale_net_usd=0.0,
            whale_event_count=0,
            generated_at=now,
            ema_fast=69.8,
            ema_slow=70.0,
            trend_score=-0.06,
            rsi=34.0,
            smart_money_score=-0.90,
            smart_money_sync=0.86,
            smart_money_wallets=180,
            smart_money_usd=2_500_000,
            smart_money_age_sec=30,
            derivatives_score=-0.18,
            global_long_short_ratio=1.8,
            top_long_short_ratio=1.0,
            taker_buy_sell_ratio=0.72,
            open_interest_value=1_000_000_000,
            open_interest_change_pct=0.001,
            derivatives_age_sec=30,
        )

        signal = SignalEngine().evaluate(features)

        self.assertEqual(signal.direction, Direction.FLAT)
        self.assertEqual(signal.components["shock_risk"], 1.0)
        self.assertIn("late SHORT after volatile flush", signal.rationale)

    def test_signal_stays_flat_without_market_price(self) -> None:
        assembler = FeatureAssembler(stablecoins={"USDT"})
        signal = SignalEngine().evaluate(assembler.snapshot("BTCUSDT"))

        self.assertEqual(signal.direction, Direction.FLAT)
        self.assertEqual(signal.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
