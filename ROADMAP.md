# ROADMAP.md

This roadmap defines the implementation phases for the prediction-market calibration research package. It is intended to be read by both humans and Codex.

## Project objective

Build a reproducible Python research package for market-weighted, horizon-indexed, walk-forward recalibration of Kalshi prediction-market probabilities, followed by conservative friction-aware edge simulation.

## Global completion rules

A phase is complete only when:

- requested code and scripts exist;
- relevant tests pass;
- assumptions are documented in configs or docs;
- outputs are reproducible from scripts/configs;
- no files under `data/raw/` are modified;
- any limitations or unverified assumptions are recorded in `TASK_LOG.md`.

## Phase 0 — Repository bootstrap

### Goal
Create the initial research-package structure and project guidance files.

### Deliverables
- `README.md`
- `pyproject.toml`
- `src/predmkt/` package scaffold
- `configs/`
- `data/raw/`, `data/interim/`, `data/processed/`, `data/artifacts/`
- `scripts/`
- `tests/`
- `notebooks/README.md`
- `docs/`
- basic smoke test that imports `predmkt`

### Done when
- `pytest` passes.
- The package imports.
- The README explains installation and first commands.
- `data/raw/` is documented as immutable.

## Phase 1 — Inspect source data and define schemas

### Goal
Understand the Jon Becker repository / data layout and define explicit schemas for the minimum Kalshi tables needed.

### Deliverables
- Data source inspection notes in `docs/data_sources/becker_kalshi_schema.md`.
- Schema definitions under `src/predmkt/io/` or `src/predmkt/schema/`.
- Small data manifest utility.
- Tests for required columns and timestamp parsing.

### Done when
- A script can inspect local raw data paths without modifying them.
- Missing/extra columns are reported clearly.
- Timestamp fields are parsed consistently.
- Raw data file hashes/manifests can be generated.

## Phase 2 — Raw-to-cleaned Kalshi data pipeline

### Goal
Build a minimal ingestion and cleaning path from immutable raw data to normalized interim tables.

### Deliverables
- `src/predmkt/io/` readers.
- `src/predmkt/cleaning/` timestamp, outcome, and contract filters.
- `scripts/build_interim_kalshi.py`.
- Cleaned output under `data/interim/`.
- Tests for cleaning invariants.

### Done when
- Raw files remain unchanged.
- Cleaned contracts/trades/price observations are written to `data/interim/`.
- Resolved binary contracts can be identified.
- Voided/delisted/ambiguous rows are excluded or quarantined.
- Exclusion criteria are logged.

### Scientific invariants
- No future information may be used in pre-resolution feature construction.
- Resolution timestamps must be explicit and normalized.
- Exclusion criteria must be reproducible.

## Phase 3 — Contract-horizon snapshot panel

### Goal
Construct the core unit of analysis: one representative price per contract × horizon bucket.

### Deliverables
- `src/predmkt/sampling/` snapshot builder.
- Configurable horizon grid.
- Configurable tolerance/staleness windows.
- VWAP / last-trade snapshot methods.
- `scripts/build_snapshot_panel.py`.
- Output under `data/processed/contract_horizon_panel.*`.
- No-look-ahead tests.

### Done when
- Each contract contributes at most one row per horizon bucket.
- Every row has `forecast_ts < resolution_ts`.
- Snapshot price uses only observations at or before `forecast_ts`.
- Staleness is recorded.
- Tests fail if future observations leak into snapshots.

## Phase 4 — Baseline forecast metrics

### Goal
Evaluate raw Kalshi prices as probability forecasts.

### Deliverables
- `src/predmkt/metrics/` with Brier, log loss, ECE, calibration intercept/slope, reliability binning.
- Metric tests using synthetic data.
- `scripts/evaluate_raw.py`.
- Baseline tables under `data/artifacts/` or `reports/`.

### Done when
- Raw prices can be scored by horizon and domain.
- Metrics are tested against known examples.
- Probability clipping for log loss is documented.
- Primary aggregation is equal-contract or equal-event-family, not trade-weighted.

## Phase 5 — Walk-forward splitter and leakage checks

### Goal
Implement strict time-ordered expanding-window or rolling-window splits.

### Deliverables
- `src/predmkt/validation/` splitters.
- Configurable train/validation/test windows.
- Event-family leakage checks.
- Tests with synthetic event families.

### Done when
- Splits are based on forecast timestamp, not random row split.
- Hyperparameter selection can use only past data.
- Same event-family leakage at a forecast timestamp is detected.
- Tests prove train timestamps precede test timestamps.

## Phase 6 — Recalibrator registry and simple baselines

### Goal
Add raw baseline, logistic/Platt, beta calibration, and isotonic recalibration under a common interface.

### Deliverables
- `src/predmkt/calibration/base.py`.
- `src/predmkt/calibration/logistic.py`.
- `src/predmkt/calibration/isotonic.py`.
- `src/predmkt/calibration/beta.py`.
- `src/predmkt/calibration/registry.py`.
- Tests for fit/predict shape, probability bounds, and monotonicity where applicable.

### Done when
- Each calibrator exposes the same `fit` / `predict_proba` interface.
- Calibrators can be trained only on past walk-forward folds.
- Predictions are bounded away from 0/1 according to config.

## Phase 7 — Walk-forward model evaluation

### Goal
Run raw vs. recalibrated forecast comparisons out of sample.

### Deliverables
- `scripts/fit_walkforward.py`.
- Fold-level result objects.
- Aggregate score tables.
- Cluster/bootstrap utilities if feasible in this phase.
- Basic reliability plots.

### Done when
- Raw and recalibrated models are evaluated on identical test folds.
- Results are saved with config hash and git commit if available.
- Average and fold-level metrics are reported.
- No model sees future labels or future prices.

## Phase 8 — Edge simulation MVP

### Goal
Convert out-of-sample calibrated probabilities into conservative expected-value screens.

### Deliverables
- `src/predmkt/edge/fees.py`.
- `src/predmkt/edge/slippage.py`.
- `src/predmkt/edge/simulator.py`.
- `scripts/run_edge_sim.py`.
- Tests for fee subtraction, thresholding, no negative-cost bugs, and capital-lockup assumptions.

### Done when
- Taker-only fee-aware simulation works.
- Fee-only, fee+spread, and fee+spread+slippage tiers can be compared.
- Edge claims are clearly labeled simulated and assumption-dependent.

## Phase 9 — Publication figures and tables

### Goal
Produce manuscript-ready outputs programmatically from saved results.

### Deliverables
- `src/predmkt/plots/`.
- `src/predmkt/reports/`.
- `scripts/make_figures.py`.
- `scripts/make_tables.py`.
- Figure/table configs.

### Done when
- Figures and tables are generated from saved result artifacts, not manual notebook state.
- At least reliability diagrams, calibration-slope heatmaps, score-comparison tables, and edge-friction sensitivity plots can be produced.

## Phase 10 — Robustness and paper replication command

### Goal
Add robustness checks and a single reproducible command path for the paper outputs.

### Deliverables
- Robustness configs.
- End-to-end smoke pipeline on small sample data.
- Paper replication script or Makefile target.
- Documentation of known limitations.

### Done when
- A documented command can reproduce the main small-sample pipeline.
- Robustness checks compare snapshot methods, liquidity filters, domain exclusions, and friction assumptions.
- Limitations around data availability, quote depth, and executability are documented.
