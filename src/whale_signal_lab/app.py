from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime

from .adapters.binance import fetch_market_batch
from .adapters.binance_futures import fetch_long_short_batch
from .adapters.binance_futures import fetch_funding_batch, fetch_orderbook_batch
from .adapters.etherscan import EtherscanClient, fetch_recent_whale_transfers
from .config import LabConfig, load_config
from .features import FeatureAssembler, base_asset
from .learning import SignalLearner
from .models import (
    Direction,
    FundingSnapshot,
    LongShortSnapshot,
    OrderBookSnapshot,
    PaperOrder,
    PricePathPoint,
    Signal,
    WalletActivity,
    WalletClusterSignal,
    WhaleTransfer,
)
from .notifications import TelegramNotifier
from .paper import PaperBroker
from .signals import SignalEngine
from .smart_money import (
    SmartMoneyClusterEngine,
    fetch_binance_orderflow_activities,
)


class LabRunner:
    def __init__(self, config: LabConfig, mode: str | None = None) -> None:
        self.config = config
        self.mode = mode or config.app.mode
        self.tick_count = 0
        self.data_warnings: list[str] = []
        self._last_poll_at: dict[str, float] = {}
        self.orderflow_history: dict[str, deque[dict]] = {
            symbol: deque(maxlen=48) for symbol in config.app.symbols
        }
        self.features = FeatureAssembler(set(config.onchain.stablecoins))
        self.engine = SignalEngine(config.onchain.min_transfer_usd, config.app.signal_horizon_sec)
        self.learner = SignalLearner(
            enabled=config.learner.enabled,
            log_path=config.learner.log_path,
            state_path=config.learner.state_path,
            outcome_horizon_ticks=config.learner.outcome_horizon_ticks,
            min_abs_return=config.learner.min_abs_return,
            learning_rate=config.learner.learning_rate,
            quality_min_probability=config.learner.quality_min_probability,
            quality_min_expectancy_r=config.learner.quality_min_expectancy_r,
            quality_warmup_trades=config.learner.quality_warmup_trades,
        )
        self.smart_money = SmartMoneyClusterEngine(
            wallet_limit=config.smart_money.wallet_limit,
            window_sec=config.smart_money.cluster_window_sec,
            min_cluster_wallets=config.smart_money.min_cluster_wallets,
            min_cluster_usd=config.smart_money.min_cluster_usd,
        )
        self.telegram = TelegramNotifier.from_config(config.telegram)
        self.paper = PaperBroker(
            starting_cash=config.paper.starting_cash,
            risk_per_trade=config.paper.risk_per_trade,
            fee_bps=config.paper.fee_bps,
            slippage_bps=config.paper.slippage_bps,
            min_confidence_to_trade=config.paper.min_confidence_to_trade,
            max_abs_position_usd=config.paper.max_abs_position_usd,
            gas_fee_usd=config.paper.gas_fee_usd,
            min_edge_cost_multiple=config.paper.min_edge_cost_multiple,
            risk_reward_ratio=config.paper.risk_reward_ratio,
            min_forecast_rr=config.paper.min_forecast_rr,
            min_stop_loss_pct=config.paper.min_stop_loss_pct,
            entry_cooldown_ticks=config.paper.entry_cooldown_ticks,
            min_holding_ticks=config.paper.min_holding_ticks,
            reversal_confidence=config.paper.reversal_confidence,
            breakeven_trigger_r=config.paper.breakeven_trigger_r,
            breakeven_lock_r=config.paper.breakeven_lock_r,
            trailing_trigger_r=config.paper.trailing_trigger_r,
            trailing_distance_r=config.paper.trailing_distance_r,
            volatility_risk_penalty_threshold=config.paper.volatility_risk_penalty_threshold,
            volatility_block_penalty=config.paper.volatility_block_penalty,
            high_volatility_position_scale=config.paper.high_volatility_position_scale,
            shock_position_scale=config.paper.shock_position_scale,
            partial_take_profit_r=config.paper.partial_take_profit_r,
            partial_take_profit_fraction=config.paper.partial_take_profit_fraction,
            time_stop_ticks=config.paper.time_stop_ticks,
            time_stop_min_r=config.paper.time_stop_min_r,
            loss_streak_limit=config.paper.loss_streak_limit,
            loss_streak_cooldown_ticks=config.paper.loss_streak_cooldown_ticks,
            loss_streak_position_scale=config.paper.loss_streak_position_scale,
            max_session_drawdown_pct=config.paper.max_session_drawdown_pct,
            max_session_losses=config.paper.max_session_losses,
            min_session_win_rate=config.paper.min_session_win_rate,
            min_session_trades_for_guard=config.paper.min_session_trades_for_guard,
            global_cooldown_ticks=config.paper.global_cooldown_ticks,
            scout_position_scale=config.paper.scout_position_scale,
            scout_min_confidence_to_trade=config.paper.scout_min_confidence_to_trade,
        )

    async def run(self, ticks: int = 0, print_json: bool | None = None) -> None:
        print_json = self.config.app.print_json if print_json is None else print_json
        while ticks <= 0 or self.tick_count < ticks:
            snapshot = await self.step()
            self._print_snapshot(snapshot, print_json)
            if ticks > 0 and self.tick_count >= ticks:
                break
            await asyncio.sleep(self.config.app.poll_interval_sec)

    async def step(self) -> dict:
        self.tick_count += 1
        market_ticks, whale_events, smart_activities, long_short_snapshots, orderbook_snapshots, funding_snapshots = (
            await self._next_events(self.tick_count)
        )
        orders: list[PaperOrder] = []
        for tick in market_ticks:
            self.features.add_market_tick(tick)
            exit_order = self.paper.mark(tick.symbol, tick.price, self.tick_count)
            if exit_order:
                orders.append(exit_order)
        learner_outcomes = self.learner.observe_prices(self.paper.marks, self.tick_count)
        for event in whale_events:
            self.features.add_whale_transfer(event)
        smart_clusters = self.smart_money.ingest(smart_activities) if self.config.smart_money.enabled else []
        for cluster in smart_clusters:
            self.features.add_smart_money_signal(cluster)
        for snapshot in long_short_snapshots:
            self.features.add_long_short_snapshot(snapshot)
        for snapshot in orderbook_snapshots:
            self.features.add_orderbook_snapshot(snapshot)
        for snapshot in funding_snapshots:
            self.features.add_funding_snapshot(snapshot)
        self.engine.set_component_weights(self.learner.component_weights())
        entry_window_open = bool(market_ticks)

        signals: list[Signal] = []
        feature_snapshots = []
        for symbol in self.config.app.symbols:
            feature_snapshot = self.features.snapshot(symbol)
            feature_snapshots.append(feature_snapshot)
            raw_signal = self.engine.evaluate(feature_snapshot)
            signal = self.learner.apply_quality_gate(raw_signal)
            signals.append(signal)
        cluster_proposals = self._cluster_proposals(smart_clusters, signals, feature_snapshots)
        orderflow_trends = self._orderflow_trends(
            smart_clusters,
            self.smart_money.orderflow_stats(),
            signals,
            feature_snapshots,
        )
        if entry_window_open:
            orders_before_entries = len(orders)
            for signal in signals:
                if signal.direction == Direction.FLAT:
                    continue
                previous_position = self.paper.positions.get(signal.symbol)
                previous_quantity = previous_position.quantity if previous_position else 0.0
                order = self.paper.rebalance_from_signal(signal, self.tick_count)
                if order:
                    orders.append(order)
                    await self._notify_entry_order(order, signal, previous_quantity)

            scout_slots = max(0, self.config.paper.scout_max_entries_per_tick - (len(orders) - orders_before_entries))
            if scout_slots > 0:
                signal_index = {signal.symbol: index for index, signal in enumerate(signals)}
                for scout_signal in self._scout_signals(signals, cluster_proposals, orderflow_trends)[:scout_slots]:
                    previous_position = self.paper.positions.get(scout_signal.symbol)
                    previous_quantity = previous_position.quantity if previous_position else 0.0
                    order = self.paper.rebalance_from_signal(scout_signal, self.tick_count)
                    if not order:
                        continue
                    orders.append(order)
                    index = signal_index.get(scout_signal.symbol)
                    if index is not None:
                        signals[index] = scout_signal
                    await self._notify_entry_order(order, scout_signal, previous_quantity)
        self.learner.observe_signals(signals, self.tick_count)

        return {
            "tick": self.tick_count,
            "mode": self.mode,
            "equity": self.paper.equity(),
            "cash": self.paper.cash,
            "performance": self.paper.performance_summary(),
            "paper_settings": asdict(self.config.paper),
            "positions": self.paper.positions,
            "trade_plans": self.paper.trade_plans,
            "marks": self.paper.marks,
            "market_ticks": market_ticks,
            "feature_snapshots": feature_snapshots,
            "signals": signals,
            "orders": orders,
            "recent_orders": self.paper.orders[-80:],
            "whale_events": whale_events,
            "long_short_snapshots": long_short_snapshots,
            "orderbook_snapshots": orderbook_snapshots,
            "funding_snapshots": funding_snapshots,
            "smart_money_activities": smart_activities[:50],
            "cluster_proposals": cluster_proposals,
            "orderflow_trends": orderflow_trends,
            "smart_money_clusters": smart_clusters[:12],
            "smart_money_summary": self.smart_money.summary(),
            "data_warnings": self.data_warnings[-12:],
            "learner_outcomes": learner_outcomes[-12:],
            "learner_summary": self.learner.summary(),
            "trade_reviews": self.paper.trade_reviews[-12:],
            "skipped_trades": self.paper.skipped_trades[-12:],
            "order_count": len(self.paper.orders),
            "telegram": self.telegram.status(),
        }

    def _scout_signals(
        self,
        signals: list[Signal],
        proposals: list[dict],
        orderflow_trends: list[dict],
    ) -> list[Signal]:
        if not self.config.paper.scout_enabled:
            return []

        signals_by_symbol = {signal.symbol: signal for signal in signals}
        candidates: list[tuple[float, Signal]] = []
        used_symbols: set[str] = set()

        for proposal in proposals:
            symbol = str(proposal.get("symbol", ""))
            base_signal = signals_by_symbol.get(symbol)
            side = self._direction_from(proposal.get("direction", Direction.FLAT))
            if base_signal is None or side == Direction.FLAT or symbol in used_symbols:
                continue
            blockers = [str(item) for item in proposal.get("blockers", []) if item]
            priority = float(proposal.get("priority", 0.0) or 0.0)
            confirmations = int(proposal.get("confirmations", 0) or 0)
            if priority < self.config.paper.scout_min_priority:
                continue
            if confirmations < self.config.paper.scout_min_confirmations:
                continue
            if len(blockers) > self.config.paper.scout_max_blockers:
                continue
            if any("RSI" in blocker or "hai phe" in blocker for blocker in blockers):
                continue
            if not self._scout_ai_allows(base_signal, side):
                continue
            scout = self._build_scout_signal(
                base_signal,
                side,
                strength=priority,
                source_code=1.0,
                reason=f"paper_scout proposal priority={priority:.2f}, confirmations={confirmations}",
            )
            candidates.append((priority + confirmations * 0.02, scout))
            used_symbols.add(symbol)

        for trend in orderflow_trends:
            symbol = str(trend.get("symbol", ""))
            base_signal = signals_by_symbol.get(symbol)
            side = self._direction_from(trend.get("bias", Direction.FLAT))
            if base_signal is None or side == Direction.FLAT or symbol in used_symbols:
                continue
            readiness = float(trend.get("readiness", 0.0) or 0.0)
            total_usd = float(trend.get("total_usd", 0.0) or 0.0)
            sample_count = int(trend.get("sample_count", 0) or 0)
            min_total_usd = max(50_000.0, self.config.smart_money.min_cluster_usd * 0.75)
            if readiness < self.config.paper.scout_min_readiness:
                continue
            if total_usd < min_total_usd or sample_count < 4:
                continue
            if side == Direction.LONG and float(trend.get("rsi", 50.0) or 50.0) >= 72.0:
                continue
            if side == Direction.SHORT and float(trend.get("rsi", 50.0) or 50.0) <= 28.0:
                continue
            if not self._scout_ai_allows(base_signal, side):
                continue
            scout = self._build_scout_signal(
                base_signal,
                side,
                strength=readiness,
                source_code=2.0,
                reason=f"paper_scout orderflow readiness={readiness:.2f}, usd={total_usd:,.0f}",
            )
            candidates.append((readiness, scout))
            used_symbols.add(symbol)

        return [signal for _, signal in sorted(candidates, key=lambda item: item[0], reverse=True)]

    def _scout_ai_allows(self, signal: Signal, side: Direction) -> bool:
        if signal.direction != Direction.FLAT:
            return False
        if signal.components.get("gate_passed", 0.0):
            return False
        if float(signal.components.get("ml_gate_passed", 1.0) or 0.0) == 0.0:
            return False
        if float(signal.components.get("shock_risk", 0.0) or 0.0) >= 1.0:
            return False
        side_value = 1.0 if side == Direction.LONG else -1.0
        side_score = side_value * signal.score
        if side_score < -0.06:
            return False
        return signal.confidence >= self.config.paper.scout_min_confidence_to_trade

    def _build_scout_signal(
        self,
        signal: Signal,
        side: Direction,
        *,
        strength: float,
        source_code: float,
        reason: str,
    ) -> Signal:
        side_value = 1.0 if side == Direction.LONG else -1.0
        scout_score = side_value * max(0.12, min(0.24, abs(signal.score) + strength * 0.08))
        confidence = max(signal.confidence, self.config.paper.scout_min_confidence_to_trade)
        stop_pct = max(0.0001, self.config.paper.min_stop_loss_pct)
        rr = max(1.0, self.config.paper.risk_reward_ratio)
        price = max(0.00000001, signal.price)
        if side == Direction.LONG:
            stop = price * (1.0 - stop_pct)
            target = price * (1.0 + stop_pct * rr)
            expected = price * (1.0 + stop_pct * rr * 0.85)
            lower = stop
            upper = target
        else:
            stop = price * (1.0 + stop_pct)
            target = max(0.00000001, price * (1.0 - stop_pct * rr))
            expected = max(0.00000001, price * (1.0 - stop_pct * rr * 0.85))
            lower = target
            upper = stop
        expected_path = [
            PricePathPoint(225, round((price + expected) / 2.0, 8), round(lower, 8), round(upper, 8)),
            PricePathPoint(signal.horizon_sec, round(expected, 8), round(lower, 8), round(upper, 8)),
        ]
        components = {
            **signal.components,
            "scout_mode": 1.0,
            "scout_strength": round(strength, 4),
            "scout_source": source_code,
            "scout_position_scale": round(self.config.paper.scout_position_scale, 4),
            "gate_passed": 1.0,
        }
        return replace(
            signal,
            direction=side,
            confidence=round(confidence, 4),
            score=round(scout_score, 4),
            components=components,
            rationale=f"{signal.rationale} | {reason}",
            expected_path=expected_path,
        )

    @staticmethod
    def _direction_from(value: object) -> Direction:
        if isinstance(value, Direction):
            return value
        try:
            return Direction(str(value))
        except ValueError:
            return Direction.FLAT

    async def _notify_entry_order(self, order: PaperOrder, signal: Signal, previous_quantity: float) -> None:
        position = self.paper.positions.get(order.symbol)
        current_quantity = position.quantity if position else 0.0
        opened_from_flat = abs(previous_quantity) < 1e-12 and abs(current_quantity) > 1e-12
        reversed_side = previous_quantity * current_quantity < 0
        if not (opened_from_flat or reversed_side):
            return
        plan = self.paper.trade_plans.get(order.symbol)
        sent = await asyncio.to_thread(
            self.telegram.notify_entry,
            order,
            signal,
            plan,
            mode=self.mode,
            tick=self.tick_count,
            equity=self.paper.equity(),
        )
        if not sent and self.telegram.last_error:
            self.data_warnings = [*self.data_warnings, self.telegram.last_error][-12:]

    async def _next_events(
        self, count: int
    ) -> tuple[
        list,
        list[WhaleTransfer],
        list[WalletActivity],
        list[LongShortSnapshot],
        list[OrderBookSnapshot],
        list[FundingSnapshot],
    ]:
        warnings: list[str] = []
        market_ticks = await self._market_ticks(warnings)
        whale_events: list[WhaleTransfer] = []
        smart_activities: list[WalletActivity] = []
        long_short_snapshots: list[LongShortSnapshot] = []
        orderbook_snapshots: list[OrderBookSnapshot] = []
        funding_snapshots: list[FundingSnapshot] = []
        should_poll_onchain = count == 1 or (
            count * self.config.app.poll_interval_sec
        ) % self.config.onchain.poll_interval_sec < self.config.app.poll_interval_sec
        if self.mode != "demo" and should_poll_onchain and self.config.onchain.etherscan_api_key and self.config.wallets:
            price_by_token = self._price_by_token(market_ticks)
            client = EtherscanClient(
                api_key=self.config.onchain.etherscan_api_key,
                chainid=self.config.onchain.chainid,
                base_url=self.config.onchain.etherscan_base_url,
            )
            wallets = tuple((wallet.label, wallet.address) for wallet in self.config.wallets)
            whale_events = await asyncio.to_thread(
                fetch_recent_whale_transfers,
                client,
                wallets,
                self.config.exchange_addresses,
                price_by_token,
                self.config.onchain.min_transfer_usd,
            )
        elif self.mode != "demo" and should_poll_onchain:
            warnings.append("On-chain that chua chay: thieu API key hoac danh sach wallet.")
        should_poll_smart_money = self.config.smart_money.enabled and self._poll_due(
            "smart_money",
            self.config.smart_money.poll_interval_sec,
        )
        should_poll_derivatives = self.config.derivatives.enabled and self._poll_due(
            "derivatives",
            self.config.derivatives.poll_interval_sec,
        )
        if should_poll_derivatives:
            try:
                long_short_snapshots = await asyncio.to_thread(
                    fetch_long_short_batch,
                    self.config.app.symbols,
                    self.config.derivatives.binance_futures_base_url,
                    self.config.derivatives.period,
                )
            except Exception as exc:
                warnings.append(f"Khong lay duoc derivatives Binance: {exc}")
                long_short_snapshots = []
        try:
            orderbook_snapshots = await asyncio.to_thread(
                fetch_orderbook_batch,
                self.config.app.symbols,
                self.config.derivatives.binance_futures_base_url,
                self.config.derivatives.orderbook_depth_limit,
            )
        except Exception as exc:
            warnings.append(f"Khong lay duoc futures orderbook: {exc}")
            orderbook_snapshots = []
        should_poll_funding = self.config.derivatives.enabled and self._poll_due(
            "funding",
            self.config.derivatives.funding_poll_interval_sec,
        )
        if should_poll_funding:
            try:
                funding_snapshots = await asyncio.to_thread(
                    fetch_funding_batch,
                    self.config.app.symbols,
                    self.config.derivatives.binance_futures_base_url,
                )
            except Exception as exc:
                warnings.append(f"Khong lay duoc futures funding: {exc}")
                funding_snapshots = []
        if should_poll_smart_money:
            try:
                smart_activities = await asyncio.to_thread(
                    fetch_binance_orderflow_activities,
                    self.config.app.symbols,
                    long_short_snapshots,
                    self.config.derivatives.binance_futures_base_url,
                    self.config.smart_money.orderflow_window_sec,
                    self.config.smart_money.min_activity_usd,
                    self.config.smart_money.cluster_bucket_sec,
                    self.config.smart_money.max_trades_per_symbol,
                )
            except Exception as exc:
                warnings.append(f"Khong lay duoc cum lenh 5 phut Binance: {exc}")
                smart_activities = []
        if not market_ticks:
            warnings.append("Khong co market data tu Binance, nen he thong khong the vao lenh.")
        self.data_warnings = warnings
        return market_ticks, whale_events, smart_activities, long_short_snapshots, orderbook_snapshots, funding_snapshots

    def _poll_due(self, key: str, interval_sec: float) -> bool:
        interval = max(0.0, float(interval_sec))
        now = time.monotonic()
        last = self._last_poll_at.get(key, 0.0)
        if last <= 0.0 or interval <= 0.0 or now - last >= interval:
            self._last_poll_at[key] = now
            return True
        return False

    async def _market_ticks(self, warnings: list[str]) -> list:
        try:
            return await asyncio.to_thread(
                fetch_market_batch,
                self.config.app.symbols,
                self.config.market.binance_base_url,
            )
        except Exception as exc:
            warnings.append(f"Khong lay duoc gia Binance: {exc}")
            return []

    def _price_by_token(self, ticks: list) -> dict[str, float]:
        prices = {coin.upper(): 1.0 for coin in self.config.onchain.stablecoins}
        for tick in ticks:
            prices[base_asset(tick.symbol).upper()] = tick.price
        return prices

    def _orderflow_trends(
        self,
        clusters: list[WalletClusterSignal],
        orderflow_stats: dict[str, dict[str, float | int]],
        signals: list[Signal],
        feature_snapshots: list,
    ) -> list[dict]:
        signals_by_symbol = {signal.symbol: signal for signal in signals}
        features_by_symbol = {feature.symbol: feature for feature in feature_snapshots}
        trend_rows: list[dict] = []
        for symbol in self.config.app.symbols:
            long_usd = 0.0
            short_usd = 0.0
            stats = orderflow_stats.get(symbol, {})
            if stats:
                long_usd = float(stats.get("long_usd", 0.0))
                short_usd = float(stats.get("short_usd", 0.0))
            long_clusters = 0
            short_clusters = 0
            max_sync = 0.0
            for cluster in clusters:
                if cluster.symbol != symbol or cluster.direction not in (Direction.LONG, Direction.SHORT):
                    continue
                max_sync = max(max_sync, cluster.sync_score)
                if cluster.direction == Direction.LONG:
                    long_clusters += 1
                else:
                    short_clusters += 1
            total_usd = long_usd + short_usd
            net_ratio = (long_usd - short_usd) / total_usd if total_usd > 0 else 0.0
            history = self.orderflow_history.setdefault(symbol, deque(maxlen=48))
            previous = list(history)[-8:]
            previous_net = sum(item["net_ratio"] for item in previous) / len(previous) if previous else net_ratio
            previous_total = sum(item["total_usd"] for item in previous) / len(previous) if previous else total_usd
            history.append(
                {
                    "tick": self.tick_count,
                    "net_ratio": net_ratio,
                    "total_usd": total_usd,
                    "long_usd": long_usd,
                    "short_usd": short_usd,
                }
            )
            velocity = net_ratio - previous_net
            liquidity_expansion = (
                (total_usd - previous_total) / previous_total if previous_total > 0 else 0.0
            )
            signal = signals_by_symbol.get(symbol)
            feature = features_by_symbol.get(symbol)
            buy_pressure = feature.buy_pressure if feature else 0.5
            taker_ratio = feature.taker_buy_sell_ratio if feature else 1.0
            rsi = feature.rsi if feature else 50.0
            derivatives_score = feature.derivatives_score if feature else 0.0
            bias = Direction.FLAT
            if net_ratio >= 0.18 and velocity >= -0.08:
                bias = Direction.LONG
            elif net_ratio <= -0.18 and velocity <= 0.08:
                bias = Direction.SHORT
            continuation_ok = (
                (bias == Direction.LONG and buy_pressure >= 0.52 and taker_ratio >= 1.0 and rsi < 76)
                or (bias == Direction.SHORT and buy_pressure <= 0.48 and taker_ratio <= 1.0 and rsi > 24)
            )
            derivative_ok = (
                (bias == Direction.LONG and derivatives_score >= -0.02)
                or (bias == Direction.SHORT and derivatives_score <= 0.02)
            )
            expanding = liquidity_expansion > 0.08
            readiness = _clamp(
                abs(net_ratio) * 0.36
                + max(0.0, velocity if bias == Direction.LONG else -velocity) * 0.18
                + max_sync * 0.18
                + (0.14 if continuation_ok else -0.10)
                + (0.08 if derivative_ok else -0.06)
                + (0.06 if expanding else 0.0),
                0.0,
                1.0,
            )
            if bias == Direction.FLAT:
                readiness = min(readiness, 0.35)
            action = "TRUNG LAP"
            if bias == Direction.LONG:
                action = "SONG LONG" if readiness >= 0.58 else "CANH LONG"
            elif bias == Direction.SHORT:
                action = "SONG SHORT" if readiness >= 0.58 else "CANH SHORT"
            if bias != Direction.FLAT and readiness < 0.18:
                action = f"THEO DOI {bias.value}"
            if signal and signal.direction == Direction.FLAT:
                action = action.replace("SONG", "CANH")
                readiness = min(readiness, 0.74)
            entry_note = _trend_entry_note(bias, continuation_ok, derivative_ok, expanding)
            trend_rows.append(
                {
                    "symbol": symbol,
                    "bias": bias,
                    "action": action,
                    "readiness": readiness,
                    "net_ratio": net_ratio,
                    "velocity": velocity,
                    "liquidity_expansion": liquidity_expansion,
                    "long_usd": long_usd,
                    "short_usd": short_usd,
                    "total_usd": total_usd,
                    "long_clusters": long_clusters,
                    "short_clusters": short_clusters,
                    "max_sync": max_sync,
                    "buy_pressure": buy_pressure,
                    "taker_buy_sell_ratio": taker_ratio,
                    "derivatives_score": derivatives_score,
                    "rsi": rsi,
                    "sample_count": len(history),
                    "entry_note": entry_note,
                    "ai_direction": signal.direction if signal else Direction.FLAT,
                    "ai_confidence": signal.confidence if signal else 0.0,
                }
            )
        return sorted(trend_rows, key=lambda item: item["readiness"], reverse=True)

    def _cluster_proposals(
        self,
        clusters: list[WalletClusterSignal],
        signals: list[Signal],
        feature_snapshots: list,
    ) -> list[dict]:
        signals_by_symbol = {signal.symbol: signal for signal in signals}
        features_by_symbol = {feature.symbol: feature for feature in feature_snapshots}
        by_symbol: dict[str, dict] = {}
        for cluster in clusters:
            if cluster.direction not in (Direction.LONG, Direction.SHORT):
                continue
            if cluster.sync_score < 0.76 or cluster.confidence < 0.86:
                continue
            symbol_bucket = by_symbol.setdefault(
                cluster.symbol,
                {
                    Direction.LONG: {"weight": 0.0, "usd": 0.0, "clusters": 0, "wallets": 0, "sync": 0.0},
                    Direction.SHORT: {"weight": 0.0, "usd": 0.0, "clusters": 0, "wallets": 0, "sync": 0.0},
                },
            )
            weight = max(0.0, cluster.total_usd) * max(0.0, cluster.sync_score) * max(0.0, cluster.confidence)
            side_bucket = symbol_bucket[cluster.direction]
            side_bucket["weight"] += weight
            side_bucket["usd"] += max(0.0, cluster.total_usd)
            side_bucket["clusters"] += 1
            side_bucket["wallets"] += max(0, cluster.wallet_count)
            side_bucket["sync"] = max(side_bucket["sync"], max(0.0, cluster.sync_score))

        proposals: list[dict] = []
        for symbol in self.config.app.symbols:
            bucket = by_symbol.get(symbol)
            signal = signals_by_symbol.get(symbol)
            feature = features_by_symbol.get(symbol)
            if not bucket or not signal or not feature:
                continue
            long_stats = bucket[Direction.LONG]
            short_stats = bucket[Direction.SHORT]
            long_weight = long_stats["weight"]
            short_weight = short_stats["weight"]
            total_weight = long_weight + short_weight
            if total_weight <= 0:
                continue
            dominant = Direction.LONG if long_weight >= short_weight else Direction.SHORT
            dominant_stats = long_stats if dominant == Direction.LONG else short_stats
            opposing_stats = short_stats if dominant == Direction.LONG else long_stats
            dominance = abs(long_weight - short_weight) / total_weight
            dominant_share = max(long_weight, short_weight) / total_weight
            conflict_share = min(long_weight, short_weight) / total_weight
            tape_ok = feature.buy_pressure >= 0.54 if dominant == Direction.LONG else feature.buy_pressure <= 0.46
            taker_ok = feature.taker_buy_sell_ratio >= 1.02 if dominant == Direction.LONG else feature.taker_buy_sell_ratio <= 0.98
            derivative_ok = feature.derivatives_score >= 0.02 if dominant == Direction.LONG else feature.derivatives_score <= -0.02
            rsi_ok = feature.rsi < 72 if dominant == Direction.LONG else feature.rsi > 28
            ai_ok = signal.direction == dominant and bool(signal.components.get("gate_passed", 0))
            confirmations = sum(bool(item) for item in (tape_ok, taker_ok, derivative_ok, rsi_ok, ai_ok))
            blockers: list[str] = []
            if conflict_share >= 0.32:
                blockers.append("hai phe co cum lon gan nhau")
            if not tape_ok:
                blockers.append("buy pressure chua ung ho" if dominant == Direction.LONG else "sell pressure chua ro")
            if not taker_ok:
                blockers.append("taker buy/sell chua xac nhan")
            if not derivative_ok:
                blockers.append("phai sinh chua dong huong")
            if not rsi_ok:
                blockers.append("RSI dang o vung de bi quet")
            if not ai_ok:
                blockers.append("AI gate chua cho vao lenh")

            if dominance >= 0.36 and confirmations >= 4:
                action = f"CANH {dominant.value}"
            elif dominance >= 0.22 and confirmations >= 3:
                action = f"CHO XAC NHAN {dominant.value}"
            else:
                action = "TRACH VAO"

            priority = _clamp(
                0.16
                + dominance * 0.26
                + dominant_stats["sync"] * 0.16
                + (confirmations / 5) * 0.34
                - conflict_share * 0.18
                - len(blockers) * 0.08,
                0.0,
                1.0,
            )
            if action == "TRACH VAO":
                priority = min(priority, 0.49)
            elif action.startswith("CHO"):
                priority = min(priority, 0.74)
            price = max(0.0, feature.price or signal.price)
            stop_pct = max(0.0001, self.config.paper.min_stop_loss_pct)
            rr = max(1.0, self.config.paper.risk_reward_ratio)
            if dominant == Direction.LONG:
                stop = price * (1 - stop_pct)
                take_profit = price * (1 + stop_pct * rr)
                trigger = price * 1.0004
            else:
                stop = price * (1 + stop_pct)
                take_profit = price * (1 - stop_pct * rr)
                trigger = price * 0.9996
            proposals.append(
                {
                    "symbol": symbol,
                    "action": action,
                    "direction": dominant,
                    "priority": priority,
                    "dominance": dominance,
                    "dominant_share": dominant_share,
                    "conflict_share": conflict_share,
                    "dominant_clusters": dominant_stats["clusters"],
                    "opposing_clusters": opposing_stats["clusters"],
                    "dominant_usd": dominant_stats["usd"],
                    "opposing_usd": opposing_stats["usd"],
                    "wallet_count": dominant_stats["wallets"],
                    "max_sync": dominant_stats["sync"],
                    "confirmations": confirmations,
                    "blockers": blockers[:4],
                    "entry_hint": trigger,
                    "stop_hint": stop,
                    "take_profit_hint": take_profit,
                    "price": price,
                    "buy_pressure": feature.buy_pressure,
                    "taker_buy_sell_ratio": feature.taker_buy_sell_ratio,
                    "derivatives_score": feature.derivatives_score,
                    "rsi": feature.rsi,
                    "ai_direction": signal.direction,
                    "ai_confidence": signal.confidence,
                }
            )
        return sorted(proposals, key=lambda item: item["priority"], reverse=True)

    def _print_snapshot(
        self,
        snapshot: dict,
        print_json: bool,
    ) -> None:
        if print_json:
            print(json.dumps(snapshot, default=_json_default, ensure_ascii=True))
            return

        count = snapshot["tick"]
        signals = snapshot["signals"]
        orders = snapshot["orders"]
        whale_events = snapshot["whale_events"]
        smart_clusters: list[WalletClusterSignal] = snapshot["smart_money_clusters"]
        learner_summary = snapshot["learner_summary"]
        print(f"\nTick {count} | mode={self.mode} | equity={self.paper.equity():,.2f} USDT")
        print(
            f"  learner win_rate={learner_summary['win_rate']:.2%} "
            f"pending={learner_summary['pending']} resolved={learner_summary['resolved']}"
        )
        if whale_events:
            for event in whale_events:
                print(
                    f"  whale {event.direction} {event.token_symbol} "
                    f"${event.usd_value:,.0f} tx={event.tx_hash}"
                )
        for signal in signals:
            first_path = signal.expected_path[-1] if signal.expected_path else None
            forecast = f" -> {first_path.expected_price:,.4f}" if first_path else ""
            marker = _direction_marker(signal.direction)
            print(
                f"  {marker} {signal.symbol:8} price={signal.price:,.4f}{forecast} "
                f"score={signal.score:+.3f} conf={signal.confidence:.2f} {signal.rationale}"
            )
        for cluster in smart_clusters[:3]:
            print(
                f"  group {cluster.cluster_id} {cluster.direction} {cluster.symbol} "
                f"wallets={cluster.wallet_count} usd={cluster.total_usd:,.0f} "
                f"score={cluster.score:+.2f} conf={cluster.confidence:.2f}"
            )
        for order in orders:
            print(
                f"  order {order.side:5} {order.symbol} qty={order.quantity:.8f} "
                f"fill={order.fill_price:,.4f} fee={order.fee:.4f}"
            )


def _direction_marker(direction: Direction) -> str:
    if direction == Direction.LONG:
        return "LONG "
    if direction == Direction.SHORT:
        return "SHORT"
    return "FLAT "


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _trend_entry_note(
    bias: Direction,
    continuation_ok: bool,
    derivative_ok: bool,
    expanding: bool,
) -> str:
    if bias == Direction.FLAT:
        return "Cho them du lieu, hai phe chua co uu the ro."
    side = "LONG" if bias == Direction.LONG else "SHORT"
    if continuation_ok and derivative_ok and expanding:
        return f"Co the canh {side} khi gia hoi nhe va cum cung huong tiep tuc day."
    if continuation_ok and derivative_ok:
        return f"Canh {side}, nhung uu tien vao khi thanh khoan bung them."
    if continuation_ok:
        return f"Chi quan sat {side}; phai sinh chua dong thuan day du."
    return f"Chua du dieu kien {side}; doi tape va taker xac nhan lai."


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return asdict(value)
    return str(value)


async def run_from_config(path: str, mode: str | None, ticks: int, print_json: bool | None) -> None:
    runner = LabRunner(load_config(path), mode=mode)
    await runner.run(ticks=ticks, print_json=print_json)
