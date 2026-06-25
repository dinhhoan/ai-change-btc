# GitHub and X Trading Research

Research timestamp: 2026-06-18.

Goal: improve Whale Signal Lab without pretending that any public bot is automatically profitable. The useful pattern across mature projects is to separate signal generation, risk gates, simulation, and performance analytics.

## GitHub projects reviewed

| Project | Useful pattern | Applied here |
| --- | --- | --- |
| [Freqtrade](https://github.com/freqtrade/freqtrade) | Dry-run first, backtesting, money management, WebUI, performance reporting, and strategy optimization. | Keep this project paper-first and make win rate/PnL visible in the cockpit before any real order path. |
| [Hummingbot](https://github.com/hummingbot/hummingbot) | Exchange connector discipline, high-frequency bot architecture, market-making/arbitrage topics, frequent releases. | Treat exchange adapters as replaceable modules and avoid coupling Binance data to the signal model. |
| [Jesse](https://github.com/jesse-ai/jesse) | Research workflow for defining strategies, backtesting, optimization, and live trading. | Keep strategy logic deterministic and testable instead of hiding it inside UI code. |
| [OctoBot](https://github.com/Drakkar-Software/OctoBot) | Built-in strategies, TradingView/social/technical indicators, paper trading, and backtesting before automation. | Add technical confirmations around whale flow: EMA trend and RSI regime checks. |
| [VectorBT](https://github.com/polakowo/vectorbt) | Large-scale parameter sweeps, performance analytics, walk-forward testing, and signal tooling. | Next step should be a batch evaluator for weights and thresholds, not manual tuning. |
| [Backtesting.py](https://github.com/kernc/backtesting.py) | Simple backtest API with win rate, profit factor, expectancy, and optimizer output. | Extend the paper broker scorecard toward expectancy, drawdown, and profit factor. |
| [CCXT](https://github.com/ccxt/ccxt) | Unified market-data and trading API across more than 100 exchanges. | Keep future exchange expansion behind adapter interfaces. |
| [QuantConnect LEAN](https://github.com/QuantConnect/Lean) | Event-driven engine, modular plug-in points, local backtest/optimization/live workflows. | Long-term architecture should replay events deterministically before deploying live. |

## X signals checked

X public search was limited from this environment, so I only used project/account metadata that could be verified from public mirrors:

- [@_hummingbot](https://x.com/_hummingbot): describes Hummingbot as an open-source framework for fleets of AI trading agents and links back to the Hummingbot ecosystem.
- [@ccxt_official](https://x.com/ccxt_official): verified account for the CCXT exchange library.
- [@freqtrade](https://x.com/freqtrade): account exists but has no useful public signal in the mirror response.
- OctoBot's GitHub README links to Twitter/X, but the `OctoBot_Project` handle was not found through the mirror endpoint.

Conclusion: do not use X posts as trading alpha yet. Use X only as a discovery/social-sentiment input after adding source scoring, spam filtering, and historical validation.

## Optimization decision

The previous engine could trigger from whale flow plus weak market context. The change inspired by the reviewed projects is a `StrategyGate` inside `SignalEngine`:

- Add EMA fast/slow trend score.
- Add RSI regime score.
- Require at least 3 independent confirmations for LONG or SHORT.
- Block LONG when EMA trend is bearish or RSI is overheated.
- Block SHORT when EMA trend is bullish or RSI is washed out.
- Block noisy volatility regimes.
- Log gate status and reasons in every signal rationale.

This should reduce false positives and improve the quality of paper trades. It does not guarantee profit; it makes the system easier to evaluate honestly.

## Next high-impact upgrades

1. Historical Binance replay: store candles and whale events, then replay them deterministically.
2. Parameter sweeps: test gate vote count, RSI bounds, EMA windows, and component weights.
3. Walk-forward validation: optimize on one period, score on the next period.
4. Risk exits: stop-loss, take-profit, trailing stop, and time stop.
5. Source score for whales: exchange wallet, fund wallet, bridge, stablecoin mint/burn, and CEX hot wallet should not have the same meaning.
