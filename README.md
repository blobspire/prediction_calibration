# Market-Weighted Recalibration in Prediction Markets

Python research package for walk-forward calibration, recalibration, and
friction-aware edge screening on public prediction-market data, starting with
Kalshi data from Jon Becker's `prediction-market-analysis` repository.

Current saved-artifact status: **READY_WITH_LIMITATIONS**. The Phase 17 run
registry is available, the final artifact audit passes, and the repository is
ready for bounded research use. Domain/category claims still require taxonomy
confidence and ambiguity review. Edge and PnL outputs are simulated expected
value screens, not executable trading profits.

## Scientific Design

- Confirmatory unit: `contract x forecast_horizon_bucket`.
- Validation: expanding walk-forward splits by `forecast_ts`, never random row
  splits.
- No-look-ahead rule: all snapshot and feature source observations must satisfy
  `source_ts <= forecast_ts < resolution_ts`.
- Primary aggregation: equal-contract, with equal-event-family reported where
  configured. Trade-weighted outputs are robustness diagnostics only.
- Horizon grid: `30d,14d,7d,3d,1d,6h,1h,15m,close`.
- Close horizon: `close = resolution_ts - 1 minute`.
- Default snapshot policy: horizon-specific last-trade primary with VWAP fields
  retained for diagnostics and robustness.

## Installation

This project uses `uv` and a checked-in lockfile.

```bash
uv sync
uv run pytest
```

Fallback editable install:

```bash
python -m pip install -e .
python -m pytest
```

## Data Setup

Raw data is expected under:

```text
data/raw/becker_prediction_market_analysis
```

Clone and download the Becker data outside the project transformation pipeline:

```bash
git clone https://github.com/Jon-Becker/prediction-market-analysis.git \
  data/raw/becker_prediction_market_analysis
git -C data/raw/becker_prediction_market_analysis checkout fc43470d1a6e443fcd0d6d070dc43f1a0033ad1b
(cd data/raw/becker_prediction_market_analysis && bash scripts/download.sh)
```

The full local clone plus downloaded data is roughly 50G. The Kalshi subset is
roughly 3.9G. After download, treat `data/raw/` as immutable: do not edit,
deduplicate, normalize, or overwrite raw files. All derived outputs must go to
`data/interim/`, `data/processed/`, `data/artifacts/`, or `paper/`.

Inspect raw schemas without modifying raw data:

```bash
uv run python scripts/audit_kalshi_raw.py \
  --kalshi-path data/raw/becker_prediction_market_analysis/data/kalshi
```

## Quick Verification

Run the documented Phase 17 check set:

```bash
uv run ruff check .
uv run pytest
uv run mypy \
  src/predmkt/edge \
  src/predmkt/io/kalshi_quotes.py \
  src/predmkt/plots/manuscript.py \
  src/predmkt/reports/manuscript.py \
  src/predmkt/reports/final_audit.py \
  src/predmkt/reports/final_readiness.py
uv run python scripts/audit_final_artifacts.py --config configs/final_audit.yaml
```

Full `uv run mypy src` is not the current CI gate because older
PyArrow/Pandas-heavy modules still need typing cleanup. The scoped mypy command
above is the Phase 17 type-check gate.

## Small-Sample Replication

Use this path for a deterministic, cheaper end-to-end replication check. It
starts from cleaned interim Kalshi tables, not raw files.

```bash
uv run python scripts/run_small_sample_pipeline.py --config configs/replication_small.yaml
```

Dry-run the stage order without producing artifacts:

```bash
uv run python scripts/run_small_sample_pipeline.py --config configs/replication_small.yaml --dry-run
```

Small-sample outputs are separated from confirmatory outputs:

```text
data/processed/replication_small/
data/artifacts/replication/small_sample/
paper/replication/small_sample/
```

Small-sample outputs are non-confirmatory and exist for reproducibility and
workflow validation.

## Full Research Replication

The full run assumes the Becker/Kalshi raw data is already present under
`data/raw/`. This command sequence is also recorded in `configs/final_run.yaml`
and `docs/final_readiness_audit.md`.

```bash
uv run python scripts/build_interim_kalshi.py --raw-kalshi-path data/raw/becker_prediction_market_analysis/data/kalshi --output-dir data/interim/kalshi
uv run python scripts/build_quote_observations.py --config configs/quotes.yaml
uv run python scripts/build_snapshot_panel.py --config configs/sampling.yaml
uv run python scripts/build_taxonomy_panel.py --config configs/taxonomy.yaml
uv run python scripts/build_feature_panel.py --config configs/features.yaml
uv run python scripts/evaluate_raw.py --config configs/metrics.yaml
uv run python scripts/plot_raw_baseline.py --config configs/figures.yaml
uv run python scripts/audit_raw_baseline.py --config configs/raw_baseline_audit.yaml
uv run python scripts/build_walkforward_splits.py --config configs/validation.yaml
uv run python scripts/fit_walkforward.py --config configs/models.yaml
uv run python scripts/run_inference.py --config configs/inference.yaml
uv run python scripts/run_edge_sim.py --config configs/backtest.yaml
uv run python scripts/evaluate_decomposition.py --config configs/decomposition.yaml
uv run python scripts/make_figures.py --config configs/reporting.yaml
uv run python scripts/make_tables.py --config configs/reporting.yaml
uv run python scripts/run_robustness.py --config configs/robustness.yaml
uv run python scripts/run_small_sample_pipeline.py --config configs/replication_small.yaml
uv run python scripts/audit_final_artifacts.py --config configs/final_audit.yaml
uv run python scripts/build_final_run_registry.py --config configs/final_run.yaml
```

The final registry writes config hashes, selected artifact hashes, raw-data
snapshot metadata, check results, git state, and reproduction commands under:

```text
data/artifacts/final_run_registry/
docs/final_readiness_audit.md
```

## Main Output Map

| Area | Outputs |
|---|---|
| Cleaned Kalshi tables | `data/interim/kalshi/contracts.parquet`, `price_observations.parquet`, `quote_observations.parquet` |
| Processed panels | `data/processed/contract_horizon_panel.parquet`, `contract_horizon_panel_taxonomy.parquet`, `modeling_panel.parquet`, `walkforward_splits.parquet` |
| Raw baseline | `data/artifacts/raw_baseline/` |
| Walk-forward evaluation | `data/artifacts/walkforward/` |
| Clustered inference | `data/artifacts/inference/` |
| Murphy decomposition | `data/artifacts/decomposition/` |
| Edge simulation | `data/artifacts/edge_sim/` |
| Robustness diagnostics | `data/artifacts/robustness/`, `paper/robustness/tables/` |
| Manuscript outputs | `paper/figures/`, `paper/tables/` |
| Final audit | `data/artifacts/final_audit/`, `docs/audits/final_data_semantics.md` |
| Final registry | `data/artifacts/final_run_registry/`, `docs/final_readiness_audit.md` |

## Models And Metrics

The default walk-forward model config enables:

```text
raw
platt
beta
isotonic
binned_reliability
hierarchical_eb
```

`hierarchical_eb` is experimental: it is a dependency-free empirical-Bayes
additive logit approximation over configured context fields, not a full Bayesian
mixed model. Raw, Platt, beta, isotonic, and binned reliability are the standard
baseline recalibrators.

Confirmatory metrics include Brier score, clipped log loss, ECE, reliability
bins, calibration intercept/slope, clustered score intervals, paired
model-vs-raw differences, Benjamini-Hochberg q-values, and Murphy-style Brier
decomposition. Murphy components are binned and retain `binning_residual` rather
than claiming an exact identity when probabilities vary within bins.

## Edge And PnL Interpretation

Edge outputs are simulated expected-value screens. They are not live trading
signals, executable-profit evidence, or recommendations.

The edge layer supports transaction-price proxy and explicit quote-snapshot
proxy modes. Quote snapshots include explicit YES/NO bid/ask fields, but Becker
public data does not include order-book depth, queue position, or executable
capacity. NO-side candidates require observed NO ask prices; the simulator does
not synthesize NO prices from `1 - YES price`.

Current simulated PnL tables can be negative. That is a valid research result
under conservative frictions and should not be tuned away.

## Claim Boundaries

Safe bounded claims:

- Contract-horizon raw and recalibrated probability evaluation.
- Equal-contract and explicitly labeled equal-event-family aggregation.
- Walk-forward recalibration comparisons on identical future test rows.
- Event-family clustered uncertainty and paired score differences.
- Murphy-style decomposition and robustness diagnostics.
- Simulated EV/PNL screens under documented assumptions.

Qualified claims:

- Domain/category findings require taxonomy confidence, ambiguity checks, and
  manual review before being treated as confirmatory.
- Event-family grouping is audited, but event-family purging remains a
  robustness sensitivity rather than the primary estimator.

Do not claim:

- Executable trading profit.
- Order-book-depth capacity.
- Live tradable edge from current artifacts.
- Frictionless YES/NO price complementarity.

## Deeper Documentation

- `docs/CURRENT_CAPABILITIES.md`: current capability and artifact registry.
- `docs/final_readiness_audit.md`: Phase 17 readiness report and command
  sequence.
- `docs/audits/final_data_semantics.md`: saved-artifact and data-semantics
  audit.
- `docs/data_sources/becker_kalshi_schema.md`: Becker/Kalshi schema and data
  notes.
- `docs/taxonomy/kalshi_taxonomy_methodology.md`: taxonomy and event-family
  mapping rules.
- `docs/inference/clustered_uncertainty.md`: clustered uncertainty methodology.
- `docs/calibration/phase14_methods.md`: expanded calibrators and Murphy
  decomposition.
- `docs/edge/executability_methodology.md`: quote-snapshot, fee, capacity, and
  simulated-PnL limitations.
- `paper/README.md`: manuscript figure/table generation notes.

## Repository Layout

```text
configs/                  YAML configs for methodology, paths, and audits
data/raw/                 immutable source data; never modify in place
data/interim/             cleaned normalized tables
data/processed/           contract-horizon panels and modeling datasets
data/artifacts/           metrics, model outputs, audits, and registries
src/predmkt/              reusable research package
scripts/                  config-driven command-line entrypoints
tests/                    schema, leakage, metric, model, edge, and audit tests
notebooks/                exploratory only
docs/                     methodology, data-source, audit, and status notes
paper/                    generated figures, tables, and appendix outputs
```
