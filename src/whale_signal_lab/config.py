from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class WalletConfig:
    label: str
    address: str
    notes: str = ""


@dataclass(frozen=True)
class AppConfig:
    mode: str = "demo"
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")
    poll_interval_sec: float = 5.0
    signal_horizon_sec: int = 900
    print_json: bool = False


@dataclass(frozen=True)
class MarketConfig:
    binance_base_url: str = "https://api.binance.com"
    binance_stream_url: str = "wss://stream.binance.com:9443/stream"
    use_websocket: bool = False


@dataclass(frozen=True)
class DerivativesConfig:
    enabled: bool = True
    binance_futures_base_url: str = "https://fapi.binance.com"
    period: str = "5m"
    poll_interval_sec: float = 300.0
    funding_poll_interval_sec: float = 300.0
    orderbook_depth_limit: int = 20


@dataclass(frozen=True)
class OnchainConfig:
    etherscan_base_url: str = "https://api.etherscan.io/v2/api"
    etherscan_api_key_env: str = "ETHERSCAN_API_KEY"
    chainid: str = "1"
    poll_interval_sec: float = 20.0
    min_transfer_usd: float = 1_000_000.0
    stablecoins: tuple[str, ...] = ("USDT", "USDC", "DAI", "FDUSD", "TUSD")

    @property
    def etherscan_api_key(self) -> str:
        return os.getenv(self.etherscan_api_key_env, "")


@dataclass(frozen=True)
class SmartMoneyConfig:
    enabled: bool = True
    chain: str = "bsc"
    chainid: str = "56"
    etherscan_api_key_env: str = "ETHERSCAN_API_KEY"
    poll_interval_sec: float = 300.0
    wallet_limit: int = 10_000
    demo_wallet_count: int = 10_000
    cluster_window_sec: int = 330
    min_cluster_wallets: int = 12
    min_cluster_usd: float = 400_000.0
    min_activity_usd: float = 15_000.0
    cluster_bucket_sec: int = 15
    orderflow_window_sec: int = 300
    max_trades_per_symbol: int = 1000
    max_pages: int = 2
    page_size: int = 500

    @property
    def etherscan_api_key(self) -> str:
        return os.getenv(self.etherscan_api_key_env, "")


@dataclass(frozen=True)
class PaperConfig:
    starting_cash: float = 10_000.0
    risk_per_trade: float = 0.05
    fee_bps: float = 7.5
    slippage_bps: float = 2.0
    gas_fee_usd: float = 0.0
    min_edge_cost_multiple: float = 1.4
    min_confidence_to_trade: float = 0.58
    max_abs_position_usd: float = 1_000.0
    target_position_notional_usd: float = 0.0
    target_margin_usd: float = 1_000.0
    max_leverage: float = 10.0
    futures_margin_mode: bool = False
    risk_reward_ratio: float = 2.0
    min_forecast_rr: float = 0.72
    min_stop_loss_pct: float = 0.003
    entry_cooldown_ticks: int = 18
    min_holding_ticks: int = 4
    reversal_confidence: float = 0.62
    breakeven_trigger_r: float = 0.9
    breakeven_lock_r: float = 0.05
    trailing_trigger_r: float = 0.9
    trailing_distance_r: float = 0.85
    volatility_risk_penalty_threshold: float = 0.008
    volatility_block_penalty: float = 0.018
    high_volatility_position_scale: float = 0.50
    shock_position_scale: float = 0.35
    partial_take_profit_r: float = 0.55
    partial_take_profit_fraction: float = 0.50
    time_stop_ticks: int = 18
    time_stop_min_r: float = 0.10
    min_decisive_trade_pnl: float = 1.0
    loss_streak_limit: int = 2
    loss_streak_cooldown_ticks: int = 48
    loss_streak_position_scale: float = 0.35
    max_session_drawdown_pct: float = 0.003
    max_session_losses: int = 3
    min_session_win_rate: float = 0.40
    min_session_trades_for_guard: int = 3
    global_cooldown_ticks: int = 48
    scout_enabled: bool = True
    scout_position_scale: float = 0.12
    scout_min_confidence_to_trade: float = 0.52
    scout_min_readiness: float = 0.55
    scout_min_priority: float = 0.60
    scout_min_confirmations: int = 3
    scout_max_blockers: int = 2
    scout_max_entries_per_tick: int = 1


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool = False
    enabled_env: str = "TELEGRAM_ENABLED"
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"
    api_ip_env: str = "TELEGRAM_API_IP"
    chat_id: str = ""
    notify_entries: bool = True
    notify_exits: bool = True
    timeout_sec: float = 5.0

    @property
    def is_enabled(self) -> bool:
        value = os.getenv(self.enabled_env, "").strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
        return self.enabled

    @property
    def bot_token(self) -> str:
        return os.getenv(self.bot_token_env, "")

    @property
    def target_chat_id(self) -> str:
        return self.chat_id or os.getenv(self.chat_id_env, "")

    @property
    def api_ip(self) -> str:
        return os.getenv(self.api_ip_env, "").strip()


@dataclass(frozen=True)
class LearnerConfig:
    enabled: bool = True
    log_path: str = "data/decision_log.jsonl"
    state_path: str = "data/learner_state.json"
    outcome_horizon_ticks: int = 12
    min_abs_return: float = 0.0008
    learning_rate: float = 0.08
    quality_min_probability: float = 0.58
    quality_min_expectancy_r: float = 0.04
    quality_warmup_trades: int = 20


@dataclass(frozen=True)
class LabConfig:
    app: AppConfig = field(default_factory=AppConfig)
    market: MarketConfig = field(default_factory=MarketConfig)
    derivatives: DerivativesConfig = field(default_factory=DerivativesConfig)
    onchain: OnchainConfig = field(default_factory=OnchainConfig)
    smart_money: SmartMoneyConfig = field(default_factory=SmartMoneyConfig)
    paper: PaperConfig = field(default_factory=PaperConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    learner: LearnerConfig = field(default_factory=LearnerConfig)
    exchange_addresses: dict[str, str] = field(default_factory=dict)
    wallets: tuple[WalletConfig, ...] = ()


def _section(data: dict, name: str) -> dict:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"Config section [{name}] must be a table.")
    return value


def load_config(path: str | Path) -> LabConfig:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    app_data = _section(raw, "app")
    if "symbols" in app_data:
        app_data = {**app_data, "symbols": tuple(app_data["symbols"])}
    app = AppConfig(**app_data)
    market = MarketConfig(**_section(raw, "market"))
    derivatives = DerivativesConfig(**_section(raw, "derivatives"))
    onchain = OnchainConfig(**_section(raw, "onchain"))
    smart_money = SmartMoneyConfig(**_section(raw, "smart_money"))
    paper = PaperConfig(**_section(raw, "paper"))
    telegram = TelegramConfig(**_section(raw, "telegram"))
    learner = LearnerConfig(**_section(raw, "learner"))
    exchange_addresses = {
        label: address.lower()
        for label, address in _section(raw, "exchange_addresses").items()
        if address and address.lower() != "0x0000000000000000000000000000000000000000"
    }
    wallets = tuple(
        WalletConfig(**item)
        for item in raw.get("wallets", [])
        if item.get("address")
        and item["address"].lower() != "0x0000000000000000000000000000000000000000"
    )
    return LabConfig(
        app=app,
        market=market,
        derivatives=derivatives,
        onchain=onchain,
        smart_money=smart_money,
        paper=paper,
        telegram=telegram,
        learner=learner,
        exchange_addresses=exchange_addresses,
        wallets=wallets,
    )
