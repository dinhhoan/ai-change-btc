# Execution Cost Guard

The dashboard now supports runtime paper-trading settings:

- starting cash
- risk per trade
- max notional per trade
- exchange fee in bps
- slippage in bps
- gas/network cost in USD
- minimum expected edge divided by total cost

Before every entry, the paper broker estimates:

```text
total_cost = exchange_fee + slippage_cost + gas_fee_usd
expected_edge = abs(expected_price - entry_price) * quantity
```

An entry is skipped when:

```text
expected_edge < total_cost * min_edge_cost_multiple
```

Exit orders bypass this guard so the system can always flatten risk. Every review is exposed through the API as `trade_reviews`; rejected entries are exposed as `skipped_trades`.

This is a paper-trading approximation. Real CEX orders have no on-chain gas fee, while DEX/on-chain execution needs live gas, route, MEV, and approval-cost estimates.
