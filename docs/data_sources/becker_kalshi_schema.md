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

## Methodological Notes

- `data/raw/` is immutable. Any cleaning, normalization, or schema mapping must write to `data/interim/` or later-stage directories.
- Timestamp fields must include explicit time zones before entering confirmatory analysis.
- The current schema utilities report missing, matched, and extra/unmapped columns so Becker-specific mappings can be reviewed before transformation code is written.
- Becker's Kalshi files are Parquet. Do not copy or rewrite them during schema inspection.
- The current market schema uses `close_time` as the provisional resolution timestamp candidate. Later cleaning must verify whether this is the correct outcome-knowledge timestamp for each contract family.
- `_fetched_at` is stored as `timestamp[ns]` without a timezone in the inspected Parquet schema. It should be treated as source-fetch metadata, not a forecast timestamp, unless later documentation justifies a timezone interpretation.
