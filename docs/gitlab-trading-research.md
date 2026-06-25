# GitLab Trading Bot Research

Research timestamp: 2026-06-18.

GitLab API searches used:

- `crypto trading bot`
- `backtesting trading bot`
- `freqtrade`
- `machine learning trading`
- `binance strategy trading`

The useful signal is not "copy an open-source bot and expect profit." The useful signal is which design patterns repeatedly appear in serious trading systems: backtesting, walk-forward validation, risk gates, stop-loss/take-profit, feature weighting, paper trading, and audit logs.

## GitLab projects worth learning from

| Project | What to learn | Caveat |
| --- | --- | --- |
| [SeegerSoftware / TradingBot](https://gitlab.com/seegersoftware/tradingbot) | Modular pipeline with candlestick patterns, RSI/MACD/MAs/Bollinger/Ichimoku/SuperTrend/Fibonacci, LSTM forecasting, dynamic signal weighting, backtesting, debug logs, stop-loss/take-profit/trailing stop. | Low star count; verify code quality before copying. Good architecture inspiration. |
| [frvnkenstein / buft](https://gitlab.com/frvnkenstein/buft) | 7-stage technical analysis pipeline, risk management, backtesting, Telegram/LLM integration. Useful model for turning multiple weak signals into a gated decision. | Bitget futures focused; adapt carefully for Binance spot/paper. |
| [Superalgos mirrors on GitLab](https://gitlab.com/theonlydidi/Superalgos) | Visual strategy design, data mining, backtesting, paper trading, multi-server bot deployment. Useful as a product/design reference for strategy cockpit and research workflow. | GitLab entries appear to be mirrors/forks; prefer upstream docs/code if using deeply. |
| [Dominique Roth / packys-freqtrade-strategies](https://gitlab.com/dominik_roth/packys-freqtrade-strategies) | Freqtrade-style strategy files and hyperopt mindset: strategy parameters should be testable, not hidden in code. | Old repo; use as pattern, not as a current profitable strategy. |
| [nullart / freqtrade-strategies](https://gitlab.com/nullart/freqtrade-strategies) | Collection-style strategy repository. Useful to study how entry/exit rules are separated from execution engine. | Old repo and likely outdated market assumptions. |
| [CryptoPulse Live Bot](https://gitlab.com/mzayyad/cryptopulse-live-bot) | Live Binance paper-trading demo/overlay idea. Useful for making this repo's HTML cockpit clearer. | Educational/demo oriented, not a decision-quality engine. |

## Ideas to add to Whale Signal Lab

1. Multi-signal gate before entry

Do not enter just because whale flow is strong. Require agreement from at least two of:

- whale net flow
- price momentum
- taker buy pressure
- volatility regime
- trend filter such as EMA slope

2. Stop-loss, take-profit, trailing stop

The current paper broker rebalances to target exposure. Add explicit exits:

- fixed stop loss per trade
- take profit per trade
- trailing stop after favorable move
- time stop when signal horizon expires

3. Walk-forward scorecard

A high win rate alone can hide large losses. Track:

- win rate
- profit factor
- expectancy per trade
- max drawdown
- average win / average loss
- max adverse excursion
- max favorable excursion

4. Strategy spec files

Move weights and thresholds into TOML specs so an AI assistant can propose changes but the deterministic engine validates them.

5. Backtest before live mode

Any change to signal weights should run through historical Binance candles first, then demo/paper forward testing, then testnet validation.

## Practical next step

Add `StrategyGate`:

- Calculate `trend_score` using EMA slope.
- Calculate `volatility_regime`.
- Only allow LONG/SHORT when confidence passes threshold and at least 2 independent components agree.
- Log blocked trades so we can see whether the filter improved win rate or simply reduced opportunity count.

