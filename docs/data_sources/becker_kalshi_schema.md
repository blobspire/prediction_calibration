# Becker / Kalshi Raw Schema Notes

## Current Local Inspection

Becker's `prediction-market-analysis` repository has been cloned to:

```text
data/raw/becker_prediction_market_analysis
```

Repository commit:

```text
fc43470d1a6e443fcd0d6d070dc43f1a0033ad1b
```

The pre-collected dataset was downloaded with Becker's `scripts/download.sh` and extracted under:

```text
data/raw/becker_prediction_market_analysis/data
```

Local extracted size observed during setup:

- Full Becker clone plus data: about 50G.
- Kalshi subset: about 3.9G.
- Kalshi markets: 769 Parquet files.
- Kalshi trades: 7,214 Parquet files.
- Kalshi market rows: 7,682,445.
- Kalshi trade rows: 72,134,741.

All-file Parquet metadata audit:

- All 769 Kalshi market files share one schema.
- All 7,214 Kalshi trade files share one schema.
- No Kalshi market or trade Parquet schema-read errors were observed.

Representative read-only schema inspections:

- `data/raw/becker_prediction_market_analysis/data/kalshi/markets/markets_860000_870000.parquet`
  - SHA-256: `f7fab5988e70d769e96318b236c96fee382c02811d9964663d7cb40887eb918e`
  - Columns: `ticker`, `event_ticker`, `market_type`, `title`, `yes_sub_title`, `no_sub_title`, `status`, `yes_bid`, `yes_ask`, `no_bid`, `no_ask`, `last_price`, `volume`, `volume_24h`, `open_interest`, `result`, `created_time`, `open_time`, `close_time`, `_fetched_at`
  - Satisfies the canonical `contracts` schema.
- `data/raw/becker_prediction_market_analysis/data/kalshi/trades/trades_61810000_61820000.parquet`
  - SHA-256: `e79d4cb478e9abf98dbf268166fb1f0419a99395da5e55ea2304026cdf66e2be`
  - Columns: `trade_id`, `ticker`, `count`, `yes_price`, `no_price`, `taker_side`, `created_time`, `_fetched_at`
  - Satisfies the canonical `price_observations` schema.

Low-cardinality values observed in the Kalshi raw data:

- `market_type`: `binary` only.
- `status`: `finalized`, `active`, `initialized`, `closed`, `inactive`, `determined`, `disputed`.
- `result`: `yes`, `no`, and empty string.
- `taker_side`: `yes`, `no`.

## Read-Only Inspection Command

Use this command on representative raw files:

```bash
uv run python scripts/inspect_raw_schema.py --raw-path data/raw/becker_prediction_market_analysis/data/kalshi/markets/markets_860000_870000.parquet
uv run python scripts/inspect_raw_schema.py --raw-path data/raw/becker_prediction_market_analysis/data/kalshi/trades/trades_61810000_61820000.parquet
```

Use this command for a full Kalshi directory schema audit without hashing every raw file:

```bash
uv run python scripts/audit_kalshi_raw.py --kalshi-path data/raw/becker_prediction_market_analysis/data/kalshi
```

For machine-readable output:

```bash
uv run python scripts/inspect_raw_schema.py --raw-path data/raw/becker_prediction_market_analysis/data/kalshi/trades/trades_61810000_61820000.parquet --format json
```

The command only reads file metadata and columns. It does not write manifests, mutate source files, normalize data, or create derived outputs.

Supported header inspection formats are `.csv`, `.tsv`, `.json`, `.jsonl`, and `.parquet`. Other files are still hashed and listed, but column inspection reports an unsupported-extension error.

## Minimum Target Schemas

These schemas define the minimum canonical fields needed for resolved binary contract analysis. They are target requirements for ingestion, not confirmed Becker column names.

### `contracts`

Required canonical fields:

- `contract_id`: stable contract identifier.
- `event_id`: event or market-family identifier for dependence checks.
- `resolution_ts`: explicit timestamp when the outcome became knowable.
- `outcome`: resolved binary outcome.
- `status`: lifecycle status used to exclude voided, canceled, delisted, or unresolved contracts.

Optional canonical fields:

- `title`: human-readable audit label.
- `category`: domain/category for slice reporting.

### `price_observations`

Required canonical fields:

- `contract_id`: stable contract identifier linking prices to contracts.
- `source_ts`: explicit observation timestamp.
- `yes_price`: observed YES-side transaction price or probability proxy.

Optional canonical fields:

- `volume`: quantity or volume for VWAP and liquidity diagnostics.

## Interim Cleaning Outputs

The Phase 2 interim builder command:

```bash
uv run python scripts/build_interim_kalshi.py \
  --raw-kalshi-path data/raw/becker_prediction_market_analysis/data/kalshi \
  --output-dir data/interim/kalshi
```

Writes:

- `data/interim/kalshi/contracts.parquet`
- `data/interim/kalshi/price_observations.parquet`
- `data/interim/kalshi/contract_exclusion_summary.parquet`
- `data/interim/kalshi/price_observation_exclusion_summary.parquet`
- `data/interim/kalshi/summary.json`

Observed output counts from the initial full run:

- Contracts raw rows: 7,682,445.
- Cleaned resolved binary contracts: 7,314,375.
- Excluded contract rows: 368,070.
- Price observation raw rows: 72,134,741.
- Cleaned price observations: 67,724,365.
- Excluded price observations: 4,410,376.

Observed contract exclusion counts:

- `status_not_finalized`: 361,541.
- `missing_result`: 6,529.

Observed price-observation exclusion counts:

- `contract_not_resolved_binary`: 4,373,335.
- `invalid_yes_price`: 37,027.
- `invalid_no_price`: 14.

The cleaned contract output has one row per `contract_id`; the initial invariant check found zero duplicate contract IDs and zero missing `resolution_ts` values.

## Methodological Notes

- `data/raw/` is immutable. Any cleaning, normalization, or schema mapping must write to `data/interim/` or later-stage directories.
- Timestamp fields must include explicit time zones before entering confirmatory analysis.
- The current schema utilities report missing, matched, and extra/unmapped columns so Becker-specific mappings can be reviewed before transformation code is written.
- Becker's Kalshi files are Parquet. Do not copy or rewrite them during schema inspection.
- The current market schema uses `close_time` as the provisional resolution timestamp candidate. Later cleaning must verify whether this is the correct outcome-knowledge timestamp for each contract family.
- `_fetched_at` is stored as `timestamp[ns]` without a timezone in the inspected Parquet schema. It should be treated as source-fetch metadata, not a forecast timestamp, unless later documentation justifies a timezone interpretation.
- The interim cleaning pipeline writes one row per resolved binary contract to `data/interim/kalshi/contracts.parquet`.
- The interim `price_observations.parquet` remains a source-observation table, not the confirmatory analysis table. Contract-horizon sampling happens later.
- The interim builder filters price observations to contracts identified in the cleaned resolved-binary contract table. This is an inclusion filter for the resolved-contract study population, not a contract-horizon analysis row definition.

## Snapshot Panel Notes

The initial snapshot builder reads only cleaned interim data:

```bash
uv run python scripts/build_snapshot_panel.py --config configs/sampling.yaml
```

The output has at most one row per `contract_id x horizon_bucket`. It includes both last-trade and short-window VWAP fields on the same row. The primary `snapshot_price` uses VWAP when at least one trade is present in the VWAP window, otherwise it falls back to last trade.

Canonical fields for downstream metrics include `contract_id`, `event_id`, `outcome`, `observed_outcome`, `horizon_bucket`, `horizon_timedelta_seconds`, `forecast_ts`, `resolution_ts`, `snapshot_price`, `snapshot_method`, `price_timestamp`, and `staleness_seconds`. Existing source-method fields such as `last_trade_ts`, `max_source_ts`, `vwap_volume`, and `vwap_trade_count` are preserved.

Initial full horizon-grid output:

- Output path: `data/processed/contract_horizon_panel.parquet`.
- Summary path: `data/processed/contract_horizon_panel_summary.json`.
- Horizons: `30d`, `14d`, `7d`, `3d`, `1d`, `6h`, `1h`, `close`.
- `close` is operationalized as one minute before `resolution_ts` so every row still satisfies `forecast_ts < resolution_ts`.
- Maximum last-trade staleness: `7d`.
- VWAP window: `6h`.
- Rows: 1,439,680.
- Candidate rows before price/staleness filtering: 58,515,000.
- Dropped with no pre-forecast price: 57,037,707.
- Dropped as stale under the `7d` tolerance: 37,613.
- `30d` rows: 7,992.
- `14d` rows: 11,836.
- `7d` rows: 18,062.
- `3d` rows: 50,469.
- `1d` rows: 141,332.
- `6h` rows: 299,051.
- `1h` rows: 392,837.
- `close` rows: 518,101.
- Snapshot method counts: `vwap`: 888,766; `last_trade`: 550,914.
- Duplicate-key validation passed with 0 duplicate rows.
- No-look-ahead validation passed with 0 bad forecast orders, 0 future last trades, 0 future VWAP sources, and 0 future price timestamps.

No-look-ahead invariant:

- `forecast_ts = resolution_ts - horizon`.
- `forecast_ts < resolution_ts`.
- `last_trade_ts <= forecast_ts`.
- `max_source_ts <= forecast_ts` when VWAP observations exist.
- `price_timestamp <= forecast_ts`.

Current limitation:

- Domain/category and event-family taxonomy fields are not available in the cleaned interim contracts yet. The panel preserves `event_id`, but Phase 5 should add explicit event-family mapping before event-family leakage checks or clustered inference.

## Taxonomy Enrichment Notes

The taxonomy enrichment layer reads the processed snapshot panel and cleaned contract metadata:

```bash
uv run python scripts/build_taxonomy_panel.py --config configs/taxonomy.yaml
```

It writes:

- `data/processed/contract_horizon_panel_taxonomy.parquet`
- `data/processed/contract_horizon_taxonomy_audit.parquet`
- `data/processed/contract_horizon_taxonomy_summary.json`

Canonical taxonomy fields:

- `domain`
- `category`
- `event_family_id`
- `taxonomy_source`
- `taxonomy_confidence`
- `taxonomy_notes`

Conservative default rules:

- `event_family_id` defaults to `event_id`.
- If `event_id` is missing, `event_family_id` falls back to `contract_id` so every row remains usable for invariant checks.
- `domain` defaults to `unknown`.
- `category` defaults to `unknown`.
- `taxonomy_source` defaults to `event_id_proxy`.
- `taxonomy_confidence` defaults to `low`.
- Title-based inference is disabled. Titles and subtitles are preserved for later audited mapping work.
- Explicit exact-match `event_id` mapping rules in `configs/taxonomy.yaml` override defaults.

Observed initial taxonomy output:

- Input rows: 1,439,680.
- Output rows: 1,439,680.
- Dropped rows: 0.
- `taxonomy_source`: `event_id_proxy`: 1,439,680.
- `domain`: `unknown`: 1,439,680.
- `category`: `unknown`: 1,439,680.
- Unknown taxonomy rows: 1,439,680.
- Ambiguous taxonomy rows: 0.
- Missing `event_family_id` rows: 0.
- Audit groups: 1.

Current limitation:

- The current taxonomy is only a conservative event-family proxy and unknown-domain placeholder. Do not claim domain-level findings or rely on event-family clustering as final until explicit mapping coverage is audited and expanded.

## Feature Panel Notes

The modeling feature panel reads the taxonomy-enriched snapshot panel, cleaned price observations, and cleaned contracts:

```bash
uv run python scripts/build_feature_panel.py --config configs/features.yaml
```

It writes:

- `data/processed/modeling_panel.parquet`
- `data/processed/modeling_panel_summary.json`

Feature config:

- Probability clipping epsilon: `0.000001`.
- Momentum window: `24h`.
- Volatility window: `24h`.
- Liquidity window: `7d`.

Feature construction rules:

- All trade-derived features use only `source_ts <= forecast_ts`.
- `raw_probability` is the snapshot panel's `snapshot_price`.
- `clipped_probability` clips `raw_probability` to `[epsilon, 1 - epsilon]`.
- `logit_probability` is computed from `clipped_probability`.
- `horizon_name` is copied from `horizon_bucket`.
- `horizon_timedelta` is copied from `horizon_timedelta_seconds`.
- `forecast_month` is derived from `forecast_ts`.
- `listing_month` is derived from cleaned contract `open_ts` when available.
- Cumulative volume and trade count use all cleaned trades through `forecast_ts`.
- Short-run momentum is the last minus first YES trade price inside the configured momentum window.
- Short-run volatility is sample standard deviation of YES trade prices inside the configured volatility window.
- `public_liquidity_proxy` is `log(1 + cumulative_volume_to_forecast)`.

Missing or inferred feature flags:

- `raw_probability_missing`.
- `domain_missing_or_unknown`.
- `category_missing_or_unknown`.
- `event_family_id_inferred`.
- `event_family_id_missing`.
- `listing_ts_missing`.
- `momentum_missing`.
- `volatility_missing`.
- `liquidity_missing`.

Observed full feature output:

- Input rows: 1,439,680.
- Output rows: 1,439,680.
- Duplicate rows: 0.
- No-look-ahead validation passed with 0 bad forecast orders, 0 future feature sources, and 0 future price timestamps.
- `domain_missing_or_unknown`: 1,439,680.
- `category_missing_or_unknown`: 1,439,680.
- `event_family_id_inferred`: 1,439,680.
- `event_family_id_missing`: 0.
- `listing_ts_missing`: 0.
- `raw_probability_missing`: 0.
- `liquidity_missing`: 0.
- `momentum_missing`: 650,115.
- `volatility_missing`: 650,115.

Current limitations:

- Domain/category features are placeholders until explicit taxonomy rules are added.
- `event_family_id` currently uses the taxonomy layer's `event_id` proxy.
- Liquidity uses public trade volume/count only, not order-book depth or executable quote liquidity.
- Momentum and volatility use transaction prices, not quote midpoints or executable prices.
