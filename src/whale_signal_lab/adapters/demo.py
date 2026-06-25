from __future__ import annotations

import random
from datetime import timedelta

from ..features import base_asset
from ..models import LongShortSnapshot, MarketTick, WhaleDirection, WhaleTransfer, utc_now


class DemoFeed:
    def __init__(self, symbols: tuple[str, ...], seed: int = 42) -> None:
        self.symbols = symbols
        self.random = random.Random(seed)
        self.step = 0
        self.prices = {symbol: self._start_price(symbol) for symbol in symbols}

    def market_ticks(self) -> list[MarketTick]:
        self.step += 1
        ticks: list[MarketTick] = []
        now = utc_now()
        for symbol in self.symbols:
            drift = self.random.gauss(0.0002, 0.0018)
            if self.step % 8 in (3, 4):
                drift += 0.0012
            self.prices[symbol] = max(0.0001, self.prices[symbol] * (1.0 + drift))
            quote_volume = self.random.uniform(250_000, 2_000_000)
            buy_pressure = max(0.1, min(0.9, 0.52 + drift * 80 + self.random.gauss(0.0, 0.08)))
            ticks.append(
                MarketTick(
                    symbol=symbol,
                    price=round(self.prices[symbol], 8),
                    event_time=now,
                    volume_quote=quote_volume,
                    taker_buy_quote=quote_volume * buy_pressure,
                    source="demo",
                )
            )
        return ticks

    def whale_events(self) -> list[WhaleTransfer]:
        if self.step % 5 != 0:
            return []
        symbol = self.symbols[self.step % len(self.symbols)]
        asset = base_asset(symbol)
        bullish = self.step % 10 == 0
        direction = WhaleDirection.EXCHANGE_OUTFLOW if bullish else WhaleDirection.EXCHANGE_INFLOW
        usd_value = self.random.uniform(1_200_000, 8_000_000)
        amount = usd_value / self.prices[symbol]
        return [
            WhaleTransfer(
                chain="demo",
                tx_hash=f"demo-{self.step}-{symbol}",
                wallet="demo_whale",
                counterparty="demo_exchange",
                token_symbol=asset,
                token_contract=None,
                amount=amount,
                usd_value=usd_value,
                direction=direction,
                timestamp=utc_now() - timedelta(seconds=self.random.randint(0, 60)),
                source="demo",
                labels={"counterparty": "demo_exchange"},
            )
        ]

    def long_short_snapshots(self) -> list[LongShortSnapshot]:
        snapshots: list[LongShortSnapshot] = []
        now = utc_now()
        for symbol in self.symbols:
            crowd_bias = self.random.gauss(0.0, 0.22)
            if self.step % 9 in (0, 1):
                crowd_bias += 0.35
            top_bias = self.random.gauss(0.0, 0.20)
            if self.step % 8 in (3, 4):
                top_bias -= 0.28
            taker_bias = self.random.gauss(0.0, 0.18)
            global_ratio = max(0.25, 1.0 + crowd_bias)
            top_ratio = max(0.25, 1.0 + top_bias)
            taker_ratio = max(0.25, 1.0 + taker_bias)
            sentiment = self._sentiment_score(global_ratio, top_ratio, taker_ratio)
            snapshots.append(
                LongShortSnapshot(
                    symbol=symbol,
                    global_long_account=global_ratio / (1.0 + global_ratio),
                    global_short_account=1.0 / (1.0 + global_ratio),
                    global_ratio=global_ratio,
                    top_long_account=top_ratio / (1.0 + top_ratio),
                    top_short_account=1.0 / (1.0 + top_ratio),
                    top_ratio=top_ratio,
                    taker_buy_sell_ratio=taker_ratio,
                    taker_buy_volume=self.random.uniform(10_000, 90_000) * taker_ratio,
                    taker_sell_volume=self.random.uniform(10_000, 90_000),
                    sentiment_score=sentiment,
                    timestamp=now,
                    source="demo_futures",
                )
            )
        return snapshots

    @staticmethod
    def _start_price(symbol: str) -> float:
        if symbol.startswith("BTC"):
            return 65_000.0
        if symbol.startswith("ETH"):
            return 3_500.0
        if symbol.startswith("SOL"):
            return 150.0
        return 10.0

    @staticmethod
    def _sentiment_score(global_ratio: float, top_ratio: float, taker_ratio: float) -> float:
        crowd_contrarian = -max(-1.0, min(1.0, (global_ratio - 1.0) / 1.5))
        top_trader_score = max(-1.0, min(1.0, (top_ratio - 1.0) / 1.5))
        taker_flow_score = max(-1.0, min(1.0, (taker_ratio - 1.0) / 1.5))
        return max(-1.0, min(1.0, 0.20 * crowd_contrarian + 0.45 * top_trader_score + 0.35 * taker_flow_score))
