from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime

from ..models import Direction, MarketTick


def _get_json(url: str, timeout: float = 5.0) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": "whale-signal-lab/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_latest_kline(
    symbol: str,
    base_url: str = "https://api.binance.com",
    interval: str = "1m",
    timeout: float = 10.0,
) -> MarketTick:
    params = urllib.parse.urlencode({"symbol": symbol.upper(), "interval": interval, "limit": 1})
    url = f"{base_url.rstrip('/')}/api/v3/klines?{params}"
    payload = _get_json(url, timeout=timeout)
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"Unexpected Binance kline payload for {symbol}: {payload!r}")
    row = payload[-1]
    close_time_ms = int(row[6])
    return MarketTick(
        symbol=symbol.upper(),
        price=float(row[4]),
        event_time=datetime.fromtimestamp(close_time_ms / 1000.0, UTC),
        volume_quote=float(row[7]),
        taker_buy_quote=float(row[10]),
        source="binance_rest_kline",
    )


def fetch_klines(
    symbol: str,
    base_url: str = "https://api.binance.com",
    interval: str = "5m",
    limit: int = 120,
    timeout: float = 10.0,
) -> list[dict[str, float | int | str]]:
    safe_limit = max(1, min(1000, int(limit)))
    params = urllib.parse.urlencode({"symbol": symbol.upper(), "interval": interval, "limit": safe_limit})
    url = f"{base_url.rstrip('/')}/api/v3/klines?{params}"
    payload = _get_json(url, timeout=timeout)
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected Binance kline payload for {symbol}: {payload!r}")
    candles: list[dict[str, float | int | str]] = []
    for row in payload:
        if not isinstance(row, list) or len(row) < 7:
            continue
        candles.append(
            {
                "symbol": symbol.upper(),
                "interval": interval,
                "open_time_ms": int(row[0]),
                "close_time_ms": int(row[6]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume_quote": float(row[7]) if len(row) > 7 else 0.0,
                "taker_buy_quote": float(row[10]) if len(row) > 10 else 0.0,
            }
        )
    return candles


def fetch_market_batch(symbols: Iterable[str], base_url: str = "https://api.binance.com") -> list[MarketTick]:
    symbol_list = [symbol for symbol in symbols]
    if not symbol_list:
        return []
    worker_count = min(6, len(symbol_list))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        return list(executor.map(lambda symbol: fetch_latest_kline(symbol, base_url=base_url), symbol_list))


class BinanceRestPoller:
    def __init__(self, symbols: Iterable[str], base_url: str, interval_sec: float) -> None:
        self.symbols = tuple(symbol.upper() for symbol in symbols)
        self.base_url = base_url
        self.interval_sec = interval_sec

    async def stream(self) -> AsyncIterator[MarketTick]:
        while True:
            for symbol in self.symbols:
                yield await asyncio.to_thread(fetch_latest_kline, symbol, self.base_url)
            await asyncio.sleep(self.interval_sec)


class BinanceWebSocketStream:
    def __init__(self, symbols: Iterable[str], stream_url: str, interval: str = "1m") -> None:
        self.symbols = tuple(symbol.lower() for symbol in symbols)
        self.stream_url = stream_url.rstrip("/")
        self.interval = interval

    async def stream(self) -> AsyncIterator[MarketTick]:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("Install optional dependency: pip install -e '.[realtime]'") from exc

        streams = "/".join(f"{symbol}@kline_{self.interval}" for symbol in self.symbols)
        url = f"{self.stream_url}?streams={streams}"
        async with websockets.connect(url, ping_interval=20, ping_timeout=60) as websocket:
            async for message in websocket:
                payload = json.loads(message)
                data = payload.get("data", payload)
                if data.get("e") != "kline":
                    continue
                kline = data["k"]
                yield MarketTick(
                    symbol=kline["s"].upper(),
                    price=float(kline["c"]),
                    event_time=datetime.fromtimestamp(int(data["E"]) / 1000.0, UTC),
                    volume_quote=float(kline.get("q", 0.0)),
                    taker_buy_quote=float(kline.get("Q", 0.0)),
                    source="binance_ws_kline",
                )


class BinanceTestnetOrderValidator:
    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_api_url: str = "https://testnet.binance.vision/api",
    ) -> None:
        self.api_key = api_key or os.getenv("BINANCE_TESTNET_API_KEY", "")
        self.api_secret = api_secret or os.getenv("BINANCE_TESTNET_API_SECRET", "")
        self.base_api_url = base_api_url.rstrip("/")

    def validate_market_order(self, symbol: str, side: Direction, quantity: float) -> dict:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("Set BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_API_SECRET first.")
        if side not in (Direction.LONG, Direction.SHORT):
            raise ValueError("Only LONG/SHORT market validation is supported.")
        params = {
            "symbol": symbol.upper(),
            "side": "BUY" if side == Direction.LONG else "SELL",
            "type": "MARKET",
            "quantity": f"{quantity:.8f}".rstrip("0").rstrip("."),
            "timestamp": str(int(time.time() * 1000)),
        }
        query = urllib.parse.urlencode(params)
        signature = hmac.new(self.api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
        body = f"{query}&signature={signature}".encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_api_url}/v3/order/test",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-MBX-APIKEY": self.api_key,
                "User-Agent": "whale-signal-lab/0.1",
            },
        )
        with urllib.request.urlopen(request, timeout=10.0) as response:
            raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {"status": "accepted_by_order_test"}
