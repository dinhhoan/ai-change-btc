from __future__ import annotations

from math import tanh

from .features import clamp
from .models import Direction, FeatureSnapshot, PricePathPoint, Signal, utc_now


BASE_COMPONENT_WEIGHTS = {
    "momentum": 0.18,
    "whale": 0.16,
    "flow": 0.10,
    "trend": 0.09,
    "rsi": 0.05,
    "smart_money": 0.14,
    "derivatives": 0.13,
    "higher_tf": 0.08,
    "orderbook": 0.04,
    "funding": 0.03,
}

CANDIDATE_SCORE_THRESHOLD = 0.22
CANDIDATE_CONFIDENCE_THRESHOLD = 0.58
MIN_CONFIRMATIONS = 4
HIGH_PRECISION_SCORE_THRESHOLD = 0.24
HIGH_PRECISION_CONFIDENCE_THRESHOLD = 0.59
MAX_OPPOSING_CONFIRMATIONS = 0
DEGRADED_DERIVATIVES_SCORE_THRESHOLD = 0.28
DEGRADED_DERIVATIVES_CONFIDENCE_THRESHOLD = 0.58
PRICE_PATH_EDGE_SCALE = 0.02
MAX_DERIVATIVES_SIGNAL_AGE_SEC = 900.0
MAX_SMART_SIGNAL_AGE_SEC = 900.0
CHOP_TREND_THRESHOLD = 0.02
CHOP_FLOW_THRESHOLD = 0.12
TREND_CONFIRM_THRESHOLD = 0.03
FLOW_CONFIRM_THRESHOLD = 0.12
MOMENTUM_CONFIRM_THRESHOLD = 0.05
SMART_CONFIRM_THRESHOLD = 0.18
DERIVATIVES_CONFIRM_THRESHOLD = 0.08
HIGHER_TF_CONFIRM_THRESHOLD = 0.08
ORDERBOOK_CONFIRM_THRESHOLD = 0.12
MAX_SPREAD_BPS = 4.0
ELEVATED_VOLATILITY_PENALTY = 0.008
HIGH_VOLATILITY_PENALTY = 0.014
VOLATILE_EXHAUSTION_RSI_LONG = 64.0
VOLATILE_EXHAUSTION_RSI_SHORT = 40.0


class SignalEngine:
    def __init__(
        self,
        whale_threshold_usd: float = 1_000_000.0,
        horizon_sec: int = 900,
        component_weights: dict[str, float] | None = None,
    ) -> None:
        self.whale_threshold_usd = max(1.0, whale_threshold_usd)
        self.horizon_sec = horizon_sec
        self.component_weights = dict(component_weights or BASE_COMPONENT_WEIGHTS)

    def set_component_weights(self, weights: dict[str, float]) -> None:
        self.component_weights = dict(weights)

    def evaluate(self, features: FeatureSnapshot) -> Signal:
        if features.price <= 0:
            return self._flat(features, "Waiting for first market price.")

        momentum_score = clamp(features.momentum_pct * 35.0, -1.5, 1.5)
        whale_score = tanh(features.whale_net_usd / self.whale_threshold_usd)
        flow_score = clamp((features.buy_pressure - 0.5) * 2.0, -1.0, 1.0)
        trend_score = clamp(features.trend_score, -1.0, 1.0)
        rsi_score = clamp((features.rsi - 50.0) / 25.0, -1.0, 1.0)
        smart_money_score = clamp(features.smart_money_score, -1.0, 1.0)
        derivatives_score = clamp(features.derivatives_score, -1.0, 1.0)
        higher_tf_score = clamp(
            (features.higher_tf_trend_score * 0.72) + clamp(features.higher_tf_momentum_pct * 120.0, -1.0, 1.0) * 0.28,
            -1.0,
            1.0,
        )
        orderbook_score = clamp(features.orderbook_imbalance, -1.0, 1.0)
        funding_score = clamp(-features.funding_rate * 350.0, -1.0, 1.0)
        volatility_penalty = clamp(features.realized_volatility * 20.0, 0.0, 0.7)
        component_scores = {
            "momentum": momentum_score,
            "whale": whale_score,
            "flow": flow_score,
            "trend": trend_score,
            "rsi": rsi_score,
            "smart_money": smart_money_score,
            "derivatives": derivatives_score,
            "higher_tf": higher_tf_score,
            "orderbook": orderbook_score,
            "funding": funding_score,
        }
        raw_score = sum(self.component_weights.get(name, 0.0) * value for name, value in component_scores.items())
        confidence = clamp(0.50 + abs(raw_score) * 0.32 - volatility_penalty * 0.25, 0.0, 0.95)

        positive_votes, negative_votes = self._confirmation_counts(features, component_scores)

        if raw_score > CANDIDATE_SCORE_THRESHOLD and confidence >= CANDIDATE_CONFIDENCE_THRESHOLD:
            candidate = Direction.LONG
        elif raw_score < -CANDIDATE_SCORE_THRESHOLD and confidence >= CANDIDATE_CONFIDENCE_THRESHOLD:
            candidate = Direction.SHORT
        else:
            candidate = Direction.FLAT

        direction, gate_reasons = self._apply_gate(
            candidate,
            positive_votes,
            negative_votes,
            features,
            momentum_score,
            flow_score,
            trend_score,
            features.rsi,
            volatility_penalty,
            raw_score,
            confidence,
        )
        aligned_votes = positive_votes if candidate == Direction.LONG else negative_votes
        opposing_votes = negative_votes if candidate == Direction.LONG else positive_votes
        degraded_derivatives_mode = self._stale_derivatives_fallback_allowed(
            candidate,
            aligned_votes,
            opposing_votes,
            features,
            flow_score,
            orderbook_score,
            raw_score,
            confidence,
        )
        derivatives_fresh = features.derivatives_age_sec <= MAX_DERIVATIVES_SIGNAL_AGE_SEC
        setup_readiness = self._setup_readiness(
            candidate,
            aligned_votes,
            opposing_votes,
            raw_score,
            confidence,
            volatility_penalty,
            gate_reasons,
        )

        components = {
            "momentum_score": round(momentum_score, 4),
            "whale_score": round(whale_score, 4),
            "flow_score": round(flow_score, 4),
            "trend_score": round(trend_score, 4),
            "rsi_score": round(rsi_score, 4),
            "smart_money_score": round(smart_money_score, 4),
            "smart_money_sync": round(features.smart_money_sync, 4),
            "smart_money_wallets": float(features.smart_money_wallets),
            "smart_money_usd": round(features.smart_money_usd, 2),
            "smart_money_age_sec": round(features.smart_money_age_sec, 1),
            "derivatives_score": round(derivatives_score, 4),
            "global_long_short_ratio": round(features.global_long_short_ratio, 4),
            "top_long_short_ratio": round(features.top_long_short_ratio, 4),
            "taker_buy_sell_ratio": round(features.taker_buy_sell_ratio, 4),
            "open_interest_value": round(features.open_interest_value, 2),
            "open_interest_change_pct": round(features.open_interest_change_pct, 4),
            "derivatives_age_sec": round(features.derivatives_age_sec, 1),
            "derivatives_fresh": 1.0 if derivatives_fresh else 0.0,
            "degraded_derivatives_mode": 1.0
            if degraded_derivatives_mode and direction == candidate and candidate != Direction.FLAT
            else 0.0,
            "higher_tf_score": round(higher_tf_score, 4),
            "higher_tf_trend_score": round(features.higher_tf_trend_score, 4),
            "higher_tf_momentum_pct": round(features.higher_tf_momentum_pct, 6),
            "regime_score": round(features.regime_score, 4),
            "orderbook_imbalance": round(features.orderbook_imbalance, 4),
            "spread_bps": round(features.spread_bps, 4),
            "orderbook_age_sec": round(features.orderbook_age_sec, 1),
            "funding_rate": round(features.funding_rate, 8),
            "funding_score": round(funding_score, 4),
            "funding_age_sec": round(features.funding_age_sec, 1),
            "volatility_penalty": round(volatility_penalty, 4),
            "realized_volatility": round(features.realized_volatility, 6),
            "shock_risk": 1.0
            if self._is_exhaustion_chase(candidate, momentum_score, features.rsi, volatility_penalty)
            else 0.0,
            "whale_net_usd": round(features.whale_net_usd, 2),
            "rsi": round(features.rsi, 2),
            "ema_fast": round(features.ema_fast, 8),
            "ema_slow": round(features.ema_slow, 8),
            "positive_votes": float(positive_votes),
            "negative_votes": float(negative_votes),
            "gate_passed": 1.0 if direction == candidate and candidate != Direction.FLAT else 0.0,
            "setup_direction": self._direction_value(candidate),
            "setup_readiness": round(setup_readiness, 4),
            "gate_blocker_count": float(len(gate_reasons)),
        }
        gate_status = "passed" if components["gate_passed"] else "blocked"
        if candidate == Direction.FLAT:
            gate_status = "neutral"
            gate_reasons = ["score/confidence below entry threshold"]
        rationale = (
            f"momentum={features.momentum_pct:.3%}, "
            f"buy_pressure={features.buy_pressure:.2f}, "
            f"whale_net_usd={features.whale_net_usd:,.0f}, "
            f"smart_group={smart_money_score:+.2f}/{features.smart_money_wallets}w, "
            f"ls={derivatives_score:+.2f} "
            f"(global={features.global_long_short_ratio:.2f}, top={features.top_long_short_ratio:.2f}), "
            f"oi={features.open_interest_change_pct:+.2%}, "
            f"htf={higher_tf_score:+.2f}/{features.market_regime}, "
            f"book={orderbook_score:+.2f}/{features.spread_bps:.1f}bps, "
            f"fund={features.funding_rate:+.4%}, "
            f"age(smart/deriv)={features.smart_money_age_sec:.0f}/{features.derivatives_age_sec:.0f}s, "
            f"trend={trend_score:+.2f}, "
            f"rsi={features.rsi:.1f}, "
            f"vol={features.realized_volatility:.3%}, "
            f"gate={gate_status}: {', '.join(gate_reasons)}"
        )
        return Signal(
            symbol=features.symbol,
            direction=direction,
            confidence=round(confidence, 4),
            score=round(raw_score, 4),
            price=features.price,
            horizon_sec=self.horizon_sec,
            components=components,
            rationale=rationale,
            expected_path=self._path(features.price, raw_score, confidence, features.realized_volatility),
            generated_at=utc_now(),
        )

    def _apply_gate(
        self,
        candidate: Direction,
        positive_votes: int,
        negative_votes: int,
        features: FeatureSnapshot,
        momentum_score: float,
        flow_score: float,
        trend_score: float,
        rsi: float,
        volatility_penalty: float,
        raw_score: float,
        confidence: float,
    ) -> tuple[Direction, list[str]]:
        if candidate == Direction.FLAT:
            return Direction.FLAT, []

        reasons: list[str] = []
        derivatives_fresh = features.derivatives_age_sec <= MAX_DERIVATIVES_SIGNAL_AGE_SEC
        if features.spread_bps > MAX_SPREAD_BPS:
            reasons.append("spread too wide for clean execution")
        aligned_votes = positive_votes if candidate == Direction.LONG else negative_votes
        opposing_votes = negative_votes if candidate == Direction.LONG else positive_votes
        degraded_derivatives_mode = self._stale_derivatives_fallback_allowed(
            candidate,
            aligned_votes,
            opposing_votes,
            features,
            flow_score,
            clamp(features.orderbook_imbalance, -1.0, 1.0),
            raw_score,
            confidence,
        )
        if features.market_regime == "chop" and (abs(raw_score) < 0.30 or aligned_votes < 5):
            reasons.append("chop regime requires exceptional edge")
        if features.market_regime == "transition" and (abs(raw_score) < 0.28 or aligned_votes < MIN_CONFIRMATIONS):
            reasons.append("transition regime needs cleaner confirmation")
        if features.market_regime == "high_volatility" and not degraded_derivatives_mode and (
            abs(raw_score) < 0.30 or aligned_votes < MIN_CONFIRMATIONS or opposing_votes > 1
        ):
            reasons.append("volatile regime needs A+ edge")
        if features.market_regime in {"volatile_pump", "volatile_flush"} and (
            abs(raw_score) < 0.34 or aligned_votes < MIN_CONFIRMATIONS or opposing_votes > 0
        ):
            reasons.append("volatile regime needs A+ edge")
        if volatility_penalty >= 0.62:
            reasons.append("volatility regime too noisy")
        spike_score_floor = 0.30 if features.market_regime == "high_volatility" else 0.34
        if volatility_penalty >= HIGH_VOLATILITY_PENALTY and abs(raw_score) < spike_score_floor:
            reasons.append("volatility spike needs stronger directional edge")
        if self._is_exhaustion_chase(candidate, momentum_score, rsi, volatility_penalty):
            if candidate == Direction.LONG:
                reasons.append("late LONG after volatile pump")
            else:
                reasons.append("late SHORT after volatile flush")
        if abs(trend_score) < CHOP_TREND_THRESHOLD and abs(flow_score) < CHOP_FLOW_THRESHOLD:
            reasons.append("market is too choppy")
        if abs(features.smart_money_score) >= SMART_CONFIRM_THRESHOLD and features.smart_money_sync < 0.72:
            reasons.append("smart-money move is not synchronized enough")
        if not derivatives_fresh and not degraded_derivatives_mode:
            reasons.append("derivatives 5m is stale")
        if features.smart_money_wallets > 0 and features.smart_money_age_sec > MAX_SMART_SIGNAL_AGE_SEC:
            reasons.append("smart-money cluster is stale")
        if 180 < features.orderbook_age_sec < 9999:
            reasons.append("orderbook depth is stale")
        if 1800 < features.funding_age_sec < 9999:
            reasons.append("funding data is stale")
        if abs(raw_score) < HIGH_PRECISION_SCORE_THRESHOLD:
            reasons.append("score below high-precision entry threshold")
        if confidence < HIGH_PRECISION_CONFIDENCE_THRESHOLD:
            reasons.append("confidence below high-precision entry threshold")
        if (
            abs(features.smart_money_score) >= SMART_CONFIRM_THRESHOLD
            and abs(features.derivatives_score) >= DERIVATIVES_CONFIRM_THRESHOLD
            and derivatives_fresh
            and features.smart_money_score * features.derivatives_score < 0
            and abs(raw_score) < 0.35
        ):
            reasons.append("smart money and derivatives disagree")

        if candidate == Direction.LONG:
            if features.buy_pressure < 0.56:
                reasons.append("LONG lacks strong tape pressure")
            if positive_votes < MIN_CONFIRMATIONS:
                reasons.append(f"needs {MIN_CONFIRMATIONS} bullish confirmations")
            if negative_votes > MAX_OPPOSING_CONFIRMATIONS:
                reasons.append("too many bearish confirmations for LONG")
            if trend_score < -0.12:
                reasons.append("EMA trend conflicts with LONG")
            if flow_score < 0.08:
                reasons.append("buy pressure does not confirm LONG")
            if derivatives_fresh and features.taker_buy_sell_ratio < 1.03:
                reasons.append("taker flow does not confirm LONG")
            if features.higher_tf_trend_score < -0.02:
                reasons.append("higher timeframe conflicts with LONG")
            if features.orderbook_imbalance < -0.02:
                reasons.append("orderbook depth conflicts with LONG")
            if derivatives_fresh and features.derivatives_score < -0.08:
                reasons.append("derivatives conflict with LONG")
            if features.market_regime in {"trend_down", "volatile_flush"} and features.higher_tf_trend_score < 0:
                reasons.append("market regime conflicts with LONG")
            if derivatives_fresh and features.funding_rate > 0.00025 and features.global_long_short_ratio > 2.0:
                reasons.append("positive funding makes LONG too crowded")
            if derivatives_fresh and features.global_long_short_ratio > 2.20 and features.derivatives_score < 0.05:
                reasons.append("crowded longs without derivatives edge")
            if derivatives_fresh and features.top_long_short_ratio < 0.92:
                reasons.append("top trader positioning conflicts with LONG")
            if rsi >= 78.0:
                reasons.append("RSI is overheated")
            if rsi >= 68.0 and momentum_score < 0.18:
                reasons.append("late LONG after stretch")
        elif candidate == Direction.SHORT:
            if features.buy_pressure > 0.44:
                reasons.append("SHORT lacks strong sell tape")
            if negative_votes < MIN_CONFIRMATIONS:
                reasons.append(f"needs {MIN_CONFIRMATIONS} bearish confirmations")
            if positive_votes > MAX_OPPOSING_CONFIRMATIONS:
                reasons.append("too many bullish confirmations for SHORT")
            if trend_score > 0.12:
                reasons.append("EMA trend conflicts with SHORT")
            if flow_score > -0.08:
                reasons.append("sell pressure does not confirm SHORT")
            if derivatives_fresh and features.taker_buy_sell_ratio > 0.97:
                reasons.append("taker flow does not confirm SHORT")
            if features.higher_tf_trend_score > 0.02:
                reasons.append("higher timeframe conflicts with SHORT")
            if features.orderbook_imbalance > 0.02:
                reasons.append("orderbook depth conflicts with SHORT")
            if derivatives_fresh and features.derivatives_score > 0.08:
                reasons.append("derivatives conflict with SHORT")
            if features.market_regime in {"trend_up", "volatile_pump"} and features.higher_tf_trend_score > 0:
                reasons.append("market regime conflicts with SHORT")
            if derivatives_fresh and features.funding_rate < -0.00025:
                reasons.append("negative funding makes SHORT too crowded")
            if derivatives_fresh and features.top_long_short_ratio > 1.25 and features.derivatives_score > -0.12:
                reasons.append("top trader positioning conflicts with SHORT")
            if rsi <= 28.0:
                reasons.append("RSI is washed out")
            if rsi <= 36.0 and momentum_score > -0.18:
                reasons.append("late SHORT after flush")
        if (
            candidate != Direction.FLAT
            and abs(features.smart_money_score) < SMART_CONFIRM_THRESHOLD
            and (not derivatives_fresh or abs(features.derivatives_score) < DERIVATIVES_CONFIRM_THRESHOLD)
            and abs(momentum_score) < 0.18
        ):
            reasons.append("no dominant edge after independent filters")

        if reasons:
            return Direction.FLAT, reasons
        if degraded_derivatives_mode:
            return candidate, ["enough independent confirmations; reduced-size derivatives fallback"]
        return candidate, ["enough independent confirmations"]

    @staticmethod
    def _stale_derivatives_fallback_allowed(
        candidate: Direction,
        aligned_votes: int,
        opposing_votes: int,
        features: FeatureSnapshot,
        flow_score: float,
        orderbook_score: float,
        raw_score: float,
        confidence: float,
    ) -> bool:
        if candidate == Direction.FLAT:
            return False
        if features.derivatives_age_sec <= MAX_DERIVATIVES_SIGNAL_AGE_SEC:
            return False
        live_book = features.orderbook_age_sec <= 180 and features.spread_bps <= MAX_SPREAD_BPS
        if not live_book:
            return False
        side = 1.0 if candidate == Direction.LONG else -1.0
        orderbook_aligned = side * orderbook_score >= -0.02
        flow_aligned = side * flow_score >= 0.06
        smart_aligned = side * features.smart_money_score >= SMART_CONFIRM_THRESHOLD and features.smart_money_sync >= 0.72
        higher_tf_aligned = side * features.higher_tf_trend_score >= -0.02
        return (
            abs(raw_score) >= DEGRADED_DERIVATIVES_SCORE_THRESHOLD
            and confidence >= DEGRADED_DERIVATIVES_CONFIDENCE_THRESHOLD
            and aligned_votes >= MIN_CONFIRMATIONS
            and opposing_votes <= MAX_OPPOSING_CONFIRMATIONS
            and orderbook_aligned
            and higher_tf_aligned
            and (flow_aligned or smart_aligned)
        )

    @staticmethod
    def _setup_readiness(
        candidate: Direction,
        aligned_votes: int,
        opposing_votes: int,
        raw_score: float,
        confidence: float,
        volatility_penalty: float,
        gate_reasons: list[str],
    ) -> float:
        if candidate == Direction.FLAT:
            return clamp((abs(raw_score) / CANDIDATE_SCORE_THRESHOLD) * 0.40 + confidence * 0.25, 0.0, 0.55)
        blocker_penalty = min(0.40, max(0, len(gate_reasons) - 1) * 0.055)
        readiness = (
            0.22
            + min(0.32, abs(raw_score))
            + confidence * 0.26
            + min(0.22, aligned_votes * 0.045)
            - min(0.20, opposing_votes * 0.10)
            - min(0.16, volatility_penalty * 4.0)
            - blocker_penalty
        )
        return clamp(readiness, 0.0, 1.0)

    @staticmethod
    def _direction_value(direction: Direction) -> float:
        if direction == Direction.LONG:
            return 1.0
        if direction == Direction.SHORT:
            return -1.0
        return 0.0

    @staticmethod
    def _is_exhaustion_chase(
        candidate: Direction,
        momentum_score: float,
        rsi: float,
        volatility_penalty: float,
    ) -> bool:
        if volatility_penalty < ELEVATED_VOLATILITY_PENALTY:
            return False
        if candidate == Direction.LONG:
            return rsi >= VOLATILE_EXHAUSTION_RSI_LONG and momentum_score >= 0.16
        if candidate == Direction.SHORT:
            return rsi <= VOLATILE_EXHAUSTION_RSI_SHORT and momentum_score <= -0.12
        return False

    @staticmethod
    def _confirmation_counts(features: FeatureSnapshot, component_scores: dict[str, float]) -> tuple[int, int]:
        bullish = 0
        bearish = 0

        if component_scores["momentum"] >= MOMENTUM_CONFIRM_THRESHOLD:
            bullish += 1
        elif component_scores["momentum"] <= -MOMENTUM_CONFIRM_THRESHOLD:
            bearish += 1

        if component_scores["flow"] >= FLOW_CONFIRM_THRESHOLD:
            bullish += 1
        elif component_scores["flow"] <= -FLOW_CONFIRM_THRESHOLD:
            bearish += 1

        if component_scores["trend"] >= TREND_CONFIRM_THRESHOLD:
            bullish += 1
        elif component_scores["trend"] <= -TREND_CONFIRM_THRESHOLD:
            bearish += 1

        if component_scores["whale"] >= 0.50:
            bullish += 1
        elif component_scores["whale"] <= -0.50:
            bearish += 1

        smart_fresh = features.smart_money_age_sec <= MAX_SMART_SIGNAL_AGE_SEC
        if smart_fresh and features.smart_money_sync >= 0.72:
            if component_scores["smart_money"] >= SMART_CONFIRM_THRESHOLD:
                bullish += 1
            elif component_scores["smart_money"] <= -SMART_CONFIRM_THRESHOLD:
                bearish += 1

        derivatives_fresh = features.derivatives_age_sec <= MAX_DERIVATIVES_SIGNAL_AGE_SEC
        if derivatives_fresh:
            bullish_derivatives = (
                component_scores["derivatives"] >= DERIVATIVES_CONFIRM_THRESHOLD
                and features.taker_buy_sell_ratio > 1.02
                and features.top_long_short_ratio >= 0.98
                and features.open_interest_change_pct > -0.0015
            )
            bearish_derivatives = (
                component_scores["derivatives"] <= -DERIVATIVES_CONFIRM_THRESHOLD
                and features.taker_buy_sell_ratio < 0.98
                and features.global_long_short_ratio >= 1.05
                and features.open_interest_change_pct < 0.0025
            )
            if bullish_derivatives:
                bullish += 1
            if bearish_derivatives:
                bearish += 1

        if component_scores.get("higher_tf", 0.0) >= HIGHER_TF_CONFIRM_THRESHOLD:
            bullish += 1
        elif component_scores.get("higher_tf", 0.0) <= -HIGHER_TF_CONFIRM_THRESHOLD:
            bearish += 1

        if features.orderbook_age_sec <= 180:
            if component_scores.get("orderbook", 0.0) >= ORDERBOOK_CONFIRM_THRESHOLD:
                bullish += 1
            elif component_scores.get("orderbook", 0.0) <= -ORDERBOOK_CONFIRM_THRESHOLD:
                bearish += 1

        return bullish, bearish

    def _flat(self, features: FeatureSnapshot, reason: str) -> Signal:
        return Signal(
            symbol=features.symbol,
            direction=Direction.FLAT,
            confidence=0.0,
            score=0.0,
            price=features.price,
            horizon_sec=self.horizon_sec,
            components={},
            rationale=reason,
            expected_path=[],
            generated_at=utc_now(),
        )

    def _path(self, price: float, score: float, confidence: float, volatility: float) -> list[PricePathPoint]:
        points: list[PricePathPoint] = []
        expected_return = clamp(score, -1.2, 1.2) * PRICE_PATH_EDGE_SCALE * confidence
        band = max(0.0012, volatility * 3.0)
        for fraction in (0.25, 0.50, 0.75, 1.0):
            drift = expected_return * fraction
            uncertainty = band * (fraction ** 0.5)
            expected_price = price * (1.0 + drift)
            points.append(
                PricePathPoint(
                    seconds_ahead=int(self.horizon_sec * fraction),
                    expected_price=round(expected_price, 8),
                    lower_band=round(price * (1.0 + drift - uncertainty), 8),
                    upper_band=round(price * (1.0 + drift + uncertainty), 8),
                )
            )
        return points
