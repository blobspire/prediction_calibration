# Prediction Market Calibration

Python research package for market-weighted, horizon-indexed, walk-forward calibration analysis of public prediction-market probabilities, starting with Kalshi data.

The confirmatory unit of analysis is `contract x forecast_horizon_bucket`. The package is scaffolded to keep data ingestion, cleaning, snapshot construction, metrics, calibration, validation, edge simulation, plots, and reports separate.

## Installation

This project uses `uv` for dependency management.

```bash
uv sync
uv run pytest
```

For a local editable install without `uv`:

```bash
python -m pip install -e .
python -m pytest
```

## First Workflow Commands

The current repository supports raw schema inspection, Kalshi interim cleaning, and
contract-horizon snapshot construction. Model fitting and metric scripts will be added
in later phases.

Inspect local raw files without modifying `data/raw/`:

```bash
uv run python scripts/inspect_raw_schema.py --raw-path data/raw
```

For the Becker dataset cloned under `data/raw/becker_prediction_market_analysis`, inspect representative Parquet files rather than hashing the entire raw tree:

```bash
uv run python scripts/inspect_raw_schema.py --raw-path data/raw/becker_prediction_market_analysis/data/kalshi/markets/markets_860000_870000.parquet
uv run python scripts/inspect_raw_schema.py --raw-path data/raw/becker_prediction_market_analysis/data/kalshi/trades/trades_61810000_61820000.parquet
```

Audit the full Kalshi raw directory schemas without hashing every raw file:

```bash
uv run python scripts/audit_kalshi_raw.py --kalshi-path data/raw/becker_prediction_market_analysis/data/kalshi
```

Build cleaned interim Kalshi tables:

```bash
uv run python scripts/build_interim_kalshi.py \
  --raw-kalshi-path data/raw/becker_prediction_market_analysis/data/kalshi \
  --output-dir data/interim/kalshi
```

Build a contract-horizon snapshot panel from cleaned interim data:

```bash
uv run python scripts/build_snapshot_panel.py --config configs/sampling.yaml
```

The sampling config defines the default horizon grid
`30d,14d,7d,3d,1d,6h,1h,close`, `close = resolution_ts - 1 minute`,
the `7d` stale-price tolerance, and the `6h` VWAP window. The script writes:

```text
data/processed/contract_horizon_panel.parquet
data/processed/contract_horizon_panel_summary.json
```

Add conservative taxonomy fields to the snapshot panel:

```bash
uv run python scripts/build_taxonomy_panel.py --config configs/taxonomy.yaml
```

The taxonomy config currently uses `event_id` as the `event_family_id` proxy and
sets `domain` and `category` to `unknown` unless an explicit `event_id` rule is
added. Title-based inference is disabled. The script writes:

```text
data/processed/contract_horizon_panel_taxonomy.parquet
data/processed/contract_horizon_taxonomy_audit.parquet
data/processed/contract_horizon_taxonomy_summary.json
```

Do not report domain-level findings until taxonomy coverage has been audited.

Build the modeling feature panel:

```bash
uv run python scripts/build_feature_panel.py --config configs/features.yaml
```

The feature config defines probability clipping, the 24h momentum/volatility
windows, and the 7d liquidity window. The script uses only cleaned trade
observations with `source_ts <= forecast_ts` and writes:

```text
data/processed/modeling_panel.parquet
data/processed/modeling_panel_summary.json
```

Current domain/category values are inherited from the taxonomy panel and are
`unknown` unless explicit taxonomy rules have been added. The feature panel
includes flags for unknown taxonomy, inferred event-family IDs, missing listing
timestamps, missing momentum/volatility windows, and missing liquidity inputs.

Expected workflow once later phases exist:

```bash
uv run python scripts/fit_walkforward.py --config configs/models.yaml
uv run python scripts/run_edge_sim.py --config configs/backtest.yaml
uv run python scripts/make_figures.py --config configs/figures.yaml
```

Use the tests to verify the package imports and schema utilities:

```bash
uv run pytest
```

## Data Policy

`data/raw/` is immutable source data storage. Do not edit, normalize, deduplicate, or overwrite files in `data/raw/`. All transformations must write to `data/interim/`, `data/processed/`, or `data/artifacts/` and should record enough metadata to reproduce the output.

Current schema notes are in `docs/data_sources/becker_kalshi_schema.md`.

## Repository Layout

```text
configs/                  YAML configs for data, sampling, models, backtests, figures
data/raw/                 immutable source data; never modify in place
data/interim/             cleaned normalized tables, including Kalshi interim outputs
data/processed/           contract-horizon panels and modeling datasets
data/artifacts/           cached model outputs, metrics, run results
src/predmkt/              research package
scripts/                  command-line entrypoints
tests/                    smoke and invariant tests
notebooks/                exploratory only
docs/                     methodology and data-source notes
paper/                    manuscript figures, tables, appendix outputs, bibliography
```
