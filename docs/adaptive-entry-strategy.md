# Adaptive Entry Strategy

Research timestamp: 2026-06-18.

The previous smart-money cluster layer was too static: it emitted a group signal but did not learn whether that group had real edge. The new strategy treats every component as a hypothesis that must earn weight over time.

## New signal inputs

1. On-chain wallet groups

- real mode discovers active counterparties from labelled exchange wallets on BSC/EVM chains
- exchange outflow is treated as accumulation pressure
- exchange inflow is treated as distribution pressure
- clusters are scored by wallet count, USD value, sync, and historical edge

2. Binance Futures long/short ratio

The system reads:

- global long/short account ratio
- top trader long/short position ratio
- taker buy/sell volume ratio

Interpretation:

- global crowd ratio is used contrarian when it becomes one-sided
- top trader ratio is used trend-following
- taker buy/sell ratio is used as immediate flow pressure

3. Market confirmation

- momentum
- taker buy pressure
- EMA trend
- RSI regime
- volatility penalty

## Learning loop

Every signal is logged to:

```text
data/decision_log.jsonl
```

Current learner state is stored in:

```text
data/learner_state.json
```

After `outcome_horizon_ticks`, the learner compares entry price with current mark price:

- winning LONG/SHORT increases weight for components that agreed with the trade
- losing LONG/SHORT decreases weight for components that pushed the trade
- if smart-money clusters are noisy, `smart_money` edge falls automatically
- if long/short ratio helps, `derivatives` edge rises automatically

The adaptive weights feed back into `SignalEngine` on every tick.

## Practical rule

Do not enter only because one source is loud. A stronger entry requires alignment between:

- smart-money group flow
- Binance Futures long/short sentiment
- whale on-chain flow
- market trend/order flow
- risk gate

If these disagree, the system should reduce size or stay FLAT until the learner proves one component has a durable edge.

## Live data notes

Binance Futures long/short endpoints are public market-data endpoints. BSC/EVM wallet monitoring needs an explorer/indexer API key and labelled seed addresses such as Binance/OKX/Bybit hot wallets, deposit wallets, DEX routers, and bridges.

For production, replace explorer polling with an indexed event stream:

- `eth_getLogs` via BSC/archive provider
- Bitquery, Dune, Covalent, Goldsky, Subsquid, or ClickHouse/DuckDB
- persistent wallet/entity labels
- rolling post-signal edge at 5m, 15m, 1h
