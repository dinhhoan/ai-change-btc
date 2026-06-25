from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from itertools import product
from typing import Iterable

from .adapters.binance import fetch_klines
from .config import LabConfig, PaperConfig, load_config
from .features import FeatureAssembler, base_asset
from .models import LongShortSnapshot, MarketTick, OrderBookSnapshot, PaperOrder, utc_now
from .paper import PaperBroker
from .signals import SignalEngine


def run_backtest(
    config: LabConfig,
    *,
    interval: str = "5m",
    limit: int = 500,
    paper_overrides: dict[str, float | int] | None = None,
) -> dict[str, object]:
    candles = _download_candles(config, interval, limit)
    return run_backtest_on_candles(config, candles, paper_overrides=paper_overrides)


def run_backtest_on_candles(
    config: LabConfig,
    candles: list[dict[str, float | int | str]],
    *,
    paper_overrides: dict[str, float | int] | None = None,
) -> dict[str, object]:
    paper_config = _paper_with_overrides(config.paper, paper_overrides or {})
    features = FeatureAssembler(set(config.onchain.stablecoins))
    engine = SignalEngine(config.onchain.min_transfer_usd, config.app.signal_horizon_sec)
    broker = _broker_from_config(paper_config)
    orders_by_symbol: dict[str, int] = {symbol: 0 for symbol in config.app.symbols}

    for step_index, candle in enumerate(sorted(candles, key=lambda item: int(item["close_time_ms"])), start=1):
        symbol = str(candle["symbol"]).upper()
        if symbol not in config.app.symbols:
            continue
        close_time = datetime.fromtimestamp(int(candle["close_time_ms"]) / 1000.0, UTC)
        tick = MarketTick(
            symbol=symbol,
            price=float(candle["close"]),
            event_time=close_time,
            volume_quote=float(candle.get("volume_quote", 0.0) or 0.0),
            taker_buy_quote=float(candle.get("taker_buy_quote", 0.0) or 0.0),
            source=f"backtest_{candle.get('interval', 'kline')}",
        )
        features.add_market_tick(tick)
        _add_historical_proxies(features, tick)
        exit_order = broker.mark(tick.symbol, tick.price, step_index)
        if exit_order:
            orders_by_symbol[exit_order.symbol] = orders_by_symbol.get(exit_order.symbol, 0) + 1

        signal = engine.evaluate(features.snapshot(symbol))
        order = broker.rebalance_from_signal(signal, step_index)
        if order:
            orders_by_symbol[order.symbol] = orders_by_symbol.get(order.symbol, 0) + 1

    summary = broker.performance_summary()
    orders = broker.orders
    return {
        "performance": summary,
        "orders": [asdict(order) for order in orders],
        "order_count": len(orders),
        "orders_by_symbol": orders_by_symbol,
        "symbol_stats": _symbol_stats(orders),
        "paper": asdict(paper_config),
    }


def run_hyperopt(
    config_path: str,
    *,
    interval: str = "5m",
    limit: int = 500,
    top: int = 8,
) -> dict[str, object]:
    config = load_config(config_path)
    candles = _download_candles(config, interval, limit)
    candidates = []
    grid = {
        "risk_reward_ratio": [2.0, 2.5, 3.0],
        "min_forecast_rr": [0.58, 0.68, 0.78],
        "partial_take_profit_r": [0.55, 0.75, 0.95],
        "trailing_trigger_r": [0.9, 1.2, 1.5],
        "trailing_distance_r": [0.45, 0.65, 0.85],
        "time_stop_ticks": [8, 12, 18],
    }
    keys = list(grid)
    for values in product(*(grid[key] for key in keys)):
        overrides = dict(zip(keys, values, strict=True))
        result = run_backtest_on_candles(config, candles, paper_overrides=overrides)
        performance = result["performance"]
        score = _objective(performance, int(result["order_count"]))
        candidates.append(
            {
                "score": score,
                "overrides": overrides,
                "performance": performance,
                "order_count": result["order_count"],
            }
        )
    ranked = sorted(candidates, key=lambda item: float(item["score"]), reverse=True)
    return {"best": ranked[: max(1, top)], "tested": len(candidates), "interval": interval, "limit": limit}


def _download_candles(config: LabConfig, interval: str, limit: int) -> list[dict[str, float | int | str]]:
    candles: list[dict[str, float | int | str]] = []
    for symbol in config.app.symbols:
        candles.extend(
            fetch_klines(
                symbol,
                base_url=config.market.binance_base_url,
                interval=interval,
                limit=limit,
            )
        )
    return candles


def _add_historical_proxies(features: FeatureAssembler, tick: MarketTick) -> None:
    now = utc_now()
    flow = max(-1.0, min(1.0, (tick.buy_pressure - 0.5) * 2.0))
    taker_ratio = tick.taker_buy_quote / max(1.0, tick.volume_quote - tick.taker_buy_quote)
    top_ratio = max(0.5, min(1.8, 1.0 + flow * 0.35))
    global_ratio = max(0.5, min(2.2, 1.0 - flow * 0.25))
    sentiment = max(-1.0, min(1.0, flow * 0.55))
    features.add_long_short_snapshot(
        LongShortSnapshot(
            symbol=tick.symbol,
            global_long_account=0.5,
            global_short_account=0.5,
            global_ratio=global_ratio,
            top_long_account=0.5,
            top_short_account=0.5,
            top_ratio=top_ratio,
            taker_buy_sell_ratio=max(0.2, min(5.0, taker_ratio)),
            taker_buy_volume=tick.taker_buy_quote,
            taker_sell_volume=max(0.0, tick.volume_quote - tick.taker_buy_quote),
            open_interest_value=tick.volume_quote,
            open_interest_change_pct=0.0,
            sentiment_score=sentiment,
            timestamp=now,
            source="backtest_proxy",
        )
    )
    features.add_orderbook_snapshot(
        OrderBookSnapshot(
            symbol=tick.symbol,
            bid_notional=max(0.0, tick.taker_buy_quote),
            ask_notional=max(0.0, tick.volume_quote - tick.taker_buy_quote),
            best_bid=tick.price * 0.99995,
            best_ask=tick.price * 1.00005,
            imbalance=flow * 0.65,
            spread_bps=1.0,
            timestamp=now,
            source="backtest_proxy",
        )
    )


def _paper_with_overrides(config: PaperConfig, overrides: dict[str, float | int]) -> PaperConfig:
    clean = {key: value for key, value in overrides.items() if hasattr(config, key)}
    return replace(config, **clean)


def _broker_from_config(config: PaperConfig) -> PaperBroker:
    return PaperBroker(
        starting_cash=config.starting_cash,
        risk_per_trade=config.risk_per_trade,
        fee_bps=config.fee_bps,
        slippage_bps=config.slippage_bps,
        min_confidence_to_trade=config.min_confidence_to_trade,
        max_abs_position_usd=config.max_abs_position_usd,
        gas_fee_usd=config.gas_fee_usd,
        min_edge_cost_multiple=config.min_edge_cost_multiple,
        risk_reward_ratio=config.risk_reward_ratio,
        min_forecast_rr=config.min_forecast_rr,
        min_stop_loss_pct=config.min_stop_loss_pct,
        entry_cooldown_ticks=config.entry_cooldown_ticks,
        min_holding_ticks=config.min_holding_ticks,
        reversal_confidence=config.reversal_confidence,
        breakeven_trigger_r=config.breakeven_trigger_r,
        breakeven_lock_r=config.breakeven_lock_r,
        trailing_trigger_r=config.trailing_trigger_r,
        trailing_distance_r=config.trailing_distance_r,
        volatility_risk_penalty_threshold=config.volatility_risk_penalty_threshold,
        volatility_block_penalty=config.volatility_block_penalty,
        high_volatility_position_scale=config.high_volatility_position_scale,
        shock_position_scale=config.shock_position_scale,
        partial_take_profit_r=config.partial_take_profit_r,
        partial_take_profit_fraction=config.partial_take_profit_fraction,
        time_stop_ticks=config.time_stop_ticks,
        time_stop_min_r=config.time_stop_min_r,
        min_decisive_trade_pnl=config.min_decisive_trade_pnl,
        loss_streak_limit=config.loss_streak_limit,
        loss_streak_cooldown_ticks=config.loss_streak_cooldown_ticks,
        loss_streak_position_scale=config.loss_streak_position_scale,
        max_session_drawdown_pct=config.max_session_drawdown_pct,
        max_session_losses=config.max_session_losses,
        min_session_win_rate=config.min_session_win_rate,
        min_session_trades_for_guard=config.min_session_trades_for_guard,
        global_cooldown_ticks=config.global_cooldown_ticks,
    )


def _symbol_stats(orders: Iterable[PaperOrder]) -> dict[str, dict[str, float | int | str]]:
    stats: dict[str, dict[str, float | int | str]] = {}
    for order in orders:
        row = stats.setdefault(
            order.symbol,
            {
                "orders": 0,
                "long_orders": 0,
                "short_orders": 0,
                "notional": 0.0,
                "fees": 0.0,
                "asset": base_asset(order.symbol),
            },
        )
        row["orders"] = int(row["orders"]) + 1
        row["notional"] = float(row["notional"]) + order.notional
        row["fees"] = float(row["fees"]) + order.fee + order.gas_fee
        if order.side.value == "LONG":
            row["long_orders"] = int(row["long_orders"]) + 1
        elif order.side.value == "SHORT":
            row["short_orders"] = int(row["short_orders"]) + 1
    return stats


def _objective(performance: dict[str, object], order_count: int) -> float:
    if order_count < 4:
        return -999.0 + order_count
    net_pnl_pct = float(performance.get("net_pnl_pct", 0.0) or 0.0)
    win_rate = float(performance.get("win_rate", 0.0) or 0.0)
    profit_factor = float(performance.get("profit_factor", 0.0) or 0.0)
    trade_bonus = min(1.5, order_count / 40.0)
    return net_pnl_pct + (win_rate * 8.0) + min(5.0, profit_factor * 1.5) + trade_bonus
