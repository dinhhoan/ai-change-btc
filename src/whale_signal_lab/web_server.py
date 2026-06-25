from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse

from .adapters.binance import fetch_klines
from .app import LabRunner
from .config import LabConfig, load_config


WEB_ROOT = Path(__file__).resolve().parents[2] / "web"


class DemoState:
    def __init__(self, config_path: str, mode: str) -> None:
        self.config_path = config_path
        self.mode = mode
        self.paper_overrides: dict[str, float] = {}
        self._lock = Lock()
        self.runner = LabRunner(self._config(), mode=mode)
        self._last_snapshot: dict | None = self._describe_unlocked()

    def reset(self, paper_overrides: dict[str, float] | None = None) -> dict:
        with self._lock:
            if paper_overrides:
                self.paper_overrides.update(paper_overrides)
            self.runner = LabRunner(self._config(), mode=self.mode)
            self._last_snapshot = self._describe_unlocked()
            return self._last_snapshot

    def describe(self) -> dict:
        if self._lock.acquire(blocking=False):
            try:
                self._last_snapshot = self._describe_unlocked()
                return self._last_snapshot
            finally:
                self._lock.release()
        if self._last_snapshot is not None:
            snapshot = dict(self._last_snapshot)
            warnings = list(snapshot.get("data_warnings", []))
            warnings.append("Dang cap nhat tick; hien thi snapshot gan nhat.")
            snapshot["data_warnings"] = warnings[-12:]
            return snapshot
        return {
            "tick": 0,
            "mode": self.mode,
            "data_warnings": ["Dang khoi tao runner; vui long thu lai sau."],
        }

    def _describe_unlocked(self) -> dict:
        return {
            "tick": self.runner.tick_count,
            "mode": self.runner.mode,
            "equity": self.runner.paper.equity(),
            "cash": self.runner.paper.cash,
            "performance": self.runner.paper.performance_summary(),
            "symbols": self.runner.config.app.symbols,
            "order_count": len(self.runner.paper.orders),
            "recent_orders": self.runner.paper.orders[-80:],
            "learner_summary": self.runner.learner.summary(),
            "smart_money_summary": self.runner.smart_money.summary(),
            "data_warnings": self.runner.data_warnings[-12:],
            "paper_settings": asdict(self.runner.config.paper),
            "telegram": self.runner.telegram.status(),
            "trade_reviews": self.runner.paper.trade_reviews[-12:],
            "skipped_trades": self.runner.paper.skipped_trades[-12:],
        }

    def tick(self) -> dict:
        with self._lock:
            self._last_snapshot = asyncio.run(self.runner.step())
            return self._last_snapshot

    def _config(self) -> LabConfig:
        config = load_config(self.config_path)
        if not self.paper_overrides:
            return config
        paper = replace(config.paper, **self.paper_overrides)
        return replace(config, paper=paper)


class DemoRequestHandler(BaseHTTPRequestHandler):
    state: DemoState

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._send_file(WEB_ROOT / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/api/state":
            self._send_json(self.state.describe())
            return
        if parsed.path == "/api/tick":
            params = parse_qs(parsed.query)
            steps = max(1, min(20, int(params.get("steps", ["1"])[0])))
            snapshot = None
            for _ in range(steps):
                snapshot = self.state.tick()
            self._send_json(snapshot or self.state.describe())
            return
        if parsed.path == "/api/klines":
            self._send_json(self._klines(parsed.query))
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/reset":
            self._send_json(self.state.reset(self._paper_overrides()))
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _paper_overrides(self) -> dict[str, float]:
        content_length = int(self.headers.get("Content-Length") or 0)
        if content_length <= 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        paper = payload.get("paper", payload)
        if not isinstance(paper, dict):
            return {}
        allowed = {
            "starting_cash": (100.0, 10_000_000.0),
            "risk_per_trade": (0.01, 1.0),
            "fee_bps": (0.0, 100.0),
            "slippage_bps": (0.0, 100.0),
            "gas_fee_usd": (0.0, 1_000.0),
            "min_edge_cost_multiple": (0.0, 20.0),
            "min_confidence_to_trade": (0.0, 0.99),
            "max_abs_position_usd": (1.0, 10_000_000.0),
            "risk_reward_ratio": (1.0, 10.0),
            "min_forecast_rr": (0.3, 2.0),
            "breakeven_trigger_r": (0.1, 5.0),
            "breakeven_lock_r": (0.0, 1.0),
            "trailing_trigger_r": (0.2, 8.0),
            "trailing_distance_r": (0.05, 5.0),
            "volatility_risk_penalty_threshold": (0.0, 0.1),
            "volatility_block_penalty": (0.0, 0.2),
            "high_volatility_position_scale": (0.05, 1.0),
            "shock_position_scale": (0.05, 1.0),
        }
        overrides: dict[str, float] = {}
        for key, (minimum, maximum) in allowed.items():
            if key not in paper:
                continue
            try:
                value = float(paper[key])
            except (TypeError, ValueError):
                continue
            overrides[key] = max(minimum, min(maximum, value))
        return overrides

    def _klines(self, query: str) -> dict[str, object]:
        params = parse_qs(query)
        allowed_intervals = {"1m", "3m", "5m", "15m"}
        interval = params.get("interval", ["5m"])[0]
        if interval not in allowed_intervals:
            interval = "5m"
        try:
            limit = int(params.get("limit", ["120"])[0])
        except ValueError:
            limit = 120
        limit = max(20, min(1000, limit))
        symbols = self.state.runner.config.app.symbols
        base_url = self.state.runner.config.market.binance_base_url
        candles: dict[str, object] = {}
        errors: dict[str, str] = {}
        for symbol in symbols:
            try:
                candles[symbol] = fetch_klines(symbol, base_url=base_url, interval=interval, limit=limit)
            except Exception as exc:  # pragma: no cover - network-dependent fallback
                errors[symbol] = str(exc)
                candles[symbol] = []
        return {
            "interval": interval,
            "limit": limit,
            "candles": candles,
            "errors": errors,
        }

    def _send_file(self, path: Path, content_type: str) -> None:
        try:
            body = path.read_bytes()
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, default=_json_default, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    return str(value)


def serve_web(config_path: str, mode: str, host: str, port: int) -> None:
    DemoRequestHandler.state = DemoState(config_path, mode)
    server = ThreadingHTTPServer((host, port), DemoRequestHandler)
    print(f"Whale Signal Lab demo: http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
