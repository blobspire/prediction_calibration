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

The current repository supports raw schema inspection, Kalshi interim cleaning,
contract-horizon snapshot construction, taxonomy enrichment, feature-panel
construction, raw baseline forecast metrics, and strict walk-forward split
construction. The codebase also includes reusable simple recalibrators.
Walk-forward raw-vs-recalibrated model evaluation is available for simple
calibrators. Edge simulation will be added in a later phase.

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
and a horizon-specific snapshot policy. The current policy uses last trade as
the primary snapshot, retains horizon-specific VWAP fields for diagnostics, and
tightens near-close stale-price rules:

```text
30d/14d/7d: 6h VWAP window, 7d max staleness
3d:         6h VWAP window, 3d max staleness
1d:         1h VWAP window, 1d max staleness
6h:         15m VWAP window, 6h max staleness
1h:         5m VWAP window, 1h max staleness
close:      last-trade primary, 5m VWAP window, 5m max staleness
```

The script writes:

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

Evaluate raw Kalshi probabilities:

```bash
uv run python scripts/evaluate_raw.py --config configs/metrics.yaml
```

The metrics config evaluates `raw_probability` against `observed_outcome` with
equal-contract aggregation as the confirmatory default. It documents the
`0.000001` log-loss clipping epsilon, reliability-bin settings, calibration
intercept/slope fit settings, and the optional disabled trade-weighted robustness
mode. The script writes:

```text
data/artifacts/raw_baseline/metrics_overall.parquet
data/artifacts/raw_baseline/metrics_by_group.parquet
data/artifacts/raw_baseline/reliability_bins.parquet
data/artifacts/raw_baseline/calibration_fits.parquet
data/artifacts/raw_baseline/missing_feature_notes.parquet
data/artifacts/raw_baseline/summary.json
```

Phase 4 scores raw market probabilities only. It does not fit recalibrators and
does not perform walk-forward model evaluation. Domain/category grouped rows are
currently taxonomy placeholders because the public Becker/Kalshi fields still
map to `unknown` unless explicit taxonomy rules are added.

Create raw-baseline research diagnostics from the saved metric artifacts:

```bash
uv run python scripts/plot_raw_baseline.py --config configs/figures.yaml
```

The figure config reads `data/artifacts/raw_baseline/` and writes pandas /
matplotlib PNG and SVG visualizations:

```text
data/artifacts/raw_baseline/figures/raw_baseline_metric_overview.{png,svg}
data/artifacts/raw_baseline/figures/raw_baseline_horizon_metrics.{png,svg}
data/artifacts/raw_baseline/figures/raw_baseline_calibration_by_horizon.{png,svg}
data/artifacts/raw_baseline/figures/raw_baseline_reliability_overall.{png,svg}
data/artifacts/raw_baseline/figures/raw_baseline_reliability_by_horizon.{png,svg}
data/artifacts/raw_baseline/figures/raw_baseline_plot_summary.json
```

These are robust raw-baseline diagnostics, not final manuscript graphics or
recalibrated-model plots.

Audit near-close raw-baseline calibration patterns before changing methodology:

```bash
uv run python scripts/audit_raw_baseline.py --config configs/raw_baseline_audit.yaml
```

The audit writes diagnostic tables and figures under:

```text
data/artifacts/raw_baseline/audit/
data/artifacts/raw_baseline/audit/figures/
```

It checks staleness by horizon/method, snapshot-method metrics, stricter 1h/close
VWAP and max-staleness variants, complete-horizon balanced panels, YES-side
price/outcome orientation, and close timestamp semantics. These outputs are
diagnostics only; they do not revise the baseline methodology or make the raw
baseline finding final.

Create presentation-ready visuals from the current raw-baseline artifacts:

```bash
uv run python scripts/make_presentation_figures.py --config configs/presentation.yaml
```

The presentation figures are written to:

```text
data/artifacts/presentation/figures/
```

They include a pipeline flowchart, snapshot-policy heatmap, horizon sample
funnel, horizon metric triptych, reliability small multiples, close reliability
zoom, calibration bars, staleness percentiles, probability distributions,
calibration-gap heatmap, balanced-panel comparison, orientation sanity check,
close timestamp semantics, methodology-refinement comparison, and a summary
dashboard. These are slide-ready raw-baseline visuals, not final
walk-forward/recalibrated-model results.

Build strict walk-forward validation splits:

```bash
uv run python scripts/build_walkforward_splits.py --config configs/validation.yaml
```

The validation config uses monthly expanding windows split by `forecast_ts`, not
row order or resolution time. The default train window starts at the earliest
available forecast timestamp, uses a one-month validation block immediately
before each one-month test block, starts testing in `2024-01`, and excludes an
incomplete final test month. Event-family leakage checks use `event_family_id`
when present and fall back to `event_id` for raw snapshot panels.

The script writes:

```text
data/processed/walkforward_splits.parquet
data/processed/walkforward_split_integrity.parquet
data/processed/walkforward_split_summary.json
```

The current event-family identifier is still a conservative `event_id` proxy for
most rows, so leakage diagnostics are useful but not a final family taxonomy.

Use simple recalibrators from Python:

```python
from predmkt.calibration import load_models_config, make_configured_calibrators

config = load_models_config("configs/models.yaml")
calibrators = make_configured_calibrators(config)
```

`configs/models.yaml` enables `raw`, `platt`, `beta`, and `isotonic`
calibrators by default. Each exposes `fit(probabilities, outcomes)` and
`predict_proba(probabilities)`, and every prediction is clipped to the configured
epsilon, currently `0.000001`. These are reusable Phase 6 model components only:
they can be used directly by the walk-forward evaluator below.

Run walk-forward raw versus recalibrated evaluation:

```bash
uv run python scripts/fit_walkforward.py --config configs/models.yaml
```

The evaluator trains each configured calibrator on `train` + `validation` rows
from each fold, then removes any fit row whose outcome was not resolved by that
fold's test start. Raw and recalibrated models are scored on identical future
test row IDs. Event-family overlaps are reported but not filtered because the
current `event_family_id` remains a conservative proxy.

The script writes:

```text
data/artifacts/walkforward/predictions.parquet
data/artifacts/walkforward/fold_metrics.parquet
data/artifacts/walkforward/aggregate_metrics.parquet
data/artifacts/walkforward/calibrator_fits.parquet
data/artifacts/walkforward/event_family_leakage.parquet
data/artifacts/walkforward/summary.json
```

For a quick smoke run on the first fold:

```bash
uv run python scripts/fit_walkforward.py \
  --config configs/models.yaml \
  --limit-folds 1 \
  --artifact-dir data/artifacts/walkforward_smoke
```

Expected workflow once later phases exist:

```bash
uv run python scripts/run_edge_sim.py --config configs/backtest.yaml
```

Use the tests to verify the package imports and schema utilities:

```bash
uv run pytest
```

## Data Policy

`data/raw/` is immutable source data storage. Do not edit, normalize, deduplicate, or overwrite files in `data/raw/`. All transformations must write to `data/interim/`, `data/processed/`, or `data/artifacts/` and should record enough metadata to reproduce the output.

Current schema notes are in `docs/data_sources/becker_kalshi_schema.md`.
The current capability/status registry is in `docs/CURRENT_CAPABILITIES.md`.

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
