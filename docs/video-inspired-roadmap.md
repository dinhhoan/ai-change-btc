# Video-Inspired Roadmap

Source reviewed: https://x.com/arceyul/status/2067158710019887302

Review date: 2026-06-18.

Important limitation: the tweet metadata was reachable through FxTwitter/VxTwitter mirrors, but this machine could not connect to `video.twimg.com` or `pbs.twimg.com`, so the full 31-minute video and thumbnail frames could not be inspected locally. The available metadata says the video is a "complete 30 minute guide to build a trading bot with Claude Fable 5." The ideas below translate that model into a safer and more production-oriented version for this repo.

## What the model appears to be

The video is positioned as an AI-assisted trading bot build:

- An LLM acts as the coding and strategy-assistant layer.
- The bot receives market data, turns it into trading signals, and simulates or places orders.
- The promise is fast construction with an AI model rather than a hand-built quant stack.

For Whale Signal Lab, the useful idea is not "let the model trade directly." The stronger design is "let the model design, explain, and review strategies, while deterministic code executes data ingestion, risk rules, backtests, and paper trades."

## Ideas to import

1. Strategy cockpit

Add a command that prints one compact operating view: latest whale transfers, top symbols by signal strength, current positions, realized paper PnL, and next expected price path.

2. AI strategy spec files

Represent each strategy as a reviewable spec instead of ad hoc code:

```toml
[strategy]
name = "whale_momentum_v1"
horizon_sec = 900
symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

[features]
momentum_weight = 0.42
whale_flow_weight = 0.38
taker_pressure_weight = 0.20

[risk]
min_confidence = 0.58
max_abs_position_usd = 5000
stop_loss_pct = 0.015
take_profit_pct = 0.025
```

The LLM can propose or explain these specs, but the Python engine should validate and execute them.

3. Paper-first safety rail

Keep the current default: no real orders. Binance Testnet validation stays behind an explicit command. Real trading should require a separate adapter, explicit environment variable, and a signed confirmation.

4. Feedback loop

Add a forward-test evaluator that labels each signal after its horizon expires:

- predicted direction
- confidence
- entry price
- horizon price
- max adverse excursion
- max favorable excursion
- simulated fill and fee impact

5. Event journal

Write every market tick, whale event, signal, and paper order to SQLite or DuckDB. This makes the bot auditable and lets the LLM summarize mistakes without hallucinating from memory.

6. Prompted review, deterministic execution

Use an LLM for:

- explaining why the bot entered or stayed flat
- generating candidate strategy specs
- reviewing poor trades after the fact
- creating natural-language market briefs

Do not use an LLM for:

- directly placing orders
- bypassing risk limits
- calculating balances or signatures
- making irreversible exchange calls

## Recommended next build step

Build `whale_signal_lab cockpit`:

- Pull live Binance market data.
- Pull configured whale wallets when Etherscan key exists.
- Evaluate signals.
- Show a terminal dashboard snapshot.
- Save every snapshot to `data/journal.sqlite`.
- Print an AI-ready JSON summary that can be pasted into any LLM for review.

This gives the project the same "AI-assisted trading bot" energy as the video while keeping the execution layer inspectable and testable.

