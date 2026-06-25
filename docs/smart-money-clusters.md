# Smart Money Cluster Design

Goal: detect coordinated wallet groups instead of trusting one whale wallet.

## What can be collected

Public chains such as BSC, Ethereum, Base, and Arbitrum expose on-chain transfers. CEX internal order books and user-to-user transfers inside Binance/OKX/Bybit are not public. The closest useful proxy is:

- wallets depositing assets into labelled exchange wallets
- wallets withdrawing assets from labelled exchange wallets
- wallets interacting with DEX routers, bridges, market-maker wallets, and token contracts
- groups of wallets moving the same asset in the same direction within a short time window

Etherscan API V2 supports 60+ EVM chains through the `chainid` parameter, including BNB Smart Chain. Token transfer endpoints and log endpoints can return up to 10,000 rows today, with the free-tier record limit scheduled to drop to 1,000 per request on July 1, 2026. Token holder list is a PRO endpoint.

## Current implementation

The project now has a `SmartMoneyClusterEngine`.

It tracks up to 10,000 wallets and emits a `WalletClusterSignal` when enough wallets align by:

- symbol
- direction: LONG for exchange outflow / accumulation, SHORT for exchange inflow / distribution
- time window
- behavior cluster id
- total USD threshold

The signal becomes part of `SignalEngine` as `smart_money_score`, so it affects trade decisions alongside whale flow, order flow, EMA trend, RSI, momentum, and volatility.

## Demo mode

Demo mode creates 10,000 deterministic wallets and injects coordinated waves. This is not fake alpha; it is a local simulation so the UI and scoring behavior can be tested before plugging in paid or API-key data.

## Live BSC path

Set:

```bash
export ETHERSCAN_API_KEY="..."
```

Then add verified exchange hot/deposit wallets:

```toml
[smart_money]
enabled = true
chain = "bsc"
chainid = "56"

[exchange_addresses]
binance_hot_bsc_1 = "0x..."
```

The collector queries token transfers for those exchange wallets, extracts counterparties, ranks active wallets, clusters synchronized flows, and returns the strongest groups.

## Next upgrade

For a true 10,000-wallet production system, use a database-backed indexer:

- BSC node or archive provider for `eth_getLogs`
- Dune, Bitquery, Covalent, Goldsky, Subsquid, or self-hosted ClickHouse/DuckDB pipeline
- persisted wallet profiles with rolling win rate after 5m/15m/1h
- labelled entities for exchanges, bridges, funds, market makers, CEX hot wallets, and DEX routers
