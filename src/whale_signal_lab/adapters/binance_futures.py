from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from ..features import clamp
from ..models import FundingSnapshot, LongShortSnapshot, OrderBookSnapshot


def fetch_long_short_snapshot(
    symbol: str,
    base_url: str = "https://fapi.binance.com",
    period: str = "5m",
) -> LongShortSnapshot:
    global_item = _latest(
        base_url,
        "/futures/data/globalLongShortAccountRatio",
        {"symbol": symbol, "period": period, "limit": 2},
    )
    top_item = _latest(
        base_url,
        "/futures/data/topLongShortPositionRatio",
        {"symbol": symbol, "period": period, "limit": 2},
    )
    taker_item = _latest(
        base_url,
        "/futures/data/takerlongshortRatio",
        {"symbol": symbol, "period": period, "limit": 2},
    )
    open_interest_series = _series(
        base_url,
        "/futures/data/openInterestHist",
        {"symbol": symbol, "period": period, "limit": 2},
    )
    open_interest_item = open_interest_series[-1]
    previous_open_interest_item = open_interest_series[-2] if len(open_interest_series) > 1 else open_interest_item
    global_ratio = _float(global_item, "longShortRatio", 1.0)
    top_ratio = _float(top_item, "longShortRatio", 1.0)
    taker_ratio = _float(taker_item, "buySellRatio", 1.0)
    open_interest_value = _float(open_interest_item, "sumOpenInterestValue", 0.0)
    previous_open_interest_value = _float(previous_open_interest_item, "sumOpenInterestValue", open_interest_value)
    open_interest_change_pct = (
        (open_interest_value - previous_open_interest_value) / previous_open_interest_value
        if previous_open_interest_value > 0
        else 0.0
    )
    timestamp_ms = int(
        taker_item.get("timestamp")
        or open_interest_item.get("timestamp")
        or top_item.get("timestamp")
        or global_item.get("timestamp")
        or 0
    )
    return LongShortSnapshot(
        symbol=symbol,
        global_long_account=_float(global_item, "longAccount", 0.5),
        global_short_account=_float(global_item, "shortAccount", 0.5),
        global_ratio=global_ratio,
        top_long_account=_float(top_item, "longAccount", 0.5),
        top_short_account=_float(top_item, "shortAccount", 0.5),
        top_ratio=top_ratio,
        taker_buy_sell_ratio=taker_ratio,
        taker_buy_volume=_float(taker_item, "buyVol", 0.0),
        taker_sell_volume=_float(taker_item, "sellVol", 0.0),
        open_interest_value=open_interest_value,
        open_interest_change_pct=open_interest_change_pct,
        sentiment_score=_sentiment_score(global_ratio, top_ratio, taker_ratio, open_interest_change_pct),
        timestamp=datetime.fromtimestamp(timestamp_ms / 1000, UTC) if timestamp_ms else datetime.now(UTC),
    )


def fetch_long_short_batch(
    symbols: tuple[str, ...],
    base_url: str = "https://fapi.binance.com",
    period: str = "5m",
) -> list[LongShortSnapshot]:
    snapshots: list[LongShortSnapshot] = []
    if not symbols:
        return snapshots
    worker_count = min(4, len(symbols))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(fetch_long_short_snapshot, symbol, base_url, period): symbol
            for symbol in symbols
        }
        for future in as_completed(futures):
            try:
                snapshots.append(future.result())
            except Exception:
                continue
    return snapshots


def fetch_orderbook_snapshot(
    symbol: str,
    base_url: str = "https://fapi.binance.com",
    limit: int = 20,
) -> OrderBookSnapshot:
    payload = _dict_payload(
        base_url,
        "/fapi/v1/depth",
        {"symbol": symbol.upper(), "limit": max(5, min(100, int(limit)))},
    )
    bids = payload.get("bids", [])
    asks = payload.get("asks", [])
    bid_notional = _book_notional(bids)
    ask_notional = _book_notional(asks)
    best_bid = _book_price(bids)
    best_ask = _book_price(asks)
    total = bid_notional + ask_notional
    imbalance = (bid_notional - ask_notional) / total if total > 0 else 0.0
    mid = (best_bid + best_ask) / 2.0 if best_bid > 0 and best_ask > 0 else 0.0
    spread_bps = ((best_ask - best_bid) / mid * 10_000.0) if mid > 0 else 0.0
    return OrderBookSnapshot(
        symbol=symbol.upper(),
        bid_notional=bid_notional,
        ask_notional=ask_notional,
        best_bid=best_bid,
        best_ask=best_ask,
        imbalance=clamp(imbalance, -1.0, 1.0),
        spread_bps=max(0.0, spread_bps),
        timestamp=datetime.now(UTC),
    )


def fetch_funding_snapshot(
    symbol: str,
    base_url: str = "https://fapi.binance.com",
) -> FundingSnapshot:
    payload = _dict_payload(base_url, "/fapi/v1/premiumIndex", {"symbol": symbol.upper()})
    next_time_ms = int(payload.get("nextFundingTime") or 0)
    return FundingSnapshot(
        symbol=symbol.upper(),
        funding_rate=_float(payload, "lastFundingRate", 0.0),
        next_funding_time=datetime.fromtimestamp(next_time_ms / 1000, UTC) if next_time_ms else None,
        mark_price=_float(payload, "markPrice", 0.0),
        index_price=_float(payload, "indexPrice", 0.0),
        timestamp=datetime.now(UTC),
    )


def fetch_orderbook_batch(
    symbols: tuple[str, ...],
    base_url: str = "https://fapi.binance.com",
    limit: int = 20,
) -> list[OrderBookSnapshot]:
    if not symbols:
        return []
    snapshots: list[OrderBookSnapshot] = []
    worker_count = min(4, len(symbols))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(fetch_orderbook_snapshot, symbol, base_url, limit): symbol for symbol in symbols}
        for future in as_completed(futures):
            try:
                snapshots.append(future.result())
            except Exception:
                continue
    return snapshots


def fetch_funding_batch(
    symbols: tuple[str, ...],
    base_url: str = "https://fapi.binance.com",
) -> list[FundingSnapshot]:
    if not symbols:
        return []
    snapshots: list[FundingSnapshot] = []
    worker_count = min(4, len(symbols))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(fetch_funding_snapshot, symbol, base_url): symbol for symbol in symbols}
        for future in as_completed(futures):
            try:
                snapshots.append(future.result())
            except Exception:
                continue
    return snapshots


def _latest(base_url: str, path: str, params: dict[str, object]) -> dict:
    payload = _series(base_url, path, params)
    latest = payload[-1]
    if not isinstance(latest, dict):
        raise RuntimeError(f"Unexpected Binance Futures item from {path}: {latest}")
    return latest


def _series(base_url: str, path: str, params: dict[str, object]) -> list[dict]:
    url = f"{base_url.rstrip('/')}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "whale-signal-lab/0.1"})
    with urllib.request.urlopen(request, timeout=4.5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"Unexpected Binance Futures payload from {path}: {payload}")
    if not all(isinstance(item, dict) for item in payload):
        raise RuntimeError(f"Unexpected Binance Futures series from {path}: {payload}")
    return payload


def _dict_payload(base_url: str, path: str, params: dict[str, object]) -> dict:
    url = f"{base_url.rstrip('/')}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "whale-signal-lab/0.1"})
    with urllib.request.urlopen(request, timeout=4.5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected Binance Futures payload from {path}: {payload}")
    return payload


def _book_notional(rows: object) -> float:
    if not isinstance(rows, list):
        return 0.0
    notional = 0.0
    for row in rows:
        if not isinstance(row, list) or len(row) < 2:
            continue
        try:
            price = float(row[0])
            quantity = float(row[1])
        except (TypeError, ValueError):
            continue
        notional += max(0.0, price * quantity)
    return notional


def _book_price(rows: object) -> float:
    if not isinstance(rows, list) or not rows:
        return 0.0
    first = rows[0]
    if not isinstance(first, list) or not first:
        return 0.0
    try:
        return float(first[0])
    except (TypeError, ValueError):
        return 0.0


def fetch_aggregate_trades(
    symbol: str,
    base_url: str = "https://fapi.binance.com",
    lookback_sec: int = 300,
    limit: int = 1000,
) -> list[dict]:
    end_time_ms = int(time.time() * 1000)
    start_time_ms = end_time_ms - (max(1, lookback_sec) * 1000)
    params = {
        "symbol": symbol.upper(),
        "startTime": start_time_ms,
        "endTime": end_time_ms,
        "limit": max(1, min(1000, int(limit))),
    }
    return _series(base_url, "/fapi/v1/aggTrades", params)


def _float(item: dict, key: str, default: float) -> float:
    try:
        return float(item.get(key, default))
    except (TypeError, ValueError):
        return default


def _ratio_score(ratio: float) -> float:
    return clamp((ratio - 1.0) / 1.5, -1.0, 1.0)


def _sentiment_score(
    global_ratio: float,
    top_ratio: float,
    taker_ratio: float,
    open_interest_change_pct: float = 0.0,
) -> float:
    crowd_contrarian = -_ratio_score(global_ratio)
    top_trader_score = _ratio_score(top_ratio)
    taker_flow_score = _ratio_score(taker_ratio)
    open_interest_score = clamp(open_interest_change_pct * 18.0, -1.0, 1.0)
    return clamp(
        (0.18 * crowd_contrarian)
        + (0.37 * top_trader_score)
        + (0.30 * taker_flow_score)
        + (0.15 * open_interest_score),
        -1.0,
        1.0,
    )
