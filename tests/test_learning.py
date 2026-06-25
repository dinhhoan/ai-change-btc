from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whale_signal_lab.learning import SignalLearner
from whale_signal_lab.models import Direction, Signal, utc_now


class SignalLearnerTest(unittest.TestCase):
    def test_learner_rewards_components_that_align_with_winning_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            learner = SignalLearner(
                log_path=str(Path(tmpdir) / "decisions.jsonl"),
                state_path=str(Path(tmpdir) / "state.json"),
                outcome_horizon_ticks=1,
                min_abs_return=0.0001,
                learning_rate=0.10,
            )
            signal = Signal(
                symbol="BTCUSDT",
                direction=Direction.LONG,
                confidence=0.7,
                score=0.4,
                price=100.0,
                horizon_sec=60,
                components={
                    "momentum_score": 0.5,
                    "derivatives_score": 0.4,
                    "smart_money_score": -0.4,
                },
                rationale="test",
                expected_path=[],
                generated_at=utc_now(),
            )

            learner.observe_signals([signal], tick=1)
            outcomes = learner.observe_prices({"BTCUSDT": 101.0}, tick=2)

            self.assertEqual(len(outcomes), 1)
            self.assertEqual(learner.wins, 1)
            self.assertGreater(learner.component_edges["momentum"], 0.0)
            self.assertGreater(learner.component_edges["derivatives"], 0.0)
            self.assertLess(learner.component_edges["smart_money"], 0.0)

    def test_learner_deduplicates_same_symbol_same_direction_while_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            learner = SignalLearner(
                log_path=str(Path(tmpdir) / "decisions.jsonl"),
                state_path=str(Path(tmpdir) / "state.json"),
                outcome_horizon_ticks=4,
            )
            signal = Signal(
                symbol="BTCUSDT",
                direction=Direction.SHORT,
                confidence=0.7,
                score=-0.4,
                price=100.0,
                horizon_sec=60,
                components={"flow_score": -0.6},
                rationale="test",
                expected_path=[],
                generated_at=utc_now(),
            )

            learner.observe_signals([signal], tick=1)
            learner.observe_signals([signal], tick=2)

            self.assertEqual(len(learner.pending), 1)

    def test_quality_gate_blocks_low_expectancy_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            learner = SignalLearner(
                log_path=str(Path(tmpdir) / "decisions.jsonl"),
                state_path=str(Path(tmpdir) / "state.json"),
                quality_min_probability=0.62,
                quality_min_expectancy_r=0.10,
                quality_warmup_trades=0,
            )
            signal = Signal(
                symbol="BTCUSDT",
                direction=Direction.LONG,
                confidence=0.58,
                score=0.23,
                price=100.0,
                horizon_sec=60,
                components={
                    "flow_score": -0.2,
                    "derivatives_score": -0.2,
                    "higher_tf_score": -0.1,
                    "positive_votes": 1,
                    "negative_votes": 2,
                    "volatility_penalty": 0.02,
                    "spread_bps": 3.5,
                },
                rationale="test",
                expected_path=[],
                generated_at=utc_now(),
            )

            gated = learner.apply_quality_gate(signal)

            self.assertEqual(gated.direction, Direction.FLAT)
            self.assertEqual(gated.components["ml_gate_passed"], 0.0)
            self.assertIn("ml_gate=blocked", gated.rationale)

    def test_quality_model_learns_from_resolved_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            learner = SignalLearner(
                log_path=str(Path(tmpdir) / "decisions.jsonl"),
                state_path=str(Path(tmpdir) / "state.json"),
                outcome_horizon_ticks=1,
                min_abs_return=0.0001,
                quality_warmup_trades=0,
            )
            signal = Signal(
                symbol="BTCUSDT",
                direction=Direction.LONG,
                confidence=0.7,
                score=0.35,
                price=100.0,
                horizon_sec=60,
                components={
                    "flow_score": 0.5,
                    "derivatives_score": 0.4,
                    "higher_tf_score": 0.3,
                    "positive_votes": 5,
                    "negative_votes": 0,
                },
                rationale="test",
                expected_path=[],
                generated_at=utc_now(),
            )

            learner.observe_signals([signal], tick=1)
            learner.observe_prices({"BTCUSDT": 101.0}, tick=2)

            self.assertEqual(learner.quality_samples, 1)
            self.assertGreater(learner.quality_weights["aligned_flow"], 0.0)


if __name__ == "__main__":
    unittest.main()
