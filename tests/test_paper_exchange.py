from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whale_signal_lab.models import Direction, PricePathPoint, Signal, utc_now
from whale_signal_lab.paper import PaperBroker


def _signal(
    direction: Direction,
    price: float = 100.0,
    confidence: float = 0.8,
    expected_price: float | None = None,
    lower_band: float | None = None,
    upper_band: float | None = None,
    components: dict[str, float] | None = None,
) -> Signal:
    expected_price = price if expected_price is None else expected_price
    lower_band = expected_price if lower_band is None else lower_band
    upper_band = expected_price if upper_band is None else upper_band
    return Signal(
        symbol="BTCUSDT",
        direction=direction,
        confidence=confidence,
        score=0.8 if direction == Direction.LONG else -0.8,
        price=price,
        horizon_sec=900,
        components=components or {},
        rationale="test",
        expected_path=[
            PricePathPoint(225, expected_price, lower_band, upper_band),
            PricePathPoint(900, expected_price, lower_band, upper_band),
        ],
        generated_at=utc_now(),
    )


class PaperBrokerTest(unittest.TestCase):
    def test_paper_broker_opens_and_closes_position(self) -> None:
        broker = PaperBroker(
            starting_cash=10_000,
            risk_per_trade=0.2,
            fee_bps=0,
            slippage_bps=0,
            min_confidence_to_trade=0.5,
            max_abs_position_usd=5_000,
        )

        buy = broker.rebalance_from_signal(
            _signal(Direction.LONG, expected_price=103.0, lower_band=99.0, upper_band=101.0),
            1,
        )
        self.assertIsNotNone(buy)
        self.assertEqual(broker.positions["BTCUSDT"].quantity, 20)
        self.assertEqual(broker.cash, 8_000)
        self.assertIn("BTCUSDT", broker.trade_plans)

        sell = broker.mark("BTCUSDT", 103.1, 6)
        self.assertIsNotNone(sell)
        self.assertEqual(broker.positions["BTCUSDT"].quantity, 0)
        self.assertGreater(broker.cash, 10_050)
        performance = broker.performance_summary()
        self.assertGreater(performance["net_pnl"], 0)
        self.assertGreater(performance["realized_pnl"], 0)
        self.assertEqual(performance["win_rate"], 1.0)
        self.assertEqual(performance["winning_trades"], 1)
        self.assertEqual(performance["losing_trades"], 0)

    def test_cost_guard_skips_trade_when_gas_exceeds_expected_edge(self) -> None:
        broker = PaperBroker(
            starting_cash=10_000,
            risk_per_trade=0.2,
            fee_bps=10,
            slippage_bps=5,
            min_confidence_to_trade=0.5,
            max_abs_position_usd=5_000,
            gas_fee_usd=25,
            min_edge_cost_multiple=2.0,
        )

        order = broker.rebalance_from_signal(
            _signal(Direction.LONG, expected_price=100.2, lower_band=99.95, upper_band=100.1),
            1,
        )

        self.assertIsNone(order)
        self.assertEqual(len(broker.skipped_trades), 1)
        self.assertEqual(broker.skipped_trades[-1]["reason"], "expected_edge_below_fee_gas_threshold")

    def test_forecast_gate_skips_trade_when_path_does_not_reach_1r(self) -> None:
        broker = PaperBroker(
            starting_cash=10_000,
            risk_per_trade=0.2,
            fee_bps=1,
            slippage_bps=0,
            min_confidence_to_trade=0.5,
            max_abs_position_usd=5_000,
        )

        order = broker.rebalance_from_signal(
            _signal(Direction.LONG, expected_price=100.25, lower_band=99.0, upper_band=100.3),
            1,
        )

        self.assertIsNone(order)
        self.assertEqual(len(broker.skipped_trades), 1)
        self.assertEqual(broker.skipped_trades[-1]["reason"], "forecast_reward_below_min_rr")

    def test_volatility_guard_tightens_forecast_gate_and_reduces_size(self) -> None:
        broker = PaperBroker(
            starting_cash=10_000,
            risk_per_trade=0.2,
            fee_bps=1,
            slippage_bps=0,
            min_confidence_to_trade=0.5,
            max_abs_position_usd=5_000,
            volatility_risk_penalty_threshold=0.008,
            high_volatility_position_scale=0.5,
        )

        order = broker.rebalance_from_signal(
            _signal(
                Direction.LONG,
                expected_price=100.82,
                lower_band=99.0,
                upper_band=101.0,
                components={"volatility_penalty": 0.012},
            ),
            1,
        )

        self.assertIsNone(order)
        self.assertEqual(len(broker.skipped_trades), 1)
        self.assertEqual(
            broker.skipped_trades[-1]["reason"],
            "volatility_adjusted_forecast_reward_below_min_rr",
        )
        self.assertEqual(broker.skipped_trades[-1]["notional"], 1000.0)

    def test_degraded_derivatives_mode_reduces_entry_size(self) -> None:
        broker = PaperBroker(
            starting_cash=10_000,
            risk_per_trade=0.2,
            fee_bps=0,
            slippage_bps=0,
            min_confidence_to_trade=0.5,
            max_abs_position_usd=5_000,
        )

        order = broker.rebalance_from_signal(
            _signal(
                Direction.LONG,
                expected_price=104.0,
                lower_band=99.0,
                upper_band=101.0,
                components={"derivatives_fresh": 0.0, "degraded_derivatives_mode": 1.0},
            ),
            1,
        )

        self.assertIsNotNone(order)
        self.assertAlmostEqual(order.notional, 700.0)

    def test_scout_mode_uses_lower_confidence_floor_and_small_size(self) -> None:
        broker = PaperBroker(
            starting_cash=10_000,
            risk_per_trade=0.2,
            fee_bps=0,
            slippage_bps=0,
            min_confidence_to_trade=0.58,
            max_abs_position_usd=5_000,
            scout_position_scale=0.25,
            scout_min_confidence_to_trade=0.50,
        )

        normal = broker.rebalance_from_signal(
            _signal(Direction.LONG, confidence=0.52, expected_price=104.0, lower_band=99.0, upper_band=101.0),
            1,
        )
        self.assertIsNone(normal)

        scout = broker.rebalance_from_signal(
            _signal(
                Direction.LONG,
                confidence=0.52,
                expected_price=104.0,
                lower_band=99.0,
                upper_band=101.0,
                components={"scout_mode": 1.0},
            ),
            2,
        )

        self.assertIsNotNone(scout)
        self.assertAlmostEqual(scout.notional, 500.0)

    def test_target_notional_uses_futures_leverage_metadata(self) -> None:
        broker = PaperBroker(
            starting_cash=10_000,
            risk_per_trade=0.2,
            fee_bps=0,
            slippage_bps=0,
            min_confidence_to_trade=0.5,
            max_abs_position_usd=10_000,
            target_position_notional_usd=10_000,
            target_margin_usd=1_000,
            max_leverage=10,
            futures_margin_mode=True,
        )

        order = broker.rebalance_from_signal(
            _signal(Direction.LONG, expected_price=104.0, lower_band=99.0, upper_band=101.0),
            1,
        )

        self.assertIsNotNone(order)
        self.assertAlmostEqual(order.notional, 10_000.0)
        self.assertAlmostEqual(order.leverage, 10.0)
        self.assertAlmostEqual(order.margin_used, 1_000.0)
        self.assertAlmostEqual(broker.cash, 10_000.0)

    def test_trailing_guard_moves_stop_after_trade_reaches_profit(self) -> None:
        broker = PaperBroker(
            starting_cash=10_000,
            risk_per_trade=0.2,
            fee_bps=0,
            slippage_bps=0,
            min_confidence_to_trade=0.5,
            max_abs_position_usd=5_000,
            breakeven_trigger_r=0.5,
            breakeven_lock_r=0.1,
            trailing_trigger_r=1.0,
            trailing_distance_r=0.5,
        )

        order = broker.rebalance_from_signal(
            _signal(Direction.LONG, expected_price=104.0, lower_band=99.0, upper_band=101.0),
            1,
        )

        self.assertIsNotNone(order)
        original_stop = broker.trade_plans["BTCUSDT"].stop_price
        broker.mark("BTCUSDT", 102.0, 2)
        raised_stop = broker.trade_plans["BTCUSDT"].stop_price
        self.assertGreater(raised_stop, original_stop)
        self.assertGreaterEqual(raised_stop, 100.0)

    def test_partial_take_profit_closes_fraction_and_keeps_plan(self) -> None:
        broker = PaperBroker(
            starting_cash=10_000,
            risk_per_trade=0.2,
            fee_bps=0,
            slippage_bps=0,
            min_confidence_to_trade=0.5,
            max_abs_position_usd=5_000,
            partial_take_profit_r=0.5,
            partial_take_profit_fraction=0.5,
        )

        order = broker.rebalance_from_signal(
            _signal(Direction.LONG, expected_price=104.0, lower_band=99.0, upper_band=101.0),
            1,
        )

        self.assertIsNotNone(order)
        partial = broker.mark("BTCUSDT", 100.6, 2)
        self.assertIsNotNone(partial)
        self.assertEqual(partial.reason, "partial_take_profit_r_hit")
        self.assertAlmostEqual(broker.positions["BTCUSDT"].quantity, 10)
        self.assertTrue(broker.trade_plans["BTCUSDT"].partial_taken)

    def test_loss_streak_cooldown_blocks_new_entries(self) -> None:
        broker = PaperBroker(
            starting_cash=10_000,
            risk_per_trade=0.2,
            fee_bps=0,
            slippage_bps=0,
            min_confidence_to_trade=0.5,
            max_abs_position_usd=5_000,
            entry_cooldown_ticks=0,
            loss_streak_limit=1,
            loss_streak_cooldown_ticks=10,
        )

        order = broker.rebalance_from_signal(
            _signal(Direction.LONG, expected_price=104.0, lower_band=99.0, upper_band=101.0),
            1,
        )
        self.assertIsNotNone(order)
        stop = broker.mark("BTCUSDT", 98.9, 2)
        self.assertIsNotNone(stop)
        blocked = broker.rebalance_from_signal(
            _signal(Direction.LONG, expected_price=104.0, lower_band=99.0, upper_band=101.0),
            3,
        )
        self.assertIsNone(blocked)
        self.assertEqual(broker.skipped_trades[-1]["reason"], "loss_streak_cooldown_active")

    def test_tiny_time_stop_loss_counts_as_scratch(self) -> None:
        broker = PaperBroker(
            starting_cash=10_000,
            risk_per_trade=0.05,
            fee_bps=0,
            slippage_bps=0,
            min_confidence_to_trade=0.5,
            max_abs_position_usd=1_000,
            time_stop_ticks=1,
            time_stop_min_r=0.10,
            min_decisive_trade_pnl=1.0,
            loss_streak_limit=1,
            loss_streak_cooldown_ticks=10,
        )

        order = broker.rebalance_from_signal(
            _signal(Direction.LONG, expected_price=104.0, lower_band=99.0, upper_band=101.0),
            1,
        )
        self.assertIsNotNone(order)
        tiny_exit = broker.mark("BTCUSDT", 99.96, 2)

        self.assertIsNotNone(tiny_exit)
        self.assertEqual(broker.performance_summary()["scratch_trades"], 1)
        self.assertEqual(broker.performance_summary()["losing_trades"], 0)
        self.assertEqual(broker.loss_streaks.get("BTCUSDT", 0), 0)

    def test_capital_guard_blocks_after_bad_session(self) -> None:
        broker = PaperBroker(
            starting_cash=10_000,
            risk_per_trade=0.2,
            fee_bps=0,
            slippage_bps=0,
            min_confidence_to_trade=0.5,
            max_abs_position_usd=5_000,
            entry_cooldown_ticks=0,
            loss_streak_limit=99,
            max_session_losses=2,
            min_session_trades_for_guard=2,
            global_cooldown_ticks=10,
        )

        first = broker.rebalance_from_signal(
            _signal(Direction.LONG, expected_price=104.0, lower_band=99.0, upper_band=101.0),
            1,
        )
        self.assertIsNotNone(first)
        self.assertIsNotNone(broker.mark("BTCUSDT", 98.9, 2))

        second = broker.rebalance_from_signal(
            _signal(Direction.LONG, expected_price=104.0, lower_band=99.0, upper_band=101.0),
            3,
        )
        self.assertIsNotNone(second)
        self.assertIsNotNone(broker.mark("BTCUSDT", 98.9, 4))

        blocked = broker.rebalance_from_signal(
            _signal(Direction.LONG, expected_price=104.0, lower_band=99.0, upper_band=101.0),
            5,
        )

        self.assertIsNone(blocked)
        self.assertEqual(broker.skipped_trades[-1]["reason"], "capital_guard_triggered")
        self.assertEqual(broker.performance_summary()["global_cooldown_until"], 15)

    def test_capital_guard_does_not_lock_profitable_session(self) -> None:
        broker = PaperBroker(
            starting_cash=10_000,
            risk_per_trade=0.2,
            fee_bps=0,
            slippage_bps=0,
            min_confidence_to_trade=0.5,
            max_abs_position_usd=5_000,
            max_session_losses=1,
            min_session_trades_for_guard=1,
            global_cooldown_ticks=10,
        )
        broker.cash = 10_025
        broker.winning_trades = 1
        broker.losing_trades = 3

        self.assertEqual(broker._capital_guard_reason(5), "")
        self.assertEqual(broker.global_cooldown_until, 0)

    def test_capital_guard_unlocks_when_pnl_recovers(self) -> None:
        broker = PaperBroker(
            starting_cash=10_000,
            risk_per_trade=0.2,
            fee_bps=0,
            slippage_bps=0,
            min_confidence_to_trade=0.5,
            max_abs_position_usd=5_000,
        )
        broker.cash = 10_001
        broker.global_cooldown_until = 20

        self.assertEqual(broker._capital_guard_reason(10), "")
        self.assertEqual(broker.global_cooldown_until, 0)


if __name__ == "__main__":
    unittest.main()
