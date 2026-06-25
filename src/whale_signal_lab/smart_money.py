from __future__ import annotations

import random
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import log10

from .adapters.binance_futures import fetch_aggregate_trades
from .features import base_asset, clamp
from .models import Direction, LongShortSnapshot, WalletActivity, WalletClusterSignal, utc_now


TOKEN_ALIASES = {
    "BTCB": "BTC",
    "WBTC": "BTC",
    "WETH": "ETH",
    "WBNB": "BNB",
}


@dataclass
class WalletProfile:
    wallet: str
    activity_count: int = 0
    total_usd: float = 0.0
    last_seen: datetime | None = None
    symbols: set[str] = field(default_factory=set)
    edge_score: float = 0.55

    @property
    def rank_score(self) -> float:
        return self.total_usd * (1.0 + self.activity_count / 25.0)


class SmartMoneyClusterEngine:
    def __init__(
        self,
        wallet_limit: int = 10_000,
        window_sec: int = 240,
        min_cluster_wallets: int = 18,
        min_cluster_usd: float = 250_000.0,
    ) -> None:
        self.wallet_limit = max(100, wallet_limit)
        self.window = timedelta(seconds=max(30, window_sec))
        self.min_cluster_wallets = max(3, min_cluster_wallets)
        self.min_cluster_usd = max(1.0, min_cluster_usd)
        self._profiles: dict[str, WalletProfile] = {}
        self._recent: deque[WalletActivity] = deque()
        self._seen_activity_keys: set[str] = set()
        self._seen_activity_order: deque[tuple[str, datetime]] = deque()

    def ingest(self, activities: list[WalletActivity]) -> list[WalletClusterSignal]:
        for activity in activities:
            key = self._activity_key(activity)
            if key in self._seen_activity_keys:
                continue
            self._seen_activity_keys.add(key)
            self._seen_activity_order.append((key, activity.timestamp))
            self._recent.append(activity)
            profile = self._profiles.get(activity.wallet)
            if profile is None:
                profile = WalletProfile(wallet=activity.wallet, edge_score=self._edge_from_wallet(activity.wallet))
                self._profiles[activity.wallet] = profile
            profile.activity_count += max(1, activity.tx_count)
            profile.total_usd += activity.usd_value
            profile.last_seen = activity.timestamp
            profile.symbols.add(activity.symbol)
        self._prune_recent()
        self._trim_profiles()
        return self.cluster_signals()

    def summary(self) -> dict[str, float | int]:
        active_cutoff = utc_now() - self.window
        active_wallets = {item.wallet for item in self._recent if item.timestamp >= active_cutoff}
        entity_label = self._entity_label()
        return {
            "tracked_wallets": len(self._profiles),
            "active_wallets": len(active_wallets),
            "tracked_entities": len(self._profiles),
            "active_entities": len(active_wallets),
            "entity_label": entity_label,
            "recent_events": len(self._recent),
            "wallet_limit": self.wallet_limit,
        }

    def orderflow_stats(self) -> dict[str, dict[str, float | int]]:
        cutoff = utc_now() - self.window
        stats: dict[str, dict[str, float | int]] = {}
        for item in self._recent:
            if item.timestamp < cutoff or item.source != "binance_agg_trades":
                continue
            symbol_stats = stats.setdefault(
                item.symbol,
                {
                    "long_usd": 0.0,
                    "short_usd": 0.0,
                    "long_trades": 0,
                    "short_trades": 0,
                    "latest_ts": 0.0,
                },
            )
            if item.direction == Direction.LONG:
                symbol_stats["long_usd"] = float(symbol_stats["long_usd"]) + item.usd_value
                symbol_stats["long_trades"] = int(symbol_stats["long_trades"]) + max(1, item.tx_count)
            elif item.direction == Direction.SHORT:
                symbol_stats["short_usd"] = float(symbol_stats["short_usd"]) + item.usd_value
                symbol_stats["short_trades"] = int(symbol_stats["short_trades"]) + max(1, item.tx_count)
            symbol_stats["latest_ts"] = max(float(symbol_stats["latest_ts"]), item.timestamp.timestamp())
        return stats

    def cluster_signals(self) -> list[WalletClusterSignal]:
        now = utc_now()
        cutoff = now - self.window
        grouped: dict[tuple[str, Direction, str], list[WalletActivity]] = defaultdict(list)
        for activity in self._recent:
            if activity.timestamp < cutoff:
                continue
            cluster_hint = activity.cluster_hint or self._behavior_key(activity)
            grouped[(activity.symbol, activity.direction, cluster_hint)].append(activity)

        signals: list[WalletClusterSignal] = []
        for (symbol, direction, cluster_id), items in grouped.items():
            wallets = {item.wallet for item in items}
            uses_orderflow = any(item.source == "binance_agg_trades" for item in items)
            participant_count = sum(max(1, item.tx_count) for item in items) if uses_orderflow else len(wallets)
            total_usd = sum(item.usd_value for item in items)
            if participant_count < self.min_cluster_wallets or total_usd < self.min_cluster_usd:
                continue

            edge = self._orderflow_edge(items) if uses_orderflow else self._average_edge(wallets)
            wallet_factor = clamp(participant_count / self.min_cluster_wallets, 0.0, 2.5) / 2.5
            usd_factor = clamp(log10(max(total_usd, 10.0) / self.min_cluster_usd + 1.0), 0.0, 1.0)
            sync_score = clamp((wallet_factor * 0.58) + (usd_factor * 0.42), 0.0, 1.0)
            signed = 1.0 if direction == Direction.LONG else -1.0
            score = clamp(signed * sync_score * clamp(edge / 0.62, 0.35, 1.25), -1.0, 1.0)
            confidence = clamp(0.42 + sync_score * 0.36 + max(0.0, edge - 0.50) * 0.70, 0.0, 0.94)
            rationale = (
                f"{participant_count} nhip lenh dong pha {direction} tren {symbol}, "
                f"sync={sync_score:.2f}, edge={edge:.2f}"
                if uses_orderflow
                else (
                    f"{len(wallets)} wallets aligned {direction} on {symbol}, "
                    f"sync={sync_score:.2f}, edge={edge:.2f}"
                )
            )
            signals.append(
                WalletClusterSignal(
                    symbol=symbol,
                    cluster_id=cluster_id,
                    direction=direction,
                    wallet_count=participant_count,
                    total_usd=round(total_usd, 2),
                    sync_score=round(sync_score, 4),
                    historical_edge=round(edge, 4),
                    score=round(score, 4),
                    confidence=round(confidence, 4),
                    rationale=rationale,
                    generated_at=now,
                )
            )
        return sorted(signals, key=lambda item: abs(item.score) * item.confidence, reverse=True)

    def _prune_recent(self) -> None:
        cutoff = utc_now() - self.window
        while self._recent and self._recent[0].timestamp < cutoff:
            self._recent.popleft()
        while self._seen_activity_order and self._seen_activity_order[0][1] < cutoff:
            key, _ = self._seen_activity_order.popleft()
            self._seen_activity_keys.discard(key)

    def _trim_profiles(self) -> None:
        if len(self._profiles) <= self.wallet_limit:
            return
        ranked = sorted(self._profiles.values(), key=lambda profile: profile.rank_score, reverse=True)
        keep = {profile.wallet for profile in ranked[: self.wallet_limit]}
        self._profiles = {wallet: profile for wallet, profile in self._profiles.items() if wallet in keep}

    def _average_edge(self, wallets: set[str]) -> float:
        edges = [self._profiles[wallet].edge_score for wallet in wallets if wallet in self._profiles]
        return sum(edges) / len(edges) if edges else 0.55

    def _entity_label(self) -> str:
        if any(item.source == "binance_agg_trades" for item in self._recent):
            return "nhip_lenh"
        return "wallet"

    def _orderflow_edge(self, items: list[WalletActivity]) -> float:
        if not items:
            return 0.55
        total_usd = sum(item.usd_value for item in items)
        trade_units = sum(max(1, item.tx_count) for item in items)
        timestamps = [item.timestamp for item in items]
        span_seconds = (max(timestamps) - min(timestamps)).total_seconds() if len(timestamps) > 1 else 0.0
        size_bonus = clamp(total_usd / max(self.min_cluster_usd, 1.0), 0.0, 2.0)
        trade_bonus = clamp(trade_units / max(self.min_cluster_wallets, 1), 0.0, 2.0)
        timing_bonus = 1.0 - clamp(span_seconds / max(self.window.total_seconds(), 1.0), 0.0, 1.0)
        return clamp(0.50 + (size_bonus * 0.09) + (trade_bonus * 0.08) + (timing_bonus * 0.07), 0.50, 0.86)

    @staticmethod
    def _behavior_key(activity: WalletActivity) -> str:
        minute_bucket = int(activity.timestamp.timestamp() // 180)
        return f"{activity.chain}:{activity.symbol}:{activity.direction}:{minute_bucket}"

    @staticmethod
    def _activity_key(activity: WalletActivity) -> str:
        return f"{activity.source}:{activity.wallet}:{activity.symbol}:{activity.direction}:{activity.timestamp.timestamp():.3f}"

    @staticmethod
    def _edge_from_wallet(wallet: str) -> float:
        sample = sum(ord(char) for char in wallet[-8:])
        return 0.50 + (sample % 24) / 100.0


class DemoSmartMoneyFeed:
    def __init__(self, symbols: tuple[str, ...], wallet_count: int = 10_000, seed: int = 7) -> None:
        self.symbols = symbols
        self.wallet_count = wallet_count
        self.random = random.Random(seed)
        self.wallets = [f"0x{index:040x}" for index in range(1, wallet_count + 1)]
        self.cluster_count = 20

    def activities(self, step: int) -> list[WalletActivity]:
        now = utc_now()
        activities: list[WalletActivity] = []
        wave = step % 4 == 0 or step % 7 == 0
        cluster_id = f"demo_cluster_{step % self.cluster_count:02d}"
        symbol = self.symbols[step % len(self.symbols)]
        direction = Direction.LONG if step % 8 in (0, 1, 2) else Direction.SHORT
        if wave:
            start = (step * 317) % max(1, self.wallet_count - 260)
            selected = self.wallets[start : start + self.random.randint(90, 240)]
            for wallet in selected:
                activities.append(
                    WalletActivity(
                        chain="bsc-demo",
                        wallet=wallet,
                        symbol=symbol,
                        token_symbol=base_asset(symbol),
                        direction=direction,
                        usd_value=self.random.uniform(8_000, 95_000),
                        tx_count=self.random.randint(1, 4),
                        timestamp=now - timedelta(seconds=self.random.randint(0, 120)),
                        source="demo",
                        cluster_hint=cluster_id,
                        labels={"pattern": "coordinated_wave"},
                    )
                )

        for noise_index in range(self.random.randint(12, 36)):
            wallet = self.wallets[self.random.randrange(self.wallet_count)]
            noise_symbol = self.random.choice(self.symbols)
            activities.append(
                WalletActivity(
                    chain="bsc-demo",
                    wallet=wallet,
                    symbol=noise_symbol,
                    token_symbol=base_asset(noise_symbol),
                    direction=self.random.choice((Direction.LONG, Direction.SHORT)),
                    usd_value=self.random.uniform(1_000, 18_000),
                    tx_count=1,
                    timestamp=now - timedelta(seconds=self.random.randint(0, 300)),
                    source="demo",
                    cluster_hint=f"background_{step}_{noise_index}",
                    labels={"pattern": "background"},
                )
            )
        return activities


def fetch_exchange_counterparty_activities(
    client,
    exchange_addresses: dict[str, str],
    symbols: tuple[str, ...],
    price_by_token: dict[str, float],
    min_usd: float,
    max_pages: int = 2,
    page_size: int = 500,
    chain: str = "bsc",
) -> list[WalletActivity]:
    symbol_by_base = {base_asset(symbol).upper(): symbol for symbol in symbols}
    activities: list[WalletActivity] = []
    seen: set[tuple[str, str]] = set()
    exchange_lookup = {address.lower(): label for label, address in exchange_addresses.items()}
    for label, exchange_address in exchange_addresses.items():
        exchange = exchange_address.lower()
        for page in range(1, max_pages + 1):
            for raw in client.token_transfers(exchange, page=page, offset=page_size):
                tx_hash = str(raw.get("hash", ""))
                from_addr = str(raw.get("from", "")).lower()
                to_addr = str(raw.get("to", "")).lower()
                token = _normalize_token(str(raw.get("tokenSymbol") or "").upper())
                symbol = symbol_by_base.get(token)
                if not symbol:
                    continue
                amount = _raw_amount(raw)
                usd_value = amount * price_by_token.get(token, 0.0)
                if usd_value < min_usd:
                    continue
                if from_addr == exchange:
                    wallet = to_addr
                    direction = Direction.LONG
                    flow = "exchange_outflow"
                elif to_addr == exchange:
                    wallet = from_addr
                    direction = Direction.SHORT
                    flow = "exchange_inflow"
                else:
                    continue
                key = (tx_hash, wallet)
                if key in seen or wallet in exchange_lookup:
                    continue
                seen.add(key)
                timestamp = datetime.fromtimestamp(int(raw.get("timeStamp", "0")), UTC)
                activities.append(
                    WalletActivity(
                        chain=chain,
                        wallet=wallet,
                        symbol=symbol,
                        token_symbol=token,
                        direction=direction,
                        usd_value=usd_value,
                        tx_count=1,
                        timestamp=timestamp,
                        source="etherscan_v2",
                        cluster_hint=f"{label}:{flow}:{symbol}",
                        labels={"exchange": label, "flow": flow, "tx": tx_hash},
                    )
                )
    return activities


def fetch_binance_orderflow_activities(
    symbols: tuple[str, ...],
    derivatives: list[LongShortSnapshot],
    base_url: str = "https://fapi.binance.com",
    lookback_sec: int = 300,
    min_trade_usd: float = 15_000.0,
    cluster_bucket_sec: int = 15,
    max_trades_per_symbol: int = 1000,
) -> list[WalletActivity]:
    snapshot_by_symbol = {item.symbol: item for item in derivatives}
    activities: list[WalletActivity] = []
    if not symbols:
        return activities

    worker_count = min(4, len(symbols))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(
                fetch_aggregate_trades,
                symbol,
                base_url=base_url,
                lookback_sec=lookback_sec,
                limit=max_trades_per_symbol,
            ): symbol
            for symbol in symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            snapshot = snapshot_by_symbol.get(symbol)
            try:
                trades = future.result()
            except Exception:
                continue
            for trade in trades:
                activity = _trade_to_activity(symbol, trade, snapshot, min_trade_usd, cluster_bucket_sec)
                if activity is not None:
                    activities.append(activity)
    return activities


def _trade_to_activity(
    symbol: str,
    trade: dict,
    snapshot: LongShortSnapshot | None,
    min_trade_usd: float,
    cluster_bucket_sec: int,
) -> WalletActivity | None:
    price = _float(trade.get("p"))
    quantity = _float(trade.get("q"))
    timestamp_ms = int(trade.get("T", 0) or 0)
    if price <= 0 or quantity <= 0 or timestamp_ms <= 0:
        return None
    usd_value = price * quantity
    if usd_value < min_trade_usd:
        return None
    direction = Direction.SHORT if bool(trade.get("m")) else Direction.LONG
    size_band = _size_band(usd_value)
    bucket = timestamp_ms // max(1, cluster_bucket_sec * 1000)
    trade_count = max(1, int(trade.get("l", 0) or 0) - int(trade.get("f", 0) or 0) + 1)
    derivative_bias = "neutral"
    if snapshot is not None:
        if direction == Direction.LONG and snapshot.sentiment_score > 0.08:
            derivative_bias = "aligned"
        elif direction == Direction.SHORT and snapshot.sentiment_score < -0.08:
            derivative_bias = "aligned"
        else:
            derivative_bias = "fading"
    return WalletActivity(
        chain="binance-futures",
        wallet=f"{symbol}:{trade.get('a', timestamp_ms)}",
        symbol=symbol,
        token_symbol=base_asset(symbol),
        direction=direction,
        usd_value=usd_value,
        tx_count=trade_count,
        timestamp=datetime.fromtimestamp(timestamp_ms / 1000, UTC),
        source="binance_agg_trades",
        cluster_hint=f"binance:{symbol}:{direction}:{bucket}:{size_band}:{derivative_bias}",
        labels={
            "price": f"{price:.6f}",
            "quantity": f"{quantity:.6f}",
            "size_band": size_band,
            "derivative_bias": derivative_bias,
        },
    )


def _size_band(usd_value: float) -> str:
    if usd_value >= 1_000_000:
        return "1m+"
    if usd_value >= 500_000:
        return "500k"
    if usd_value >= 250_000:
        return "250k"
    if usd_value >= 100_000:
        return "100k"
    if usd_value >= 50_000:
        return "50k"
    return "15k"


def _float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_token(token: str) -> str:
    return TOKEN_ALIASES.get(token, token)


def _raw_amount(raw: dict) -> float:
    decimals = int(raw.get("tokenDecimal") or 0)
    value = int(raw.get("value") or 0)
    return value / (10**decimals if decimals else 1)
