from __future__ import annotations

from dataclasses import dataclass, field, replace

from .models import Direction, PaperOrder, Position, Signal, TradePlan, utc_now


@dataclass
class PaperBroker:
    starting_cash: float
    risk_per_trade: float
    fee_bps: float
    slippage_bps: float
    min_confidence_to_trade: float
    max_abs_position_usd: float
    gas_fee_usd: float = 0.0
    min_edge_cost_multiple: float = 1.25
    risk_reward_ratio: float = 3.0
    min_stop_loss_pct: float = 0.003
    target_position_notional_usd: float = 0.0
    target_margin_usd: float = 1_000.0
    max_leverage: float = 10.0
    futures_margin_mode: bool = False
    entry_cooldown_ticks: int = 6
    min_holding_ticks: int = 4
    reversal_confidence: float = 0.62
    min_forecast_rr: float = 0.78
    breakeven_trigger_r: float = 0.9
    breakeven_lock_r: float = 0.05
    trailing_trigger_r: float = 1.4
    trailing_distance_r: float = 0.75
    volatility_risk_penalty_threshold: float = 0.008
    volatility_block_penalty: float = 0.018
    high_volatility_position_scale: float = 0.50
    shock_position_scale: float = 0.35
    partial_take_profit_r: float = 0.75
    partial_take_profit_fraction: float = 0.50
    time_stop_ticks: int = 10
    time_stop_min_r: float = 0.10
    min_decisive_trade_pnl: float = 1.0
    loss_streak_limit: int = 2
    loss_streak_cooldown_ticks: int = 24
    loss_streak_position_scale: float = 0.50
    max_session_drawdown_pct: float = 0.0015
    max_session_losses: int = 2
    min_session_win_rate: float = 0.40
    min_session_trades_for_guard: int = 5
    global_cooldown_ticks: int = 24
    scout_position_scale: float = 0.25
    scout_min_confidence_to_trade: float = 0.50
    cash: float = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict)
    trade_plans: dict[str, TradePlan] = field(default_factory=dict)
    last_exit_tick: dict[str, int] = field(default_factory=dict)
    marks: dict[str, float] = field(default_factory=dict)
    orders: list[PaperOrder] = field(default_factory=list)
    realized_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    total_fees: float = 0.0
    total_gas_fees: float = 0.0
    winning_trades: int = 0
    losing_trades: int = 0
    scratch_trades: int = 0
    trade_reviews: list[dict[str, float | str | bool]] = field(default_factory=list)
    skipped_trades: list[dict[str, float | str | bool]] = field(default_factory=list)
    loss_streaks: dict[str, int] = field(default_factory=dict)
    loss_cooldown_until: dict[str, int] = field(default_factory=dict)
    global_cooldown_until: int = 0

    def __post_init__(self) -> None:
        self.cash = float(self.starting_cash)

    def mark(self, symbol: str, price: float, current_tick: int = 0) -> PaperOrder | None:
        if price > 0:
            self.marks[symbol] = price
            self._update_dynamic_trade_plan(symbol, price)
        return self._check_trade_plan(symbol, price, current_tick)

    def equity(self) -> float:
        if self.futures_margin_mode:
            return self.cash + self.unrealized_pnl()
        value = self.cash
        for symbol, position in self.positions.items():
            mark = self.marks.get(symbol, position.avg_price)
            value += position.market_value(mark)
        return value

    def unrealized_pnl(self) -> float:
        pnl = 0.0
        for symbol, position in self.positions.items():
            mark = self.marks.get(symbol, position.avg_price)
            pnl += (mark - position.avg_price) * position.quantity
        return pnl

    def performance_summary(self) -> dict[str, object]:
        equity = self.equity()
        net_pnl = equity - self.starting_cash
        closed_trades = self.winning_trades + self.losing_trades + self.scratch_trades
        decisive_trades = self.winning_trades + self.losing_trades
        win_rate = self.winning_trades / decisive_trades if decisive_trades else 0.0
        profit_factor = self.gross_profit / abs(self.gross_loss) if self.gross_loss < 0 else None
        return {
            "starting_cash": self.starting_cash,
            "equity": equity,
            "cash": self.cash,
            "net_pnl": net_pnl,
            "net_pnl_pct": (net_pnl / self.starting_cash * 100.0) if self.starting_cash else 0.0,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl(),
            "total_fees": self.total_fees,
            "total_gas_fees": self.total_gas_fees,
            "win_rate": win_rate,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "scratch_trades": self.scratch_trades,
            "closed_trades": closed_trades,
            "open_positions": sum(1 for position in self.positions.values() if abs(position.quantity) > 1e-12),
            "profit_factor": profit_factor,
            "last_trade_review": self.trade_reviews[-1] if self.trade_reviews else None,
            "skipped_trades": len(self.skipped_trades),
            "loss_streaks": dict(self.loss_streaks),
            "loss_cooldown_until": dict(self.loss_cooldown_until),
            "global_cooldown_until": self.global_cooldown_until,
            "capital_guard_active": self.global_cooldown_until > 0,
        }

    def rebalance_from_signal(self, signal: Signal, current_tick: int = 0) -> PaperOrder | None:
        if signal.price <= 0:
            return None
        self.mark(signal.symbol, signal.price)

        current = self.positions.get(signal.symbol, Position(signal.symbol))
        current_side = Direction.FLAT
        if current.quantity > 0:
            current_side = Direction.LONG
        elif current.quantity < 0:
            current_side = Direction.SHORT

        scout_mode = self._component_float(signal, "scout_mode") >= 1.0
        min_entry_confidence = (
            min(self.min_confidence_to_trade, max(0.0, self.scout_min_confidence_to_trade))
            if scout_mode
            else self.min_confidence_to_trade
        )
        if current_side == Direction.FLAT and signal.confidence < min_entry_confidence:
            return None

        if current_side != Direction.FLAT:
            if signal.direction == current_side:
                return None
            if signal.direction == Direction.FLAT and not self._flow_reversal_exit(signal, current_side):
                return None
            active_plan = self.trade_plans.get(signal.symbol)
            if active_plan and current_tick - active_plan.created_tick < self.min_holding_ticks:
                return None
            if (
                signal.direction != Direction.FLAT
                and (signal.confidence < self.reversal_confidence or abs(signal.score) < 0.16)
            ):
                return None
            target_notional = 0.0
        else:
            if signal.direction != Direction.FLAT:
                guard_reason = self._capital_guard_reason(current_tick)
                if guard_reason:
                    self._record_skip(signal, signal.direction, guard_reason)
                    return None
                ticks_since_exit = current_tick - self.last_exit_tick.get(signal.symbol, -10_000)
                if ticks_since_exit < self.entry_cooldown_ticks:
                    return None
                loss_guard_reason = self._loss_guard_reason(signal.symbol, current_tick)
                if loss_guard_reason:
                    self._record_skip(signal, signal.direction, loss_guard_reason)
                    return None
            target_notional = 0.0
            if signal.direction == Direction.LONG:
                target_notional = self._base_entry_notional()
            elif signal.direction == Direction.SHORT:
                target_notional = -self._base_entry_notional()
            target_notional = self._risk_adjusted_target_notional(signal, target_notional)
            target_notional = self._loss_adjusted_target_notional(signal, target_notional)

        current_notional = current.quantity * signal.price
        delta_notional = target_notional - current_notional
        if abs(delta_notional) < 1.0:
            return None

        quantity = abs(delta_notional) / signal.price
        side = Direction.LONG if delta_notional > 0 else Direction.SHORT
        review = self._review_execution(signal, side, quantity, abs(delta_notional), target_notional == 0.0)
        self.trade_reviews.append(review)
        self.trade_reviews = self.trade_reviews[-100:]
        if not review["accepted"]:
            self.skipped_trades.append(review)
            self.skipped_trades = self.skipped_trades[-100:]
            return None

        previous_quantity = current.quantity
        order = self._fill_market(
            signal.symbol,
            side,
            quantity,
            signal.price,
            f"{signal.rationale} | cost={review['total_cost']:.2f}, edge={review['expected_edge']:.2f}",
            float(review["gas_fee"]),
            float(review["slippage_cost"]),
            float(review["expected_edge"]),
            float(review["total_cost"]),
            current_tick,
        )
        resulting_position = self.positions.get(signal.symbol, Position(signal.symbol))
        if abs(previous_quantity) < 1e-12 and abs(resulting_position.quantity) > 1e-12:
            self.trade_plans[signal.symbol] = replace(
                self._build_trade_plan(signal, order.fill_price, side, current_tick),
                leverage=order.leverage,
                margin_used=order.margin_used,
                entry_notional=order.notional,
                entry_fee_remaining=order.fee,
            )
        elif target_notional == 0.0:
            self.trade_plans.pop(signal.symbol, None)
            self.last_exit_tick[signal.symbol] = current_tick
        return order

    def _base_entry_notional(self) -> float:
        if self.target_position_notional_usd > 0:
            target = self.target_position_notional_usd
        else:
            target = self.equity() * self.risk_per_trade
        cap = self.max_abs_position_usd if self.max_abs_position_usd > 0 else target
        return max(0.0, min(target, cap))

    def _review_execution(
        self,
        signal: Signal,
        side: Direction,
        quantity: float,
        delta_notional: float,
        is_exit: bool,
    ) -> dict[str, float | str | bool]:
        exchange_fee = delta_notional * self.fee_bps / 10_000.0
        slippage_cost = delta_notional * self.slippage_bps / 10_000.0
        gas_fee = max(0.0, self.gas_fee_usd)
        total_cost = exchange_fee + slippage_cost + gas_fee
        stop_price, take_profit_price, planned_edge = self._risk_reward_plan(signal, side, signal.price, quantity)
        expected_edge = self._forecast_edge(signal, side, signal.price, quantity, take_profit_price)
        risk_edge = max(0.0, abs(signal.price - stop_price) * quantity)
        forecast_rr = expected_edge / risk_edge if risk_edge > 0 else 999.0
        positive_votes = int(signal.components.get("positive_votes", 0) or 0)
        negative_votes = int(signal.components.get("negative_votes", 0) or 0)
        confirmations = positive_votes if side == Direction.LONG else negative_votes
        volatility_penalty = self._component_float(signal, "volatility_penalty")
        shock_risk = self._component_float(signal, "shock_risk")
        effective_multiple = max(0.0, self.min_edge_cost_multiple)
        if signal.confidence >= 0.54:
            effective_multiple *= 0.90
        if confirmations >= 3:
            effective_multiple *= 0.90
        volatility_factor = self._volatility_risk_factor(volatility_penalty, shock_risk)
        effective_multiple *= volatility_factor
        effective_multiple = max(0.55, effective_multiple)
        effective_min_rr = max(0.52, self.min_forecast_rr)
        if signal.confidence >= 0.54:
            effective_min_rr *= 0.94
        if confirmations >= 3:
            effective_min_rr *= 0.94
        if abs(signal.score) >= 0.18:
            effective_min_rr *= 0.97
        if abs(float(signal.components.get("smart_money_score", 0.0) or 0.0)) >= 0.20:
            effective_min_rr *= 0.98
        effective_min_rr *= volatility_factor
        effective_min_rr = max(0.58, min(0.95, effective_min_rr))
        min_required = total_cost * effective_multiple
        volatility_blocked = (
            not is_exit
            and volatility_penalty >= self.volatility_block_penalty
            and abs(signal.score) < 0.32
        )
        shock_blocked = (
            not is_exit
            and shock_risk >= 1.0
            and forecast_rr < max(0.90, effective_min_rr)
        )
        accepted = is_exit or (
            not volatility_blocked
            and not shock_blocked
            and (
                total_cost <= 0.0
                or (expected_edge >= min_required and forecast_rr >= effective_min_rr)
            )
        )
        reason = "accepted"
        if is_exit:
            reason = "exit_order_cost_guard_bypassed"
        elif volatility_blocked:
            reason = "volatility_spike_requires_stronger_score"
        elif shock_blocked:
            reason = "volatile_exhaustion_requires_clearer_reward"
        elif expected_edge < min_required:
            reason = "expected_edge_below_fee_gas_threshold"
        elif forecast_rr < effective_min_rr:
            reason = (
                "volatility_adjusted_forecast_reward_below_min_rr"
                if volatility_factor > 1.0
                else "forecast_reward_below_min_rr"
            )
        return {
            "symbol": signal.symbol,
            "side": side,
            "accepted": accepted,
            "reason": reason,
            "notional": round(delta_notional, 8),
            "exchange_fee": round(exchange_fee, 8),
            "slippage_cost": round(slippage_cost, 8),
            "gas_fee": round(gas_fee, 8),
            "total_cost": round(total_cost, 8),
            "expected_edge": round(expected_edge, 8),
            "planned_edge": round(planned_edge, 8),
            "forecast_rr": round(forecast_rr, 6),
            "min_forecast_rr_used": round(effective_min_rr, 6),
            "stop_price": round(stop_price, 8),
            "take_profit_price": round(take_profit_price, 8),
            "min_required_edge": round(min_required, 8),
            "cost_multiple_used": round(effective_multiple, 4),
            "edge_cost_ratio": round(expected_edge / total_cost, 6) if total_cost > 0 else 999.0,
            "volatility_penalty": round(volatility_penalty, 6),
            "volatility_risk_factor": round(volatility_factor, 4),
            "shock_risk": bool(shock_risk >= 1.0),
            "confidence": signal.confidence,
            "score": signal.score,
        }

    def _risk_adjusted_target_notional(self, signal: Signal, target_notional: float) -> float:
        if abs(target_notional) < 1e-12:
            return target_notional
        volatility_penalty = self._component_float(signal, "volatility_penalty")
        shock_risk = self._component_float(signal, "shock_risk")
        ml_probability = self._component_float(signal, "ml_win_probability")
        degraded_derivatives_mode = self._component_float(signal, "degraded_derivatives_mode")
        derivatives_fresh = self._component_float(signal, "derivatives_fresh")
        derivatives_fresh_known = "derivatives_fresh" in signal.components
        scout_mode = self._component_float(signal, "scout_mode")
        scale = 1.0
        if volatility_penalty >= self.volatility_risk_penalty_threshold:
            scale = min(scale, self.high_volatility_position_scale)
        if shock_risk >= 1.0:
            scale = min(scale, self.shock_position_scale)
        if degraded_derivatives_mode >= 1.0:
            scale = min(scale, 0.35)
        elif derivatives_fresh_known and derivatives_fresh == 0.0:
            scale = min(scale, 0.50)
        if scout_mode >= 1.0:
            scale = min(scale, max(0.01, min(1.0, self.scout_position_scale)))
        if 0.0 < ml_probability < 0.62:
            scale = min(scale, 0.50)
        elif 0.0 < ml_probability < 0.66:
            scale = min(scale, 0.75)
        scale = max(0.05, min(1.0, scale))
        return target_notional * scale

    def _flow_reversal_exit(self, signal: Signal, current_side: Direction) -> bool:
        if current_side == Direction.FLAT:
            return False
        side = 1.0 if current_side == Direction.LONG else -1.0
        flow = side * self._component_float(signal, "flow_score")
        derivatives = side * self._component_float(signal, "derivatives_score")
        orderbook = side * self._component_float(signal, "orderbook_imbalance")
        higher_tf = side * self._component_float(signal, "higher_tf_score")
        ml_probability = self._component_float(signal, "ml_win_probability")
        positive_votes = int(self._component_float(signal, "positive_votes"))
        negative_votes = int(self._component_float(signal, "negative_votes"))
        adverse_votes = negative_votes if current_side == Direction.LONG else positive_votes
        pressure = 0
        if flow < -0.16:
            pressure += 1
        if derivatives < -0.12:
            pressure += 1
        if orderbook < -0.08:
            pressure += 1
        if higher_tf < -0.08:
            pressure += 1
        if adverse_votes >= 2:
            pressure += 1
        if 0.0 < ml_probability < 0.46:
            pressure += 1
        return pressure >= 2

    def _loss_adjusted_target_notional(self, signal: Signal, target_notional: float) -> float:
        if abs(target_notional) < 1e-12:
            return target_notional
        streak = self.loss_streaks.get(signal.symbol, 0)
        if streak < max(1, self.loss_streak_limit):
            return target_notional
        scale = max(0.05, min(1.0, self.loss_streak_position_scale))
        return target_notional * scale

    def _leverage_and_margin(self, notional: float) -> tuple[float, float]:
        notional = abs(notional)
        if notional <= 0:
            return 1.0, 0.0
        max_leverage = max(1.0, self.max_leverage)
        desired_margin = self.target_margin_usd if self.target_margin_usd > 0 else notional
        margin = min(notional, desired_margin)
        margin = max(margin, notional / max_leverage)
        leverage = min(max_leverage, notional / max(margin, 1e-12))
        margin = notional / max(leverage, 1e-12)
        return leverage, margin

    def _capital_guard_reason(self, current_tick: int) -> str:
        net_pnl_pct = (self.equity() - self.starting_cash) / self.starting_cash if self.starting_cash else 0.0
        if current_tick < self.global_cooldown_until:
            if net_pnl_pct >= 0:
                self.global_cooldown_until = 0
                return ""
            return "capital_guard_cooldown_active"

        closed_trades = self.winning_trades + self.losing_trades + self.scratch_trades
        if closed_trades < max(1, self.min_session_trades_for_guard):
            return ""

        decisive_trades = self.winning_trades + self.losing_trades
        win_rate = self.winning_trades / decisive_trades if decisive_trades else 0.0
        drawdown_limit = -abs(self.max_session_drawdown_pct)
        drawdown_breached = net_pnl_pct <= drawdown_limit
        loss_limit_breached = (
            net_pnl_pct < 0
            and self.losing_trades >= max(1, self.max_session_losses)
            and win_rate < max(0.0, self.min_session_win_rate)
        )
        if not (drawdown_breached or loss_limit_breached):
            return ""

        cooldown_ticks = max(1, self.global_cooldown_ticks)
        self.global_cooldown_until = max(self.global_cooldown_until, current_tick + cooldown_ticks)
        return "capital_guard_triggered"

    def _loss_guard_reason(self, symbol: str, current_tick: int) -> str:
        streak = self.loss_streaks.get(symbol, 0)
        if streak < max(1, self.loss_streak_limit):
            return ""

        cooldown_until = self.loss_cooldown_until.get(symbol)
        if cooldown_until is None:
            cooldown_until = current_tick + max(1, self.loss_streak_cooldown_ticks)
            self.loss_cooldown_until[symbol] = cooldown_until
        if current_tick < cooldown_until:
            return "loss_streak_cooldown_active"

        self.loss_streaks[symbol] = 0
        self.loss_cooldown_until.pop(symbol, None)
        return ""

    def _record_skip(self, signal: Signal, side: Direction, reason: str) -> None:
        self.skipped_trades.append(
            {
                "symbol": signal.symbol,
                "side": side,
                "accepted": False,
                "reason": reason,
                "notional": 0.0,
                "exchange_fee": 0.0,
                "slippage_cost": 0.0,
                "gas_fee": 0.0,
                "total_cost": 0.0,
                "expected_edge": 0.0,
                "planned_edge": 0.0,
                "forecast_rr": 0.0,
                "min_forecast_rr_used": self.min_forecast_rr,
                "stop_price": signal.price,
                "take_profit_price": signal.price,
                "min_required_edge": 0.0,
                "cost_multiple_used": self.min_edge_cost_multiple,
                "edge_cost_ratio": 0.0,
                "volatility_penalty": self._component_float(signal, "volatility_penalty"),
                "volatility_risk_factor": 1.0,
                "shock_risk": bool(self._component_float(signal, "shock_risk") >= 1.0),
                "confidence": signal.confidence,
                "score": signal.score,
            }
        )
        self.skipped_trades = self.skipped_trades[-100:]

    def _volatility_risk_factor(self, volatility_penalty: float, shock_risk: float) -> float:
        threshold = max(0.000001, self.volatility_risk_penalty_threshold)
        if volatility_penalty < threshold and shock_risk < 1.0:
            return 1.0
        excess = max(0.0, (volatility_penalty - threshold) / threshold)
        factor = 1.18 + min(0.42, excess * 0.20)
        if shock_risk >= 1.0:
            factor += 0.18
        return min(1.75, factor)

    @staticmethod
    def _component_float(signal: Signal, key: str) -> float:
        try:
            return float(signal.components.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _risk_reward_plan(
        self,
        signal: Signal,
        side: Direction,
        entry_price: float,
        quantity: float,
    ) -> tuple[float, float, float]:
        window = signal.expected_path[:2] or signal.expected_path
        if side == Direction.LONG:
            band_stop = min((point.lower_band for point in window), default=entry_price)
            risk_per_unit = max(entry_price - band_stop, entry_price * self.min_stop_loss_pct)
            stop_price = entry_price - risk_per_unit
            take_profit_price = entry_price + (risk_per_unit * self.risk_reward_ratio)
            expected_edge = max(0.0, (take_profit_price - entry_price) * quantity)
        else:
            band_stop = max((point.upper_band for point in window), default=entry_price)
            risk_per_unit = max(band_stop - entry_price, entry_price * self.min_stop_loss_pct)
            stop_price = entry_price + risk_per_unit
            take_profit_price = max(0.00000001, entry_price - (risk_per_unit * self.risk_reward_ratio))
            expected_edge = max(0.0, (entry_price - take_profit_price) * quantity)
        return stop_price, take_profit_price, expected_edge

    @staticmethod
    def _forecast_edge(
        signal: Signal,
        side: Direction,
        entry_price: float,
        quantity: float,
        take_profit_price: float,
    ) -> float:
        if quantity <= 0:
            return 0.0
        last_path = signal.expected_path[-1] if signal.expected_path else None
        if last_path is None:
            return 0.0
        expected_price = last_path.expected_price
        if side == Direction.LONG:
            projected_exit = min(expected_price, take_profit_price)
            return max(0.0, (projected_exit - entry_price) * quantity)
        projected_exit = max(expected_price, take_profit_price)
        return max(0.0, (entry_price - projected_exit) * quantity)

    def _build_trade_plan(
        self,
        signal: Signal,
        fill_price: float,
        side: Direction,
        current_tick: int,
    ) -> TradePlan:
        stop_price, take_profit_price, _ = self._risk_reward_plan(signal, side, fill_price, 1.0)
        return TradePlan(
            symbol=signal.symbol,
            side=side,
            entry_price=round(fill_price, 8),
            stop_price=round(stop_price, 8),
            take_profit_price=round(take_profit_price, 8),
            risk_per_unit=round(abs(fill_price - stop_price), 8),
            rr_ratio=self.risk_reward_ratio,
            created_tick=current_tick,
        )

    def _update_dynamic_trade_plan(self, symbol: str, price: float) -> None:
        position = self.positions.get(symbol)
        plan = self.trade_plans.get(symbol)
        if position is None or plan is None or abs(position.quantity) < 1e-12 or plan.risk_per_unit <= 0:
            return

        trigger_breakeven = max(0.0, self.breakeven_trigger_r) * plan.risk_per_unit
        lock_profit = max(0.0, self.breakeven_lock_r) * plan.risk_per_unit
        trigger_trailing = max(0.0, self.trailing_trigger_r) * plan.risk_per_unit
        trailing_distance = max(0.05, self.trailing_distance_r) * plan.risk_per_unit
        stop_price = plan.stop_price

        if position.quantity > 0:
            profit_per_unit = price - plan.entry_price
            if profit_per_unit >= trigger_breakeven:
                stop_price = max(stop_price, plan.entry_price + lock_profit)
            if profit_per_unit >= trigger_trailing:
                stop_price = max(stop_price, price - trailing_distance)
            stop_price = min(stop_price, plan.take_profit_price)
        else:
            profit_per_unit = plan.entry_price - price
            if profit_per_unit >= trigger_breakeven:
                stop_price = min(stop_price, plan.entry_price - lock_profit)
            if profit_per_unit >= trigger_trailing:
                stop_price = min(stop_price, price + trailing_distance)
            stop_price = max(stop_price, plan.take_profit_price)

        if abs(stop_price - plan.stop_price) < 1e-12:
            return
        self.trade_plans[symbol] = TradePlan(
            symbol=plan.symbol,
            side=plan.side,
            entry_price=plan.entry_price,
            stop_price=round(stop_price, 8),
            take_profit_price=plan.take_profit_price,
            risk_per_unit=plan.risk_per_unit,
            rr_ratio=plan.rr_ratio,
            created_tick=plan.created_tick,
            partial_taken=plan.partial_taken,
            leverage=plan.leverage,
            margin_used=plan.margin_used,
            entry_notional=plan.entry_notional,
            entry_fee_remaining=plan.entry_fee_remaining,
        )

    def _check_trade_plan(self, symbol: str, price: float, current_tick: int) -> PaperOrder | None:
        if price <= 0:
            return None
        position = self.positions.get(symbol)
        plan = self.trade_plans.get(symbol)
        if position is None or plan is None or abs(position.quantity) < 1e-12:
            return None

        exit_side = None
        reason = ""
        exit_quantity = abs(position.quantity)
        partial_r = max(0.0, self.partial_take_profit_r)
        partial_fraction = max(0.0, min(0.95, self.partial_take_profit_fraction))
        time_in_trade = current_tick - plan.created_tick
        if position.quantity > 0:
            profit_r = (price - plan.entry_price) / plan.risk_per_unit if plan.risk_per_unit > 0 else 0.0
            if not plan.partial_taken and partial_r > 0 and partial_fraction > 0 and profit_r >= partial_r:
                exit_side = Direction.SHORT
                reason = "partial_take_profit_r_hit"
                exit_quantity = abs(position.quantity) * partial_fraction
            if price <= plan.stop_price:
                exit_side = Direction.SHORT
                reason = "stop_loss_rr_hit"
                exit_quantity = abs(position.quantity)
            elif price >= plan.take_profit_price:
                exit_side = Direction.SHORT
                reason = "take_profit_rr_hit"
                exit_quantity = abs(position.quantity)
            elif exit_side is None and self.time_stop_ticks > 0 and time_in_trade >= self.time_stop_ticks and profit_r < self.time_stop_min_r:
                exit_side = Direction.SHORT
                reason = "time_stop_underperforming"
                exit_quantity = abs(position.quantity)
        else:
            profit_r = (plan.entry_price - price) / plan.risk_per_unit if plan.risk_per_unit > 0 else 0.0
            if not plan.partial_taken and partial_r > 0 and partial_fraction > 0 and profit_r >= partial_r:
                exit_side = Direction.LONG
                reason = "partial_take_profit_r_hit"
                exit_quantity = abs(position.quantity) * partial_fraction
            if price >= plan.stop_price:
                exit_side = Direction.LONG
                reason = "stop_loss_rr_hit"
                exit_quantity = abs(position.quantity)
            elif price <= plan.take_profit_price:
                exit_side = Direction.LONG
                reason = "take_profit_rr_hit"
                exit_quantity = abs(position.quantity)
            elif exit_side is None and self.time_stop_ticks > 0 and time_in_trade >= self.time_stop_ticks and profit_r < self.time_stop_min_r:
                exit_side = Direction.LONG
                reason = "time_stop_underperforming"
                exit_quantity = abs(position.quantity)

        if exit_side is None:
            return None

        pre_exit_quantity = abs(position.quantity)
        order = self._fill_market(
            symbol,
            exit_side,
            exit_quantity,
            price,
            reason,
            0.0,
            0.0,
            0.0,
            0.0,
            current_tick,
        )
        remaining = self.positions.get(symbol, Position(symbol)).quantity
        if abs(remaining) < 1e-12:
            self.trade_plans.pop(symbol, None)
            self.last_exit_tick[symbol] = current_tick
        elif reason == "partial_take_profit_r_hit":
            closed_fraction = min(1.0, exit_quantity / max(pre_exit_quantity, 1e-12))
            self.trade_plans[symbol] = TradePlan(
                symbol=plan.symbol,
                side=plan.side,
                entry_price=plan.entry_price,
                stop_price=plan.stop_price,
                take_profit_price=plan.take_profit_price,
                risk_per_unit=plan.risk_per_unit,
                rr_ratio=plan.rr_ratio,
                created_tick=plan.created_tick,
                partial_taken=True,
                leverage=plan.leverage,
                margin_used=max(0.0, plan.margin_used * (1.0 - closed_fraction)),
                entry_notional=max(0.0, plan.entry_notional * (1.0 - closed_fraction)),
                entry_fee_remaining=max(0.0, plan.entry_fee_remaining * (1.0 - closed_fraction)),
            )
        return order

    def _fill_market(
        self,
        symbol: str,
        side: Direction,
        quantity: float,
        price: float,
        reason: str,
        gas_fee: float = 0.0,
        slippage_cost: float = 0.0,
        estimated_edge: float = 0.0,
        total_execution_cost: float = 0.0,
        current_tick: int = 0,
    ) -> PaperOrder:
        signed_quantity = quantity if side == Direction.LONG else -quantity
        slippage = self.slippage_bps / 10_000.0
        fill_price = price * (1.0 + slippage if side == Direction.LONG else 1.0 - slippage)
        notional = abs(quantity * fill_price)
        fee = notional * self.fee_bps / 10_000.0
        position = self.positions.setdefault(symbol, Position(symbol))
        previous_quantity = position.quantity
        realized_gross = self._realized_gross_pnl(position, signed_quantity, fill_price)
        closed_quantity = min(abs(position.quantity), abs(signed_quantity)) if position.quantity * signed_quantity < 0 else 0.0
        closed_fee = fee * (closed_quantity / quantity) if quantity > 0 and closed_quantity > 0 else 0.0
        closed_gas = gas_fee if closed_quantity > 0 else 0.0
        active_plan = self.trade_plans.get(symbol)
        closed_fraction = min(1.0, closed_quantity / max(abs(previous_quantity), 1e-12)) if closed_quantity > 0 else 0.0
        entry_fee_allocated = (active_plan.entry_fee_remaining * closed_fraction) if active_plan else 0.0
        realized_net = realized_gross - closed_fee - closed_gas - entry_fee_allocated
        if closed_quantity > 0 and active_plan:
            leverage = active_plan.leverage
            margin_used = active_plan.margin_used * closed_fraction
        else:
            leverage, margin_used = self._leverage_and_margin(notional)

        if self.futures_margin_mode:
            if closed_quantity > 0:
                self.cash += realized_gross - closed_fee - closed_gas
            else:
                self.cash -= fee + gas_fee
        elif side == Direction.LONG:
            self.cash -= notional + fee + gas_fee
        else:
            self.cash += notional - fee - gas_fee

        self.total_fees += fee + gas_fee
        self.total_gas_fees += gas_fee
        if closed_quantity > 0:
            self.realized_pnl += realized_net
            decisive_threshold = max(0.0, self.min_decisive_trade_pnl)
            if realized_net > decisive_threshold:
                self.winning_trades += 1
                self.gross_profit += realized_net
                self.loss_streaks[symbol] = 0
            elif realized_net < -decisive_threshold:
                self.losing_trades += 1
                self.gross_loss += realized_net
                streak = self.loss_streaks.get(symbol, 0) + 1
                self.loss_streaks[symbol] = streak
                if streak >= max(1, self.loss_streak_limit):
                    self.loss_cooldown_until[symbol] = current_tick + max(0, self.loss_streak_cooldown_ticks)
            else:
                self.scratch_trades += 1
        self._update_position(position, signed_quantity, fill_price)
        order = PaperOrder(
            symbol=symbol,
            side=side,
            quantity=quantity,
            fill_price=round(fill_price, 8),
            notional=round(notional, 8),
            fee=round(fee, 8),
            reason=reason,
            timestamp=utc_now(),
            gas_fee=round(gas_fee, 8),
            slippage_cost=round(slippage_cost, 8),
            estimated_edge=round(estimated_edge, 8),
            total_execution_cost=round(total_execution_cost, 8),
            leverage=round(leverage, 4),
            margin_used=round(margin_used, 8),
            realized_pnl=round(realized_net, 8),
            realized_gross_pnl=round(realized_gross, 8),
            closed_notional=round(abs(closed_quantity * fill_price), 8),
        )
        self.orders.append(order)
        return order

    @staticmethod
    def _realized_gross_pnl(position: Position, signed_quantity: float, fill_price: float) -> float:
        if position.quantity == 0 or position.quantity * signed_quantity >= 0:
            return 0.0
        closed_quantity = min(abs(position.quantity), abs(signed_quantity))
        return (fill_price - position.avg_price) * closed_quantity * (1.0 if position.quantity > 0 else -1.0)

    @staticmethod
    def _update_position(position: Position, signed_quantity: float, fill_price: float) -> None:
        new_quantity = position.quantity + signed_quantity
        if abs(new_quantity) < 1e-12:
            position.quantity = 0.0
            position.avg_price = 0.0
            return

        same_side = (position.quantity >= 0 and signed_quantity >= 0) or (
            position.quantity <= 0 and signed_quantity <= 0
        )
        if position.quantity == 0 or same_side:
            old_notional = abs(position.quantity) * position.avg_price
            added_notional = abs(signed_quantity) * fill_price
            position.avg_price = (old_notional + added_notional) / abs(new_quantity)
        elif abs(signed_quantity) > abs(position.quantity):
            position.avg_price = fill_price
        position.quantity = new_quantity
