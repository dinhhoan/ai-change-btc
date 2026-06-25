from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from math import sqrt

from .models import (
    FundingSnapshot,
    FeatureSnapshot,
    LongShortSnapshot,
    MarketTick,
    OrderBookSnapshot,
    WhaleDirection,
    WhaleTransfer,
    WalletClusterSignal,
    utc_now,
)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def base_asset(symbol: str) -> str:
    for quote in ("USDT", "USDC", "FDUSD", "BUSD", "BTC", "ETH"):
        if symbol.endswith(quote):
            return symbol[: -len(quote)]
    return symbol


class MarketFeatureWindow:
    def __init__(self, max_ticks: int = 120) -> None:
        self._ticks: dict[str, deque[MarketTick]] = defaultdict(lambda: deque(maxlen=max_ticks))

    def add(self, tick: MarketTick) -> None:
        self._ticks[tick.symbol].append(tick)

    def snapshot(
        self, symbol: str
    ) -> tuple[float, float, float, float, float, float, float, float, float, float, float, float, str]:
        ticks = list(self._ticks[symbol])
        if not ticks:
            return 0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, 0.0, 50.0, 0.0, 0.0, 0.0, "unknown"

        latest = ticks[-1]
        first = ticks[0]
        prices = [tick.price for tick in ticks]
        momentum_pct = (latest.price - first.price) / first.price if first.price else 0.0
        returns = []
        for previous, current in zip(ticks, ticks[1:]):
            if previous.price > 0:
                returns.append((current.price - previous.price) / previous.price)
        if len(returns) >= 2:
            mean = sum(returns) / len(returns)
            variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
            volatility = sqrt(variance)
        else:
            volatility = 0.0

        quote_volume = sum(tick.volume_quote for tick in ticks)
        taker_buy_quote = sum(tick.taker_buy_quote for tick in ticks)
        buy_pressure = taker_buy_quote / quote_volume if quote_volume > 0 else latest.buy_pressure
        ema_fast = self._ema(prices, 5)
        ema_slow = self._ema(prices, 13)
        higher_ema_fast = self._ema(prices, 21)
        higher_ema_slow = self._ema(prices, 55)
        trend_score = (
            clamp(((ema_fast - ema_slow) / latest.price) * 120.0, -1.0, 1.0)
            if latest.price
            else 0.0
        )
        higher_tf_trend_score = (
            clamp(((higher_ema_fast - higher_ema_slow) / latest.price) * 180.0, -1.0, 1.0)
            if latest.price
            else 0.0
        )
        higher_anchor = ticks[-min(len(ticks), 60)]
        higher_tf_momentum_pct = (
            (latest.price - higher_anchor.price) / higher_anchor.price if higher_anchor.price else 0.0
        )
        regime_score, market_regime = self._regime(momentum_pct, higher_tf_trend_score, volatility, buy_pressure)
        rsi = self._rsi(returns[-14:])
        return (
            latest.price,
            momentum_pct,
            volatility,
            clamp(buy_pressure, 0.0, 1.0),
            quote_volume,
            ema_fast,
            ema_slow,
            trend_score,
            rsi,
            higher_tf_trend_score,
            higher_tf_momentum_pct,
            regime_score,
            market_regime,
        )

    @staticmethod
    def _ema(prices: list[float], period: int) -> float:
        if not prices:
            return 0.0
        alpha = 2.0 / (period + 1.0)
        value = prices[0]
        for price in prices[1:]:
            value = (price * alpha) + (value * (1.0 - alpha))
        return value

    @staticmethod
    def _rsi(returns: list[float]) -> float:
        if len(returns) < 2:
            return 50.0
        gains = sum(max(item, 0.0) for item in returns)
        losses = sum(abs(min(item, 0.0)) for item in returns)
        if gains == 0 and losses == 0:
            return 50.0
        if losses == 0:
            return 100.0
        relative_strength = gains / losses
        return clamp(100.0 - (100.0 / (1.0 + relative_strength)), 0.0, 100.0)

    @staticmethod
    def _regime(
        momentum_pct: float,
        higher_tf_trend_score: float,
        volatility: float,
        buy_pressure: float,
    ) -> tuple[float, str]:
        if volatility >= 0.00055:
            if momentum_pct >= 0.0035 and buy_pressure >= 0.58:
                return 0.35, "volatile_pump"
            if momentum_pct <= -0.0035 and buy_pressure <= 0.42:
                return -0.35, "volatile_flush"
            return 0.0, "high_volatility"
        if higher_tf_trend_score >= 0.08 and momentum_pct >= -0.001:
            return clamp(higher_tf_trend_score, 0.0, 1.0), "trend_up"
        if higher_tf_trend_score <= -0.08 and momentum_pct <= 0.001:
            return clamp(higher_tf_trend_score, -1.0, 0.0), "trend_down"
        if abs(higher_tf_trend_score) < 0.035 and abs(momentum_pct) < 0.0015:
            return 0.0, "chop"
        return clamp(higher_tf_trend_score, -0.6, 0.6), "transition"


class WhaleFlowWindow:
    def __init__(self, max_age: timedelta = timedelta(minutes=45)) -> None:
        self.max_age = max_age
        self._events: deque[WhaleTransfer] = deque()

    def add(self, event: WhaleTransfer) -> None:
        self._events.append(event)
        self.prune(event.timestamp)

    def prune(self, now: datetime | None = None) -> None:
        now = now or utc_now()
        cutoff = now - self.max_age
        while self._events and self._events[0].timestamp < cutoff:
            self._events.popleft()

    def score_for_symbol(self, symbol: str, stablecoins: set[str], now: datetime | None = None) -> tuple[float, int]:
        self.prune(now)
        asset = base_asset(symbol).upper()
        net_usd = 0.0
        count = 0
        for event in self._events:
            token = event.token_symbol.upper()
            impact = self._impact(event.direction)
            if token == asset:
                net_usd += event.usd_value * impact
                count += 1
            elif token in stablecoins:
                net_usd += event.usd_value * impact * 0.35
                count += 1
        return net_usd, count

    @staticmethod
    def _impact(direction: WhaleDirection) -> float:
        if direction == WhaleDirection.EXCHANGE_OUTFLOW:
            return 1.0
        if direction == WhaleDirection.EXCHANGE_INFLOW:
            return -1.0
        if direction == WhaleDirection.WHALE_IN:
            return 0.35
        if direction == WhaleDirection.WHALE_OUT:
            return -0.35
        return 0.0


class SmartMoneySignalWindow:
    def __init__(self, max_age: timedelta = timedelta(minutes=8)) -> None:
        self.max_age = max_age
        self._signals: deque[WalletClusterSignal] = deque()

    def add(self, signal: WalletClusterSignal) -> None:
        self._signals.append(signal)
        self.prune(signal.generated_at)

    def prune(self, now: datetime | None = None) -> None:
        now = now or utc_now()
        cutoff = now - self.max_age
        while self._signals and self._signals[0].generated_at < cutoff:
            self._signals.popleft()

    def score_for_symbol(self, symbol: str, now: datetime | None = None) -> tuple[float, float, int, float, float]:
        self.prune(now)
        now = now or utc_now()
        matched = [signal for signal in self._signals if signal.symbol == symbol]
        if not matched:
            return 0.0, 0.0, 0, 0.0, 9999.0
        weighted_score = sum(signal.score * signal.confidence for signal in matched)
        confidence_weight = sum(signal.confidence for signal in matched) or 1.0
        score = clamp(weighted_score / confidence_weight, -1.0, 1.0)
        sync = max(signal.sync_score for signal in matched)
        wallets = sum(signal.wallet_count for signal in matched)
        total_usd = sum(signal.total_usd for signal in matched)
        latest = max(signal.generated_at for signal in matched)
        age_sec = max(0.0, (now - latest).total_seconds())
        return score, sync, wallets, total_usd, age_sec


class DerivativesSentimentWindow:
    def __init__(self, max_age: timedelta = timedelta(minutes=20)) -> None:
        self.max_age = max_age
        self._snapshots: dict[str, LongShortSnapshot] = {}

    def add(self, snapshot: LongShortSnapshot) -> None:
        self._snapshots[snapshot.symbol] = snapshot

    def score_for_symbol(self, symbol: str, now: datetime | None = None) -> tuple[float, float, float, float, float, float, float]:
        now = now or utc_now()
        snapshot = self._snapshots.get(symbol)
        if snapshot is None or snapshot.timestamp < now - self.max_age:
            return 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 9999.0
        age_sec = max(0.0, (now - snapshot.timestamp).total_seconds())
        return (
            clamp(snapshot.sentiment_score, -1.0, 1.0),
            snapshot.global_ratio,
            snapshot.top_ratio,
            snapshot.taker_buy_sell_ratio,
            snapshot.open_interest_value,
            snapshot.open_interest_change_pct,
            age_sec,
        )


class OrderBookSignalWindow:
    def __init__(self, max_age: timedelta = timedelta(minutes=3)) -> None:
        self.max_age = max_age
        self._snapshots: dict[str, OrderBookSnapshot] = {}

    def add(self, snapshot: OrderBookSnapshot) -> None:
        self._snapshots[snapshot.symbol] = snapshot

    def score_for_symbol(self, symbol: str, now: datetime | None = None) -> tuple[float, float, float]:
        now = now or utc_now()
        snapshot = self._snapshots.get(symbol)
        if snapshot is None or snapshot.timestamp < now - self.max_age:
            return 0.0, 0.0, 9999.0
        age_sec = max(0.0, (now - snapshot.timestamp).total_seconds())
        return clamp(snapshot.imbalance, -1.0, 1.0), max(0.0, snapshot.spread_bps), age_sec


class FundingSignalWindow:
    def __init__(self, max_age: timedelta = timedelta(minutes=30)) -> None:
        self.max_age = max_age
        self._snapshots: dict[str, FundingSnapshot] = {}

    def add(self, snapshot: FundingSnapshot) -> None:
        self._snapshots[snapshot.symbol] = snapshot

    def score_for_symbol(self, symbol: str, now: datetime | None = None) -> tuple[float, float]:
        now = now or utc_now()
        snapshot = self._snapshots.get(symbol)
        if snapshot is None or snapshot.timestamp < now - self.max_age:
            return 0.0, 9999.0
        age_sec = max(0.0, (now - snapshot.timestamp).total_seconds())
        return snapshot.funding_rate, age_sec


class FeatureAssembler:
    def __init__(self, stablecoins: set[str]) -> None:
        self.market = MarketFeatureWindow()
        self.whales = WhaleFlowWindow()
        self.smart_money = SmartMoneySignalWindow()
        self.derivatives = DerivativesSentimentWindow()
        self.orderbook = OrderBookSignalWindow()
        self.funding = FundingSignalWindow()
        self.stablecoins = {item.upper() for item in stablecoins}

    def add_market_tick(self, tick: MarketTick) -> None:
        self.market.add(tick)

    def add_whale_transfer(self, transfer: WhaleTransfer) -> None:
        self.whales.add(transfer)

    def add_smart_money_signal(self, signal: WalletClusterSignal) -> None:
        self.smart_money.add(signal)

    def add_long_short_snapshot(self, snapshot: LongShortSnapshot) -> None:
        self.derivatives.add(snapshot)

    def add_orderbook_snapshot(self, snapshot: OrderBookSnapshot) -> None:
        self.orderbook.add(snapshot)

    def add_funding_snapshot(self, snapshot: FundingSnapshot) -> None:
        self.funding.add(snapshot)

    def snapshot(self, symbol: str) -> FeatureSnapshot:
        (
            price,
            momentum,
            volatility,
            buy_pressure,
            volume,
            ema_fast,
            ema_slow,
            trend_score,
            rsi,
            higher_tf_trend_score,
            higher_tf_momentum_pct,
            regime_score,
            market_regime,
        ) = self.market.snapshot(symbol)
        whale_net_usd, whale_count = self.whales.score_for_symbol(symbol, self.stablecoins)
        smart_score, smart_sync, smart_wallets, smart_usd, smart_age_sec = self.smart_money.score_for_symbol(symbol)
        derivatives_score, global_ratio, top_ratio, taker_ratio, open_interest_value, open_interest_change_pct, derivatives_age_sec = (
            self.derivatives.score_for_symbol(symbol)
        )
        orderbook_imbalance, spread_bps, orderbook_age_sec = self.orderbook.score_for_symbol(symbol)
        funding_rate, funding_age_sec = self.funding.score_for_symbol(symbol)
        return FeatureSnapshot(
            symbol=symbol,
            price=price,
            momentum_pct=momentum,
            realized_volatility=volatility,
            buy_pressure=buy_pressure,
            quote_volume=volume,
            whale_net_usd=whale_net_usd,
            whale_event_count=whale_count,
            generated_at=utc_now(),
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            trend_score=trend_score,
            rsi=rsi,
            smart_money_score=smart_score,
            smart_money_sync=smart_sync,
            smart_money_wallets=smart_wallets,
            smart_money_usd=smart_usd,
            smart_money_age_sec=smart_age_sec,
            derivatives_score=derivatives_score,
            global_long_short_ratio=global_ratio,
            top_long_short_ratio=top_ratio,
            taker_buy_sell_ratio=taker_ratio,
            open_interest_value=open_interest_value,
            open_interest_change_pct=open_interest_change_pct,
            derivatives_age_sec=derivatives_age_sec,
            higher_tf_trend_score=higher_tf_trend_score,
            higher_tf_momentum_pct=higher_tf_momentum_pct,
            regime_score=regime_score,
            market_regime=market_regime,
            orderbook_imbalance=orderbook_imbalance,
            spread_bps=spread_bps,
            orderbook_age_sec=orderbook_age_sec,
            funding_rate=funding_rate,
            funding_age_sec=funding_age_sec,
        )
