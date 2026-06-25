from __future__ import annotations

import argparse
import asyncio
import json

from .adapters.binance import BinanceTestnetOrderValidator
from .app import run_from_config
from .backtesting import run_backtest, run_hyperopt
from .config import load_config
from .models import Direction
from .web_server import serve_web


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Whale Signal Lab")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run realtime or demo signal loop.")
    run_parser.add_argument("--config", default="config.example.toml")
    run_parser.add_argument("--mode", choices=["demo", "live"], default=None)
    run_parser.add_argument("--ticks", type=int, default=10, help="0 means run forever.")
    run_parser.add_argument("--json", action="store_true", help="Print JSON lines.")

    validate_parser = subparsers.add_parser("validate-order", help="Validate a Binance Spot Testnet order.")
    validate_parser.add_argument("--symbol", required=True)
    validate_parser.add_argument("--side", choices=["BUY", "SELL"], required=True)
    validate_parser.add_argument("--quantity", type=float, required=True)

    web_parser = subparsers.add_parser("web", help="Serve the HTML demo cockpit.")
    web_parser.add_argument("--config", default="config.example.toml")
    web_parser.add_argument("--mode", choices=["demo", "live"], default="demo")
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8765)

    backtest_parser = subparsers.add_parser("backtest", help="Replay recent Binance candles through the paper engine.")
    backtest_parser.add_argument("--config", default="config.example.toml")
    backtest_parser.add_argument("--interval", default="5m")
    backtest_parser.add_argument("--limit", type=int, default=500)

    hyperopt_parser = subparsers.add_parser("hyperopt", help="Search exit/risk parameters on recent Binance candles.")
    hyperopt_parser.add_argument("--config", default="config.example.toml")
    hyperopt_parser.add_argument("--interval", default="5m")
    hyperopt_parser.add_argument("--limit", type=int, default=500)
    hyperopt_parser.add_argument("--top", type=int, default=8)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        asyncio.run(run_from_config(args.config, args.mode, args.ticks, args.json))
        return
    if args.command == "validate-order":
        side = Direction.LONG if args.side == "BUY" else Direction.SHORT
        result = BinanceTestnetOrderValidator().validate_market_order(args.symbol, side, args.quantity)
        print(result)
        return
    if args.command == "web":
        serve_web(args.config, args.mode, args.host, args.port)
        return
    if args.command == "backtest":
        result = run_backtest(load_config(args.config), interval=args.interval, limit=args.limit)
        print(_json(result))
        return
    if args.command == "hyperopt":
        result = run_hyperopt(args.config, interval=args.interval, limit=args.limit, top=args.top)
        print(_json(result))
        return
    parser.error(f"Unknown command: {args.command}")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


if __name__ == "__main__":
    main()
