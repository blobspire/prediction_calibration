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
- any limitations or unverified assumptions are recorded in `agents/TASK_LOG.md`.

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

## Phase 8 — Edge simulation

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

## Remaining Work Before Final Deployment

### Audit verdict
The Phase 0-10 codebase is a functional, tested, config-driven Kalshi v1
pipeline for contract-horizon snapshots, raw metrics, walk-forward
recalibration, simulated edge screens, manuscript outputs, robustness
diagnostics, and small-sample replication.

It is **partial for final deployment** under `agents/PROJECT_BRIEF.md`. The current
pipeline is not yet the final publishable research package because several
brief-level requirements remain intentionally partial or absent:

- final taxonomy/domain coverage;
- audited event-family clustering;
- clustered uncertainty and confidence intervals;
- hierarchical or partially pooled calibration;
- Murphy reliability/resolution/uncertainty decomposition;
- full alternate-method robustness reruns;
- executable quote/depth support;
- NO-side support from observed NO prices;
- final artifact and scientific-readiness audit.

The following phases are required before final publishable claims. They do not
invalidate Phases 0-10; they extend the implemented foundation into a final
research-grade deployment.

## Phase 11 — Final scientific audit and data semantics

### Goal
Convert the current full artifact chain into an audited, defensible research
result.

### Deliverables
- Audit `resolution_ts` / `close_time` assumptions and voided, delisted, or
  ambiguous-resolution handling.
- Produce `docs/audits/final_data_semantics.md`.
- Add artifact-level validation reports for snapshots, splits, predictions,
  edge outputs, and manuscript tables.
- Confirm no raw-data mutation, no look-ahead leakage, no accidental trade
  weighting, and no unsupported edge claims.

### Done when
- Full Phase 2-10 artifacts have a PASS/PARTIAL/FAIL audit.
- Any remaining semantic uncertainty is explicitly marked non-confirmatory.
- README, TASK_LOG, CURRENT_CAPABILITIES, and manuscript limitation tables agree
  on the audit status.

## Phase 12 — Taxonomy and event-family hardening

Status: implemented as a rule-based, audited taxonomy layer on 2026-05-07.
Remaining taxonomy-related constraints are manual review of low-confidence,
ambiguous, and unknown rows plus Phase 13 clustered inference.

### Goal
Replace placeholder taxonomy with auditable event-family, domain, and category
coverage.

### Deliverables
- Expand explicit taxonomy rules for `domain`, `category`, sports/non-sports,
  and event-family grouping.
- Add coverage reports, ambiguity flags, and unknown-rate summaries.
- Rebuild split leakage diagnostics using hardened event-family IDs.
- Add tests for mapping precedence, ambiguity handling, fallback behavior, and
  no row drops.

### Done when
- Domain/category are no longer entirely `unknown`, or the roadmap explicitly
  restricts final claims to overall/horizon/liquidity/staleness only.
- Event-family leakage checks use an audited grouping field; clustered inference
  remains Phase 13.
- Domain/sports robustness checks are computed only where taxonomy coverage is
  sufficient; otherwise they emit explicit `not_applicable` artifacts.

## Phase 13 — Confirmatory inference and uncertainty

### Goal
Attach uncertainty estimates to all raw-vs-recalibrated claims.

### Deliverables
- Cluster bootstrap by audited event family or contract family.
- Paired score-difference confidence intervals for Brier score, log loss, and
  ECE.
- Calibration intercept/slope confidence intervals.
- Multiple-comparison control across horizon, domain, liquidity, and staleness
  slices.
- Optional Diebold-Mariano-style paired loss diagnostics for forecast-score
  comparisons.

### Done when
- Manuscript score tables include confidence intervals, effect sizes, and
  effective cluster counts.
- No iid trade bootstrap is used for confirmatory market-level inference.
- Uncertainty outputs are reproducible from configs and saved result artifacts.

## Phase 14 — Expanded calibration methods and decompositions

Status: implemented as of 2026-05-07. Remaining caveat: `hierarchical_eb`
is experimental and domain-level claims remain conditional on taxonomy
confidence and ambiguity review.

### Goal
Complete the recalibration method ladder described in `agents/PROJECT_BRIEF.md`.

### Deliverables
- Bin-based reliability correction baseline.
- Murphy reliability/resolution/uncertainty decomposition where feasible.
- Hierarchical or partially pooled logistic recalibrator with horizon/domain
  effects, clearly marked experimental until taxonomy is hardened.
- Walk-forward evaluation support for the new methods.

### Done when
- New models use the same fold assignments, test rows, and metric functions as
  raw/Platt/beta/isotonic.
- Model outputs are saved with fit status, config hash, parameters, and failure
  modes.
- Hierarchical/domain models are not used for confirmatory domain claims until
  Phase 12 taxonomy coverage passes audit.

## Phase 15 — Full robustness reruns

### Goal
Move robustness beyond saved-artifact slices and small-sample variants.

### Deliverables
- Full alternate snapshot-method reruns: last trade, short-window VWAP, and
  longer-window VWAP.
- Stricter stale-price and liquidity-filter reruns.
- Equal-contract vs. equal-event-family vs. explicitly trade-weighted
  robustness.
- Sports/domain exclusions once taxonomy supports them.
- Mutually exclusive event-family exclusion, clustering, or sensitivity
  robustness.

### Done when
- Robustness outputs are separated from confirmatory outputs and summarized in
  manuscript appendix tables.
- Unavailable checks fail clearly or produce explicit `not_applicable`
  artifacts.
- Any finding that survives only optimistic assumptions is labeled fragile
  rather than tradable.

## Phase 16 — Edge executability upgrade

Status: implemented as a simulated-screen executability audit layer. The code
supports explicit quote-snapshot YES/NO asks and versioned fee/capacity/PnL
artifacts, but executable-profit claims remain unsupported without order-book
depth.

### Goal
Distinguish conservative expected-value screens from executable trading
evidence.

### Deliverables
- Versioned fee assumptions by date if historical fee schedules can be
  documented.
- Direct quote/order-book ingestion path if public data becomes available.
- Observed NO-side price support only when explicit NO prices exist.
- Capacity/liquidity constraints and cumulative simulated PnL figures labeled
  assumption-dependent.
- Stronger stale-price and liquidity gates for edge screens.

### Done when
- Edge claims remain “simulated screens” unless executable quote/depth data
  supports stronger language.
- Friction-layering and PnL outputs are reproducible from saved artifacts.
- NO-side opportunities are never synthesized from complementarity unless the
  data directly supports the price side.

## Phase 17 — Final reproducibility and deployment gate

Status: implemented as of 2026-05-08. The readiness layer records full-run
commands, config hashes, selected artifact hashes, data snapshot metadata,
scoped CI check results, and final claim boundaries. Edge/PnL outputs remain
simulated screens, and domain-level claims still require taxonomy-confidence
review.

### Goal
Make the project publication/deployment ready.

### Deliverables
- Run registry with git commit, dirty flag, config hash, data snapshot/hash,
  start/end time, and artifact paths.
- CI-ready test command set.
- Frozen final configs for the paper run.
- One documented full-run command and one small-sample replication command.
- Final `docs/final_readiness_audit.md`.

### Done when
- `uv run ruff check .`, `uv run pytest`, and final artifact audits pass.
- README, TASK_LOG, CURRENT_CAPABILITIES, ROADMAP, and paper outputs agree on
  what is final vs. exploratory.
- Every new confirmatory artifact records config hash, source artifact paths,
  run label, and limitations.
- Final claims remain equal-contract or equal-event-family by default;
  trade-weighted outputs remain explicitly labeled robustness checks.
- No remaining blocker exists for the stated publishable claims.
