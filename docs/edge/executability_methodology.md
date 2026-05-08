# Phase 16 Edge Executability Methodology

Phase 16 distinguishes simulated expected-value screens from executable trading
evidence. It does not turn the current outputs into realized trading profits.

## Quote Snapshot Source

`scripts/build_quote_observations.py` reads the immutable Becker/Kalshi raw
market snapshots under `data/raw/becker_prediction_market_analysis/data/kalshi/markets`.
The canonical quote table preserves explicit `yes_bid`, `yes_ask`, `no_bid`,
and `no_ask` prices and treats `_fetched_at` as a UTC quote-snapshot timestamp.

The output is written to `data/interim/kalshi/quote_observations.parquet`.
Rows with invalid prices, missing timestamps, or bid/ask inversions are excluded
with reason counts. The builder does not modify `data/raw/`.

## Entry-Price Modes

The edge simulator supports two entry modes:

- `transaction_proxy`: the existing snapshot probability is used as the entry
  price proxy.
- `quote_snapshot_proxy`: the nearest quote at or before `forecast_ts` is used.
  YES buys use explicit `yes_ask`; NO buys use explicit `no_ask`.

NO-side prices are never synthesized from `1 - YES price`. A NO candidate can
exist only when an explicit observed NO ask is available. The NO model
probability may be `1 - predicted_yes_probability`, but the price side remains
observed.

## Fees, Capacity, And PnL

Fees are configured as versioned assumptions. The default fee schedule remains a
Kalshi-style proxy, not a historical billing audit, unless a future config entry
documents a source for a specific historical fee regime.

Capacity defaults to a fixed configured contract count because the public
Becker/Kalshi market snapshots do not include order-book size or depth. The
`simulated_pnl.parquet` artifact is therefore assumption-dependent and should be
read as a reproducible sensitivity screen, not executable trading evidence.

## Limitations

- Quote snapshots are public market snapshots, not guaranteed fills.
- No order-book depth or queue position is available.
- Spread/slippage costs remain conservative haircuts.
- PnL is simulated from saved forecasts and resolved outcomes.
- Stronger executable claims require timestamped quote depth, documented fees,
  and capacity constraints beyond the current public data.
