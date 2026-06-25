from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def utc_now() -> datetime:
    return datetime.now(UTC)


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class WhaleDirection(StrEnum):
    EXCHANGE_INFLOW = "exchange_inflow"
    EXCHANGE_OUTFLOW = "exchange_outflow"
    WHALE_IN = "whale_in"
    WHALE_OUT = "whale_out"
    WALLET_TO_WALLET = "wallet_to_wallet"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MarketTick:
    symbol: str
    price: float
    event_time: datetime
    volume_quote: float = 0.0
    taker_buy_quote: float = 0.0
    source: str = "binance"

    @property
    def buy_pressure(self) -> float:
        if self.volume_quote <= 0:
            return 0.5
        return max(0.0, min(1.0, self.taker_buy_quote / self.volume_quote))


@dataclass(frozen=True)
class WhaleTransfer:
    chain: str
    tx_hash: str
    wallet: str
    counterparty: str
    token_symbol: str
    token_contract: str | None
    amount: float
    usd_value: float
    direction: WhaleDirection
    timestamp: datetime
    source: str = "etherscan"
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WalletActivity:
    chain: str
    wallet: str
    symbol: str
    token_symbol: str
    direction: Direction
    usd_value: float
    tx_count: int
    timestamp: datetime
    source: str = "smart_money"
    cluster_hint: str = ""
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WalletClusterSignal:
    symbol: str
    cluster_id: str
    direction: Direction
    wallet_count: int
    total_usd: float
    sync_score: float
    historical_edge: float
    score: float
    confidence: float
    rationale: str
    generated_at: datetime


@dataclass(frozen=True)
class LongShortSnapshot:
    symbol: str
    global_long_account: float
    global_short_account: float
    global_ratio: float
    top_long_account: float
    top_short_account: float
    top_ratio: float
    taker_buy_sell_ratio: float
    taker_buy_volume: float
    taker_sell_volume: float
    open_interest_value: float
    open_interest_change_pct: float
    sentiment_score: float
    timestamp: datetime
    source: str = "binance_futures"


@dataclass(frozen=True)
class OrderBookSnapshot:
    symbol: str
    bid_notional: float
    ask_notional: float
    best_bid: float
    best_ask: float
    imbalance: float
    spread_bps: float
    timestamp: datetime
    source: str = "binance_futures_depth"


@dataclass(frozen=True)
class FundingSnapshot:
    symbol: str
    funding_rate: float
    next_funding_time: datetime | None
    mark_price: float
    index_price: float
    timestamp: datetime
    source: str = "binance_futures_premium_index"


@dataclass(frozen=True)
class FeatureSnapshot:
    symbol: str
    price: float
    momentum_pct: float
    realized_volatility: float
    buy_pressure: float
    quote_volume: float
    whale_net_usd: float
    whale_event_count: int
    generated_at: datetime
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    trend_score: float = 0.0
    rsi: float = 50.0
    smart_money_score: float = 0.0
    smart_money_sync: float = 0.0
    smart_money_wallets: int = 0
    smart_money_usd: float = 0.0
    smart_money_age_sec: float = 9999.0
    derivatives_score: float = 0.0
    global_long_short_ratio: float = 1.0
    top_long_short_ratio: float = 1.0
    taker_buy_sell_ratio: float = 1.0
    open_interest_value: float = 0.0
    open_interest_change_pct: float = 0.0
    derivatives_age_sec: float = 9999.0
    higher_tf_trend_score: float = 0.0
    higher_tf_momentum_pct: float = 0.0
    regime_score: float = 0.0
    market_regime: str = "unknown"
    orderbook_imbalance: float = 0.0
    spread_bps: float = 0.0
    orderbook_age_sec: float = 9999.0
    funding_rate: float = 0.0
    funding_age_sec: float = 9999.0


@dataclass(frozen=True)
class PricePathPoint:
    seconds_ahead: int
    expected_price: float
    lower_band: float
    upper_band: float


@dataclass(frozen=True)
class Signal:
    symbol: str
    direction: Direction
    confidence: float
    score: float
    price: float
    horizon_sec: int
    components: dict[str, float]
    rationale: str
    expected_path: list[PricePathPoint]
    generated_at: datetime


@dataclass(frozen=True)
class PaperOrder:
    symbol: str
    side: Direction
    quantity: float
    fill_price: float
    notional: float
    fee: float
    reason: str
    timestamp: datetime
    gas_fee: float = 0.0
    slippage_cost: float = 0.0
    estimated_edge: float = 0.0
    total_execution_cost: float = 0.0


@dataclass(frozen=True)
class TradePlan:
    symbol: str
    side: Direction
    entry_price: float
    stop_price: float
    take_profit_price: float
    risk_per_unit: float
    rr_ratio: float
    created_tick: int
    partial_taken: bool = False


@dataclass
class Position:
    symbol: str
    quantity: float = 0.0
    avg_price: float = 0.0

    def market_value(self, mark_price: float) -> float:
        return self.quantity * mark_price
