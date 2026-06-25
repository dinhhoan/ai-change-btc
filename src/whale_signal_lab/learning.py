from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import json
from dataclasses import asdict, replace
from math import exp
from pathlib import Path
from typing import Any

from .features import clamp
from .models import Direction, Signal, utc_now
from .signals import BASE_COMPONENT_WEIGHTS


COMPONENT_KEYS = {
    "momentum": "momentum_score",
    "whale": "whale_score",
    "flow": "flow_score",
    "trend": "trend_score",
    "rsi": "rsi_score",
    "smart_money": "smart_money_score",
    "derivatives": "derivatives_score",
    "higher_tf": "higher_tf_score",
    "orderbook": "orderbook_imbalance",
    "funding": "funding_score",
}

QUALITY_FEATURE_KEYS = (
    "bias",
    "confidence",
    "abs_score",
    "aligned_momentum",
    "aligned_flow",
    "aligned_trend",
    "aligned_smart_money",
    "aligned_derivatives",
    "aligned_higher_tf",
    "aligned_orderbook",
    "aligned_funding",
    "confirmations",
    "opposing_confirmations",
    "rsi_stretch",
    "volatility_penalty",
    "spread_penalty",
    "shock_risk",
)


class SignalLearner:
    def __init__(
        self,
        log_path: str,
        state_path: str,
        enabled: bool = True,
        outcome_horizon_ticks: int = 12,
        min_abs_return: float = 0.0008,
        learning_rate: float = 0.08,
        quality_min_probability: float = 0.58,
        quality_min_expectancy_r: float = 0.04,
        quality_warmup_trades: int = 20,
    ) -> None:
        self.log_path = Path(log_path)
        self.state_path = Path(state_path)
        self.enabled = enabled
        self.outcome_horizon_ticks = max(1, outcome_horizon_ticks)
        self.min_abs_return = max(0.0, min_abs_return)
        self.learning_rate = max(0.0, min(0.5, learning_rate))
        self.quality_min_probability = clamp(quality_min_probability, 0.50, 0.90)
        self.quality_min_expectancy_r = clamp(quality_min_expectancy_r, -0.50, 1.50)
        self.quality_warmup_trades = max(0, quality_warmup_trades)
        self.pending: list[dict[str, Any]] = []
        self.component_edges = {name: 0.0 for name in BASE_COMPONENT_WEIGHTS}
        self.quality_weights = {name: 0.0 for name in QUALITY_FEATURE_KEYS}
        self.quality_bias = 0.0
        self.quality_samples = 0
        self.resolved = 0
        self.wins = 0
        self.losses = 0
        self.scratches = 0
        self._load()

    def component_weights(self) -> dict[str, float]:
        adjusted = {}
        for name, base_weight in BASE_COMPONENT_WEIGHTS.items():
            edge = clamp(self.component_edges.get(name, 0.0), -0.45, 0.45)
            adjusted[name] = base_weight * (1.0 + edge)
        total = sum(adjusted.values()) or 1.0
        base_total = sum(BASE_COMPONENT_WEIGHTS.values())
        return {name: value / total * base_total for name, value in adjusted.items()}

    def observe_prices(self, marks: dict[str, float], tick: int) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        resolved: list[dict[str, Any]] = []
        still_pending: list[dict[str, Any]] = []
        for item in self.pending:
            if tick - int(item["entry_tick"]) < self.outcome_horizon_ticks:
                still_pending.append(item)
                continue
            current_price = marks.get(str(item["symbol"]))
            if current_price is None:
                still_pending.append(item)
                continue
            outcome = self._resolve(item, float(current_price), tick)
            resolved.append(outcome)
            self._log({"type": "outcome", **outcome})
        self.pending = still_pending
        if resolved:
            self._save()
        return resolved

    def apply_quality_gate(self, signal: Signal) -> Signal:
        if not self.enabled or signal.direction == Direction.FLAT:
            return signal

        quality = self.predict_quality(signal)
        components = {
            **signal.components,
            "ml_win_probability": round(float(quality["probability"]), 4),
            "ml_heuristic_probability": round(float(quality["heuristic_probability"]), 4),
            "ml_model_probability": round(float(quality["model_probability"]), 4),
            "ml_expectancy_r": round(float(quality["expectancy_r"]), 4),
            "ml_min_probability": round(float(quality["min_probability"]), 4),
            "ml_min_expectancy_r": round(float(quality["min_expectancy_r"]), 4),
            "ml_sample_count": float(self.quality_samples),
        }
        accepted = (
            float(quality["probability"]) >= float(quality["min_probability"])
            and float(quality["expectancy_r"]) >= float(quality["min_expectancy_r"])
        )
        components["ml_gate_passed"] = 1.0 if accepted else 0.0
        suffix = (
            f"ml_gate={'passed' if accepted else 'blocked'}: "
            f"p={float(quality['probability']):.1%}, "
            f"expectancy={float(quality['expectancy_r']):+.2f}R, "
            f"samples={self.quality_samples}"
        )
        if accepted:
            return replace(signal, components=components, rationale=f"{signal.rationale} | {suffix}")
        return replace(
            signal,
            direction=Direction.FLAT,
            confidence=min(signal.confidence, round(float(quality["probability"]), 4)),
            components=components,
            rationale=f"{signal.rationale} | {suffix}",
        )

    def predict_quality(self, signal: Signal) -> dict[str, float]:
        features = self._quality_features(signal)
        model_probability = self._quality_model_probability(features)
        heuristic_probability = self._heuristic_probability(signal)
        if self.quality_samples < self.quality_warmup_trades:
            probability = heuristic_probability
        else:
            probability = (model_probability * 0.65) + (heuristic_probability * 0.35)
        probability = clamp(probability, 0.01, 0.99)
        reward_r = self._component_float(signal.components, "planned_rr", 1.6)
        reward_r = clamp(reward_r, 1.0, 3.5)
        expectancy_r = (probability * reward_r) - (1.0 - probability)
        min_probability = self.quality_min_probability
        if self.quality_samples < self.quality_warmup_trades:
            min_probability += 0.02
        return {
            "probability": probability,
            "heuristic_probability": heuristic_probability,
            "model_probability": model_probability,
            "expectancy_r": expectancy_r,
            "min_probability": clamp(min_probability, 0.50, 0.90),
            "min_expectancy_r": self.quality_min_expectancy_r,
        }

    def observe_signals(self, signals: list[Signal], tick: int) -> None:
        if not self.enabled:
            return
        for signal in signals:
            record = {
                "type": "decision",
                "id": f"{tick}:{signal.symbol}:{signal.generated_at.timestamp()}",
                "tick": tick,
                "timestamp": signal.generated_at.isoformat(),
                "symbol": signal.symbol,
                "direction": signal.direction,
                "price": signal.price,
                "score": signal.score,
                "confidence": signal.confidence,
                "components": signal.components,
                "rationale": signal.rationale,
            }
            self._log(record)
            if signal.direction != Direction.FLAT:
                already_pending = any(
                    str(item.get("symbol")) == signal.symbol and str(item.get("direction")) == str(signal.direction)
                    for item in self.pending
                )
                if already_pending:
                    continue
                self.pending.append(
                    {
                        "id": record["id"],
                        "entry_tick": tick,
                        "entry_time": signal.generated_at.isoformat(),
                        "symbol": signal.symbol,
                        "direction": signal.direction,
                        "entry_price": signal.price,
                        "score": signal.score,
                        "confidence": signal.confidence,
                        "components": signal.components,
                    }
                )
        self._save()

    def summary(self) -> dict[str, Any]:
        total = self.wins + self.losses
        return {
            "enabled": self.enabled,
            "pending": len(self.pending),
            "resolved": self.resolved,
            "wins": self.wins,
            "losses": self.losses,
            "scratches": self.scratches,
            "win_rate": self.wins / total if total else 0.0,
            "component_edges": {name: round(value, 4) for name, value in self.component_edges.items()},
            "component_weights": {name: round(value, 4) for name, value in self.component_weights().items()},
            "quality_model": {
                "samples": self.quality_samples,
                "min_probability": round(self.quality_min_probability, 4),
                "min_expectancy_r": round(self.quality_min_expectancy_r, 4),
                "warmup_trades": self.quality_warmup_trades,
                "bias": round(self.quality_bias, 4),
                "weights": {name: round(value, 4) for name, value in self.quality_weights.items()},
            },
            "log_path": str(self.log_path),
        }

    def _resolve(self, item: dict[str, Any], current_price: float, tick: int) -> dict[str, Any]:
        entry_price = float(item["entry_price"])
        raw_return = (current_price - entry_price) / entry_price if entry_price else 0.0
        direction = Direction(str(item["direction"]))
        direction_sign = 1.0 if direction == Direction.LONG else -1.0
        signed_return = raw_return * direction_sign
        if signed_return > self.min_abs_return:
            label = 1
            self.wins += 1
        elif signed_return < -self.min_abs_return:
            label = -1
            self.losses += 1
        else:
            label = 0
            self.scratches += 1
        self.resolved += 1
        if label:
            self._update_edges(item, direction_sign, label)
            self._update_quality_model(item, label)
        return {
            "id": item["id"],
            "entry_tick": item["entry_tick"],
            "exit_tick": tick,
            "symbol": item["symbol"],
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": current_price,
            "raw_return": raw_return,
            "signed_return": signed_return,
            "label": label,
            "components": item["components"],
            "component_edges": dict(self.component_edges),
            "resolved_at": utc_now().isoformat(),
        }

    def _update_edges(self, item: dict[str, Any], direction_sign: float, label: int) -> None:
        components = item.get("components", {})
        for name, key in COMPONENT_KEYS.items():
            value = float(components.get(key, 0.0) or 0.0)
            if abs(value) < 0.08:
                continue
            alignment = clamp(direction_sign * value, -1.0, 1.0)
            delta = self.learning_rate * label * alignment
            self.component_edges[name] = clamp(self.component_edges.get(name, 0.0) + delta, -0.45, 0.45)

    def _update_quality_model(self, item: dict[str, Any], label: int) -> None:
        signal = Signal(
            symbol=str(item["symbol"]),
            direction=Direction(str(item["direction"])),
            confidence=float(item.get("confidence", 0.0) or 0.0),
            score=float(item.get("score", 0.0) or 0.0),
            price=float(item.get("entry_price", 0.0) or 0.0),
            horizon_sec=0,
            components=dict(item.get("components", {})),
            rationale="learner_replay",
            expected_path=[],
            generated_at=utc_now(),
        )
        features = self._quality_features(signal)
        prediction = self._quality_model_probability(features)
        target = 1.0 if label > 0 else 0.0
        error = target - prediction
        step = min(0.12, max(0.01, self.learning_rate * 0.75))
        self.quality_bias = clamp(self.quality_bias + step * error, -3.0, 3.0)
        for name, value in features.items():
            if name == "bias":
                continue
            self.quality_weights[name] = clamp(
                self.quality_weights.get(name, 0.0) + step * error * value,
                -3.0,
                3.0,
            )
        self.quality_samples += 1

    def _quality_features(self, signal: Signal) -> dict[str, float]:
        side = 1.0 if signal.direction == Direction.LONG else -1.0
        components = signal.components
        positive_votes = self._component_float(components, "positive_votes", 0.0)
        negative_votes = self._component_float(components, "negative_votes", 0.0)
        aligned_votes = positive_votes if side > 0 else negative_votes
        opposing_votes = negative_votes if side > 0 else positive_votes
        rsi = self._component_float(components, "rsi", 50.0)
        spread_bps = self._component_float(components, "spread_bps", 0.0)
        return {
            "bias": 1.0,
            "confidence": clamp((signal.confidence - 0.50) * 2.0, -1.0, 1.0),
            "abs_score": clamp((abs(signal.score) - 0.20) * 4.0, -1.0, 1.0),
            "aligned_momentum": clamp(side * self._component_float(components, "momentum_score", 0.0), -1.0, 1.0),
            "aligned_flow": clamp(side * self._component_float(components, "flow_score", 0.0), -1.0, 1.0),
            "aligned_trend": clamp(side * self._component_float(components, "trend_score", 0.0), -1.0, 1.0),
            "aligned_smart_money": clamp(side * self._component_float(components, "smart_money_score", 0.0), -1.0, 1.0),
            "aligned_derivatives": clamp(side * self._component_float(components, "derivatives_score", 0.0), -1.0, 1.0),
            "aligned_higher_tf": clamp(side * self._component_float(components, "higher_tf_score", 0.0), -1.0, 1.0),
            "aligned_orderbook": clamp(side * self._component_float(components, "orderbook_imbalance", 0.0), -1.0, 1.0),
            "aligned_funding": clamp(side * self._component_float(components, "funding_score", 0.0), -1.0, 1.0),
            "confirmations": clamp(aligned_votes / 6.0, 0.0, 1.0),
            "opposing_confirmations": clamp(opposing_votes / 3.0, 0.0, 1.0),
            "rsi_stretch": clamp(abs(rsi - 50.0) / 35.0, 0.0, 1.0),
            "volatility_penalty": clamp(self._component_float(components, "volatility_penalty", 0.0) / 0.03, 0.0, 1.0),
            "spread_penalty": clamp(spread_bps / 4.0, 0.0, 1.0),
            "shock_risk": clamp(self._component_float(components, "shock_risk", 0.0), 0.0, 1.0),
        }

    def _quality_model_probability(self, features: dict[str, float]) -> float:
        logit = self.quality_bias
        for name, value in features.items():
            if name == "bias":
                continue
            logit += self.quality_weights.get(name, 0.0) * value
        return self._sigmoid(logit)

    def _heuristic_probability(self, signal: Signal) -> float:
        components = signal.components
        side = 1.0 if signal.direction == Direction.LONG else -1.0
        positive_votes = self._component_float(components, "positive_votes", 0.0)
        negative_votes = self._component_float(components, "negative_votes", 0.0)
        aligned_votes = positive_votes if side > 0 else negative_votes
        opposing_votes = negative_votes if side > 0 else positive_votes
        aligned_flow = side * self._component_float(components, "flow_score", 0.0)
        aligned_smart = side * self._component_float(components, "smart_money_score", 0.0)
        aligned_derivatives = side * self._component_float(components, "derivatives_score", 0.0)
        aligned_higher_tf = side * self._component_float(components, "higher_tf_score", 0.0)
        aligned_orderbook = side * self._component_float(components, "orderbook_imbalance", 0.0)
        probability = (
            0.48
            + (signal.confidence - 0.50) * 0.55
            + max(0.0, abs(signal.score) - 0.20) * 0.70
            + aligned_votes * 0.028
            - opposing_votes * 0.08
            + max(0.0, aligned_flow) * 0.035
            + max(0.0, aligned_smart) * 0.025
            + max(0.0, aligned_derivatives) * 0.030
            + max(0.0, aligned_higher_tf) * 0.025
            + max(0.0, aligned_orderbook) * 0.020
            - self._component_float(components, "volatility_penalty", 0.0) * 1.8
            - self._component_float(components, "shock_risk", 0.0) * 0.12
            - clamp(self._component_float(components, "spread_bps", 0.0) / 4.0, 0.0, 1.0) * 0.04
        )
        return clamp(probability, 0.05, 0.95)

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self.state_path.read_text, encoding="utf-8")
                payload_text = future.result(timeout=1.0)
            payload = json.loads(payload_text)
        except FutureTimeoutError:
            return
        except (OSError, json.JSONDecodeError):
            return
        self.component_edges.update(payload.get("component_edges", {}))
        self.quality_weights.update(payload.get("quality_weights", {}))
        self.quality_bias = float(payload.get("quality_bias", 0.0) or 0.0)
        self.quality_samples = int(payload.get("quality_samples", 0) or 0)
        self.pending = list(payload.get("pending", []))[-500:]
        self.resolved = int(payload.get("resolved", 0))
        self.wins = int(payload.get("wins", 0))
        self.losses = int(payload.get("losses", 0))
        self.scratches = int(payload.get("scratches", 0))

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "component_edges": self.component_edges,
            "quality_weights": self.quality_weights,
            "quality_bias": self.quality_bias,
            "quality_samples": self.quality_samples,
            "pending": self.pending[-500:],
            "resolved": self.resolved,
            "wins": self.wins,
            "losses": self.losses,
            "scratches": self.scratches,
            "updated_at": utc_now().isoformat(),
        }
        self.state_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def _log(self, record: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=_json_default, ensure_ascii=True) + "\n")

    @staticmethod
    def _component_float(components: dict[str, Any], key: str, default: float = 0.0) -> float:
        try:
            return float(components.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _sigmoid(value: float) -> float:
        value = clamp(value, -30.0, 30.0)
        return 1.0 / (1.0 + exp(-value))


def _json_default(value: object) -> object:
    if isinstance(value, Direction):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return str(value)
