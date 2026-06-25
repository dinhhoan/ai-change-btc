# Research Notes

Research timestamp: 2026-06-18.

This project intentionally combines on-chain flow, exchange microstructure, and paper trading instead of treating whale alerts as a standalone buy/sell signal. Whale transfers are noisy; exchange inflows can mean selling pressure, collateral movement, or custody rotation. The engine therefore scores them as one feature alongside price momentum, taker-buy pressure, and realized volatility.

## GitHub repositories reviewed

The list below came from GitHub repository search API calls on 2026-06-18.

| Repository | Why it matters | Snapshot |
| --- | --- | --- |
| [pmaji/crypto-whale-watching-app](https://github.com/pmaji/crypto-whale-watching-app) | Python Dash app focused on whale activity dashboards. Useful prior art for visualization and watchlists. | Python, MIT, 636 stars, 137 forks, updated 2026-05-26. |
| [aicoincom/coinos-skills](https://github.com/aicoincom/coinos-skills) | Newer AI-agent crypto toolkit mentioning real-time prices, funding rates, whale tracking, CCXT trading, and bot automation. | JavaScript, MIT, 45 stars, updated 2026-06-16. |
| [Co-Messi/HyperData-Terminal](https://github.com/Co-Messi/HyperData-Terminal) | TUI terminal idea combining live order flow, liquidation cascades, whale tracking, and paper trading. | Python, Apache-2.0, 8 stars, updated 2026-06-10. |
| [Aliipou/mm-live](https://github.com/Aliipou/mm-live) | Binance WebSocket, order-flow imbalance, Kalman fair value, and paper engine. Useful for market microstructure inspiration. | Python, 5 stars, updated 2026-05-18. |
| [frostyalce000/paper-trading-binance](https://github.com/frostyalce000/paper-trading-binance) | Minimal Binance Testnet paper-trading reference. | Python, 4 stars, updated 2026-06-14. |
| [darflashxd/crypto-whale-hunter](https://github.com/darflashxd/crypto-whale-hunter) | Multi-token whale tracker using Etherscan API V2. | Python, MIT, 1 star, created 2026-01-30. |

## Video reference

- [arc. X video](https://x.com/arceyul/status/2067158710019887302): metadata says it is a 31-minute guide to building a trading bot with Claude Fable 5. Full media download from `video.twimg.com` was blocked from this machine, so the project uses the available tweet metadata as inspiration rather than a frame-by-frame reconstruction. See `docs/video-inspired-roadmap.md`.

## GitLab references

See `docs/gitlab-trading-research.md` for GitLab API research on open-source trading bots, backtesting projects, Freqtrade strategy repositories, and concrete ideas to improve entry quality.

## API references

- [Binance Spot WebSocket Streams](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams): market stream base URLs, kline streams, aggregate trade streams, book ticker streams, and connection limits.
- [Binance Spot Trading Endpoints](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/trading-endpoints): `/api/v3/order` and `/api/v3/order/test`. This project only validates against `/order/test` unless you deliberately extend it.
- [Binance Spot Testnet FAQ](https://developers.binance.com/docs/binance-spot-api-docs/faqs/testnet): testnet URLs, virtual balances, and monthly testnet resets.
- [Etherscan V2 txlist](https://docs.etherscan.io/api-reference/endpoint/txlist): normal transactions by address.
- [Etherscan V2 tokentx](https://docs.etherscan.io/api-reference/endpoint/tokentx): ERC-20 token transfers by address with chain ID support.

## Design choices

- Core package has zero required dependencies, so scoring and paper trading can run in a restricted environment.
- Live market mode uses Binance public 1m klines over REST by default. WebSocket support is available through the optional `websockets` dependency.
- On-chain mode uses Etherscan V2 polling. True push-based on-chain monitoring should be added through an indexed provider such as Alchemy, QuickNode Streams, Moralis Streams, or a self-hosted node/log indexer if latency matters.
- Binance integration defaults to `POST /api/v3/order/test` on Spot Testnet, which validates signed order parameters without sending the order into the matching engine.
- Prediction is scenario scoring, not prophecy: output is direction, confidence, component scores, and a short expected price path with uncertainty bands.
