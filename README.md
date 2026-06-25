# Whale Signal Lab

Realtime whale-flow research scaffold with Binance market data, Etherscan wallet polling, signal scoring, and a paper-trading broker. It is built as a lab, not an auto-trader. Default behavior never sends real orders.

## What it does

- Tracks market state from Binance 1m klines: price, quote volume, and taker-buy pressure.
- Tracks large ERC-20 transfers from watched wallets through Etherscan V2 when an API key and wallet list are configured.
- Scores the next short-horizon scenario from momentum, whale net flow, order-flow pressure, EMA trend, RSI regime, and volatility.
- Uses a strategy gate so a whale transfer alone cannot trigger an entry without enough independent confirmations.
- Tracks smart-money wallet clusters: demo mode simulates 10,000 wallets; live mode can discover real BSC/EVM counterparties from labelled exchange wallets when an API key is configured.
- Reads Binance Futures long/short sentiment and lets an online learner adjust signal weights from logged outcomes.
- Reads Binance Futures orderbook depth and funding rate to avoid entries with weak execution context.
- Simulates LONG/SHORT/FLAT rebalancing in a paper broker with fees, slippage, partial take profit, trailing stops, time stops, and loss-streak protection.
- Provides backtest and hyperopt commands for recent Binance candles before changing live/demo settings.
- Can validate a Binance Spot Testnet order with `/api/v3/order/test`; this validates only and does not match the order.

This is not financial advice. Treat all output as research telemetry and run forward tests before trusting any signal.

## Quick start

```bash
cd "/Users/hoantran/Tdhoan/crypto-whale-radar"
PYTHONPATH=src python3 -m whale_signal_lab run --config config.example.toml --mode demo --ticks 10
```

Run unit tests:

```bash
cd "/Users/hoantran/Tdhoan/crypto-whale-radar"
python3 -m unittest discover tests
```

Run the HTML demo cockpit:

```bash
cd "/Users/hoantran/Tdhoan/crypto-whale-radar"
PYTHONPATH=src /opt/homebrew/bin/python3 -m whale_signal_lab web --config config.example.toml --mode demo --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

The cockpit is Vietnamese-first and shows paper-trading performance:

- Lãi/Lỗ ròng and percentage return
- Tỷ lệ thắng
- Thắng / Thua
- PnL đã chốt and PnL đang mở
- Phí giao dịch
- Whale net flow and latest signals
- Smart-money wallet clusters, active wallet count, group sync, and group edge
- Current long/short ratio, adaptive learner win rate, and learned signal weights
- Runtime paper settings for starting cash, per-trade risk, max order size, fees, slippage, and gas/network cost
- Pre-trade cost review that can skip entries when expected edge is too small after fee, slippage, and gas
- Regime, higher-timeframe, orderbook, funding, partial-TP, and loss-streak state

## Backtest and hyperopt

Backtest the current settings on recent Binance candles:

```bash
cd "/Users/hoantran/Tdhoan/crypto-whale-radar"
PYTHONPATH=src /opt/homebrew/bin/python3 -m whale_signal_lab backtest --config config.example.toml --interval 5m --limit 500
```

Search exit/risk settings. Use at least 500 candles; shorter samples may produce no trades and are only a smoke test.

```bash
cd "/Users/hoantran/Tdhoan/crypto-whale-radar"
PYTHONPATH=src /opt/homebrew/bin/python3 -m whale_signal_lab hyperopt --config config.example.toml --interval 5m --limit 500 --top 8
```

Backtest uses historical kline flow plus conservative proxies for derivatives/orderbook context because full historical orderbook and funding are not available from the lightweight public pull used here. Treat results as a filter for candidate settings, then forward-test in demo.

## Telegram entry alerts

The app can send a Telegram message when the paper broker opens a new LONG/SHORT position. Tokens are read from environment variables so secrets do not need to be committed.

1. Create a bot with BotFather and copy the bot token.
2. Add the bot to your Telegram channel as an admin.
3. Set the target channel. Public channels can use `@channel_username`; private channels usually need the numeric chat id.
4. Enable `[telegram]` with `TELEGRAM_ENABLED=1` or `enabled = true`, then restart the web server.

```bash
export TELEGRAM_ENABLED=1
export TELEGRAM_BOT_TOKEN="123456:replace_me"
export TELEGRAM_CHAT_ID="@your_channel_username"
```

```toml
[telegram]
enabled = true
notify_entries = true
notify_exits = false
```

Run live Binance public data without Etherscan:

```bash
cd "/Users/hoantran/Tdhoan/crypto-whale-radar"
PYTHONPATH=src python3 -m whale_signal_lab run --config config.example.toml --mode live --ticks 20
```

## Configure whale wallets

1. Copy `.env.example` values into your shell or a local dotenv loader.
2. Set `ETHERSCAN_API_KEY`.
3. Replace the sample wallet in `config.example.toml`.
4. Add verified exchange addresses under `[exchange_addresses]` so the engine can classify inflow/outflow.

Example:

```toml
[exchange_addresses]
binance_hot_1 = "0x..."

[[wallets]]
label = "fund_alpha_whale"
address = "0x..."
```

## Binance Testnet order validation

Create Spot Testnet keys at Binance's testnet site, then set:

```bash
export BINANCE_TESTNET_API_KEY="..."
export BINANCE_TESTNET_API_SECRET="..."
PYTHONPATH=src python3 -m whale_signal_lab validate-order --symbol BTCUSDT --side BUY --quantity 0.001
```

The command calls `POST /api/v3/order/test`, which validates parameters and signature without placing the order in the matching engine.

## Project layout

```text
src/whale_signal_lab/
  adapters/       Binance, Etherscan, and demo feeds
  app.py          Realtime loop
  backtesting.py  Candle replay and parameter search
  web_server.py   Small stdlib HTTP server for the HTML cockpit
  features.py     Rolling market and whale-flow features
  signals.py      Scenario scoring and expected price path
  paper.py        Paper broker with fees and slippage
web/index.html    Browser demo cockpit
tests/            Unit tests for signal and broker behavior
docs/research.md  GitHub/API research notes
docs/chien-luoc-he-thong-vn.md  Tong hop chien luoc he thong bang tieng Viet
docs/gitlab-trading-research.md  GitLab trading-bot research and win-rate ideas
docs/github-x-trading-research.md  GitHub/X research and StrategyGate notes
docs/smart-money-clusters.md  Detecting coordinated wallet groups
docs/adaptive-entry-strategy.md  Logging, learning, and long/short strategy
docs/execution-cost-guard.md  Runtime capital controls and fee/gas guard
```

## Next production steps

- Replace Etherscan polling with a streaming indexer for low-latency transfers.
- Add labelled entity database for exchanges, funds, market makers, bridges, and OTC desks.
- Store ticks/events/orders in SQLite, DuckDB, or TimescaleDB for proper walk-forward evaluation.
- Add performance metrics: hit rate by horizon, drawdown, Sharpe, turnover, slippage sensitivity, and signal attribution.
- Add parameter sweeps for StrategyGate thresholds, EMA windows, RSI bounds, and component weights.
- Persist smart-money wallet profiles and calculate real post-signal edge at 5m/15m/1h horizons.
- Replace JSONL learner logs with SQLite/DuckDB once signal volume grows.
