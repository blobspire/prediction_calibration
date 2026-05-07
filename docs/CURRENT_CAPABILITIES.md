# Current Capabilities

Last updated: 2026-05-07.

This is the project capability registry. It tracks what the codebase can currently do,
what artifacts exist locally, what is only partial or placeholder, and what must be
built before the project can make research-grade claims.

Status labels:

- `complete`: implemented, config-driven, tested against relevant invariants, documented, and usable at full configured scale.
- `partial`: useful implementation exists, but important research-grade requirements or coverage are missing.
- `prototype`: smoke or MVP implementation exists and should not be treated as final.
- `blocked`: cannot proceed without an upstream decision, data, or repair.
- `not implemented`: no substantive implementation yet.

## Non-Negotiable Scientific State

- Primary unit of analysis: `contract x forecast_horizon_bucket`.
- Raw data policy: `data/raw/` is immutable and must not be edited.
- Confirmatory evaluation must be split by `forecast_ts`, not row order or resolution timestamp.
- Snapshot and feature construction must use only source observations satisfying `source_ts <= forecast_ts < resolution_ts`.
- Primary aggregation must not become trade-weighted unless explicitly configured as a robustness check.
- Domain-level findings are not allowed yet because domain/category taxonomy coverage is currently all `unknown`.
- Event-family leakage checks are not final yet because `event_family_id` is currently a conservative `event_id` proxy.

## Phase Gate Summary

| Area | Status | Current State | Main Remaining Gap |
|---|---|---|---|
| Phase 0 repository bootstrap | complete | Package scaffold, configs/data/docs/scripts/tests layout, import smoke test, README/data policy. | None material. |
| Phase 1 raw schema inspection | complete | Read-only raw inspection, Parquet schema audit, schema validators, timestamp parsing tests. | Raw hash manifests are available for representative files, not all 50G by default. |
| Becker raw data setup | complete | Becker repo/data present under `data/raw/becker_prediction_market_analysis`; raw repo clean. | Raw data is local and ignored; another machine must clone/download separately. |
| Phase 2 raw-to-interim Kalshi cleaning | partial | Resolved binary contracts and cleaned price observations are built and logged. | `close_time` remains provisional resolution timestamp; no richer void/delist semantic review by family. |
| Phase 3 contract-horizon snapshots | complete | Config-driven full horizon grid, horizon-specific last-trade/VWAP policy, no-look-ahead validation, canonical panel schema. | Snapshot uses trade proxy only; no historical quotes/order book. |
| Conservative taxonomy layer | partial | Adds `domain`, `category`, `event_family_id`, taxonomy audit, and explicit rule config. | All domain/category values are `unknown`; event family is `event_id` proxy. |
| Forecast feature panel | partial | Config-driven modeling panel with probabilities, horizon fields, taxonomy fields, staleness, cumulative activity, momentum, volatility, liquidity proxy. | Domain/category placeholders; liquidity is public trade proxy only; momentum/volatility use transaction prices. |
| Phase 4 baseline forecast metrics | complete | Config-driven raw baseline metrics, equal-contract primary aggregation, reliability bins, ECE, calibration slope/intercept, grouped artifacts, and known-value tests. | Domain/category grouped outputs remain taxonomy placeholders until coverage improves. |
| Phase 5 walk-forward validation | complete | Config-driven monthly expanding splits by `forecast_ts`, one-month validation/test windows, split-integrity artifacts, and strict event-family overlap diagnostics. | Later model evaluation must decide whether to filter or group around flagged event-family overlaps; event families remain conservative proxies. |
| Phase 6 recalibrators | complete | Common fit/predict interface, raw/Platt/beta/isotonic calibrators, model config, registry, bounded predictions, and synthetic tests. | Full walk-forward model evaluation is Phase 7. |
| Phase 7 walk-forward evaluation | complete | Config-driven raw-vs-recalibrated evaluation with identical test folds, label-available fit rows, fold/aggregate metrics, fit artifacts, config hash, git commit, and leakage diagnostics. | Clustered inference, hierarchical models, and full-scale audited edge interpretation remain later work. |
| Phase 8 edge simulation | complete | Config-driven taker-only YES-side EV screens with fee-only, fee+spread, and fee+spread+slippage tiers, capital lockup, exclusions, and full artifacts. | Full trading claims remain out of scope; spread/slippage are proxy haircuts because executable quote/depth data is unavailable. |
| Phase 9 plots/reports | complete | Config-driven manuscript figures and tables are generated from saved raw/walk-forward/edge artifacts under `paper/`. | Manuscript claims still need clustered uncertainty and Phase 12-17 final gates. |
| Phase 10 replication/robustness | complete | Config-driven robustness diagnostics and deterministic small-sample replication command path are implemented with separated non-confirmatory outputs. | Robustness outputs remain sensitivity diagnostics; domain exclusions are not substantive while taxonomy is all `unknown`. |
| Phase 11 final scientific audit | complete | Config-driven saved-artifact audit writes inventory, checks, phase status, summary JSON, and `docs/audits/final_data_semantics.md`; current full audit is PARTIAL with 0 hard failures. | Phase 12-17 blockers remain: taxonomy hardening, clustered uncertainty, expanded robustness, and edge executability. |
| Final deployment readiness | partial | Phase 0-11 implementation is a working v1 research pipeline with full local artifacts, final audit outputs, and tests passing. | Phases 12-17 in `ROADMAP.md` remain required before final publishable claims. |

## Current Commands

Read-only raw inspection:

```bash
uv run python scripts/inspect_raw_schema.py --raw-path data/raw
uv run python scripts/audit_kalshi_raw.py --kalshi-path data/raw/becker_prediction_market_analysis/data/kalshi
```

Build cleaned interim Kalshi tables:

```bash
uv run python scripts/build_interim_kalshi.py \
  --raw-kalshi-path data/raw/becker_prediction_market_analysis/data/kalshi \
  --output-dir data/interim/kalshi
```

Build processed snapshot, taxonomy, and feature panels:

```bash
uv run python scripts/build_snapshot_panel.py --config configs/sampling.yaml
uv run python scripts/build_taxonomy_panel.py --config configs/taxonomy.yaml
uv run python scripts/build_feature_panel.py --config configs/features.yaml
uv run python scripts/evaluate_raw.py --config configs/metrics.yaml
uv run python scripts/plot_raw_baseline.py --config configs/figures.yaml
uv run python scripts/audit_raw_baseline.py --config configs/raw_baseline_audit.yaml
uv run python scripts/make_presentation_figures.py --config configs/presentation.yaml
uv run python scripts/build_walkforward_splits.py --config configs/validation.yaml
uv run python scripts/fit_walkforward.py --config configs/models.yaml
uv run python scripts/run_edge_sim.py --config configs/backtest.yaml
uv run python scripts/make_figures.py --config configs/reporting.yaml
uv run python scripts/make_tables.py --config configs/reporting.yaml
uv run python scripts/run_robustness.py --config configs/robustness.yaml
uv run python scripts/run_small_sample_pipeline.py --config configs/replication_small.yaml
uv run python scripts/audit_final_artifacts.py --config configs/final_audit.yaml
```

Reusable recalibrators are available through the Python registry:

```python
from predmkt.calibration import load_models_config, make_configured_calibrators

config = load_models_config("configs/models.yaml")
calibrators = make_configured_calibrators(config)
```

Run tests:

```bash
uv run pytest
```

Latest local verification used `uv run pytest` and passed `93 passed`.
`uv run ruff check .` also passes. Targeted `mypy` checks pass for
`src/predmkt/edge`, `src/predmkt/plots/manuscript.py`, and
`src/predmkt/reports/manuscript.py`. Full walk-forward, edge-simulation,
manuscript, robustness, small-sample replication, and final-audit artifacts now
exist under their configured output roots.

## Config Registry

| Config | Status | Purpose |
|---|---|---|
| `configs/sampling.yaml` | complete | Snapshot inputs/outputs, horizon grid, `close = resolution_ts - 1 minute`, horizon-specific staleness/VWAP windows, and snapshot method preference. |
| `configs/taxonomy.yaml` | partial | Conservative taxonomy enrichment, explicit event-id mapping rules, default unknown domain/category, event-id event-family proxy. |
| `configs/features.yaml` | partial | Modeling feature inputs/outputs, probability epsilon, 24h momentum/volatility windows, 7d liquidity window, missing-feature policy. |
| `configs/metrics.yaml` | complete | Raw baseline metric input/output paths, log-loss clipping epsilon, reliability bins, calibration fit settings, groupings, and equal-contract primary aggregation. |
| `configs/figures.yaml` | partial | Raw-baseline diagnostic figure inputs, output directory, horizon order, aggregation mode, PNG/SVG formats, and DPI. |
| `configs/raw_baseline_audit.yaml` | partial | Diagnostics for staleness, snapshot-method sensitivity, stricter close/1h variants, balanced panels, orientation, and close timestamp semantics. |
| `configs/presentation.yaml` | partial | Slide-ready raw-baseline figure inputs, presentation output directory, horizon order, formats, DPI, and recorded pre-refinement comparison values. |
| `configs/models.yaml` | complete | Recalibrator input columns, enabled raw/Platt/beta/isotonic model names, prediction clipping epsilon, fit controls, metric settings, fit-label policy, and walk-forward artifact directory. |
| `configs/validation.yaml` | complete | Forecast-time expanding walk-forward split inputs/outputs, monthly window settings, event-family fallback policy, and strict overlap leakage diagnostics. |
| `configs/backtest.yaml` | complete | Conservative YES-side edge-screen inputs, fee proxy, spread/slippage haircuts, capital-lockup charge, optional liquidity/staleness filters, and artifact directory. |
| `configs/reporting.yaml` | complete | Manuscript figure/table input artifact dirs, `paper/` output dirs, model/horizon order, figure/table formats, metric scope, and explicit full-vs-smoke run label. |
| `configs/robustness.yaml` | complete | Non-confirmatory robustness inputs/outputs, snapshot-method slices, liquidity filters, explicit unavailable-domain handling, friction scenarios, and small snapshot variants. |
| `configs/replication_small.yaml` | complete | Deterministic small-sample replication paths, stage configs, limits, run label, and separate processed/artifact/paper output roots. |
| `configs/final_audit.yaml` | complete | Phase 11 saved-artifact and data-semantics audit inputs, expected horizons/models, full-run labels, hard-fail/partial severity rules, known partial limitations, and audit output paths. |

## Local Data Artifacts

Raw Becker/Kalshi source:

- Path: `data/raw/becker_prediction_market_analysis`
- Becker commit: `fc43470d1a6e443fcd0d6d070dc43f1a0033ad1b`
- Full clone plus data: about 50G.
- Kalshi subset: about 3.9G.
- Kalshi markets: 769 Parquet files, 7,682,445 rows.
- Kalshi trades: 7,214 Parquet files, 72,134,741 rows.

Interim outputs:

- `data/interim/kalshi/contracts.parquet`: 7,314,375 cleaned resolved binary contracts.
- `data/interim/kalshi/price_observations.parquet`: 67,724,365 cleaned price observations.
- Contract exclusions: 368,070 rows.
- Price-observation exclusions: 4,410,376 rows.

Processed outputs:

- `data/processed/contract_horizon_panel.parquet`: 695,940 rows.
- `data/processed/contract_horizon_panel_summary.json`
- `data/processed/contract_horizon_panel_taxonomy.parquet`: 695,940 rows.
- `data/processed/contract_horizon_taxonomy_audit.parquet`
- `data/processed/contract_horizon_taxonomy_summary.json`
- `data/processed/modeling_panel.parquet`: 695,940 rows.
- `data/processed/modeling_panel_summary.json`
- `data/artifacts/raw_baseline/metrics_overall.parquet`
- `data/artifacts/raw_baseline/metrics_by_group.parquet`
- `data/artifacts/raw_baseline/reliability_bins.parquet`
- `data/artifacts/raw_baseline/calibration_fits.parquet`
- `data/artifacts/raw_baseline/missing_feature_notes.parquet`
- `data/artifacts/raw_baseline/summary.json`
- `data/artifacts/raw_baseline/figures/raw_baseline_metric_overview.{png,svg}`
- `data/artifacts/raw_baseline/figures/raw_baseline_horizon_metrics.{png,svg}`
- `data/artifacts/raw_baseline/figures/raw_baseline_calibration_by_horizon.{png,svg}`
- `data/artifacts/raw_baseline/figures/raw_baseline_reliability_overall.{png,svg}`
- `data/artifacts/raw_baseline/figures/raw_baseline_reliability_by_horizon.{png,svg}`
- `data/artifacts/raw_baseline/figures/raw_baseline_plot_summary.json`
- `data/artifacts/raw_baseline/audit/audit_summary.json`
- `data/artifacts/raw_baseline/audit/staleness_by_horizon_method.parquet`
- `data/artifacts/raw_baseline/audit/snapshot_method_counts.parquet`
- `data/artifacts/raw_baseline/audit/snapshot_method_metrics.parquet`
- `data/artifacts/raw_baseline/audit/strict_close_1h_variant_metrics.parquet`
- `data/artifacts/raw_baseline/audit/balanced_horizon_metrics.parquet`
- `data/artifacts/raw_baseline/audit/orientation_sanity_by_outcome.parquet`
- `data/artifacts/raw_baseline/audit/close_timestamp_semantics.parquet`
- `data/artifacts/raw_baseline/audit/close_stale_flags.parquet`
- `data/artifacts/raw_baseline/audit/figures/*.png`
- `data/artifacts/raw_baseline/audit/figures/*.svg`
- `data/artifacts/presentation/figures/presentation_*.png`
- `data/artifacts/presentation/figures/presentation_*.svg`
- `data/artifacts/presentation/figures/presentation_figure_summary.json`
- `data/processed/walkforward_splits.parquet`: 4,094,883 fold/split assignment rows from 22 monthly expanding folds.
- `data/processed/walkforward_split_integrity.parquet`
- `data/processed/walkforward_split_summary.json`
- `data/artifacts/walkforward_smoke/predictions.parquet`: one-fold smoke output, not confirmatory.
- `data/artifacts/walkforward_smoke/fold_metrics.parquet`
- `data/artifacts/walkforward_smoke/aggregate_metrics.parquet`
- `data/artifacts/walkforward_smoke/calibrator_fits.parquet`
- `data/artifacts/walkforward_smoke/event_family_leakage.parquet`
- `data/artifacts/walkforward_smoke/summary.json`
- `data/artifacts/walkforward/predictions.parquet`: full 22-fold walk-forward output with 1,970,448 model prediction rows.
- `data/artifacts/walkforward/fold_metrics.parquet`: 880 fold-level metric rows.
- `data/artifacts/walkforward/aggregate_metrics.parquet`: 80 pooled and fold-macro metric rows.
- `data/artifacts/walkforward/calibrator_fits.parquet`
- `data/artifacts/walkforward/event_family_leakage.parquet`: 318 reported fit/test event-family overlaps.
- `data/artifacts/walkforward/summary.json`
- `data/artifacts/edge_sim_smoke/edge_candidates.parquet`: one-fold smoke edge-screen output, not confirmatory.
- `data/artifacts/edge_sim_smoke/edge_summary_by_tier.parquet`
- `data/artifacts/edge_sim_smoke/edge_summary_by_model_tier.parquet`
- `data/artifacts/edge_sim_smoke/excluded_rows.parquet`
- `data/artifacts/edge_sim_smoke/summary.json`
- `data/artifacts/edge_sim/edge_candidates.parquet`: full edge-screen output with 5,911,344 candidate rows.
- `data/artifacts/edge_sim/edge_summary_by_tier.parquet`
- `data/artifacts/edge_sim/edge_summary_by_model_tier.parquet`
- `data/artifacts/edge_sim/excluded_rows.parquet`
- `data/artifacts/edge_sim/summary.json`
- `paper/figures/figure_manifest.json`
- `paper/figures/manuscript_*.{png,svg,pdf}`
- `paper/tables/table_manifest.json`
- `paper/tables/*.csv`
- `paper/tables/*.md`
- `paper/tables/*.tex`
- `data/artifacts/robustness/summary.json`: full robustness run over 1,970,448 saved prediction rows.
- `data/artifacts/robustness/snapshot_method_slices.parquet`
- `data/artifacts/robustness/liquidity_filter_sensitivity.parquet`
- `data/artifacts/robustness/domain_exclusion_status.parquet`: records domain/category exclusions as unavailable while taxonomy is all `unknown`.
- `data/artifacts/robustness/friction_assumption_sensitivity.parquet`
- `data/artifacts/robustness/snapshot_variant_runs.parquet`: two small-sample snapshot variant summaries.
- `paper/robustness/tables/*.csv`
- `paper/robustness/tables/*.md`
- `data/processed/replication_small/modeling_panel.parquet`: deterministic small-sample replication panel with 8,460 rows.
- `data/artifacts/replication/small_sample/replication_manifest.json`: all 9 stages completed.
- `data/artifacts/replication/small_sample/walkforward/predictions.parquet`: 1,636 small-sample walk-forward predictions over 2 evaluated folds.
- `data/artifacts/replication/small_sample/edge_sim/edge_candidates.parquet`: 4,908 small-sample simulated edge candidate rows.
- `paper/replication/small_sample/figures/figure_manifest.json`
- `paper/replication/small_sample/figures/manuscript_*.{png,svg,pdf}`
- `paper/replication/small_sample/tables/table_manifest.json`
- `paper/replication/small_sample/tables/*.{csv,md,tex}`
- `data/artifacts/final_audit/artifact_inventory.parquet`
- `data/artifacts/final_audit/audit_checks.parquet`: current full audit has
  61 checks, 56 PASS, 5 PARTIAL, and 0 FAIL.
- `data/artifacts/final_audit/phase_status.parquet`
- `data/artifacts/final_audit/summary.json`: current overall status is
  `PARTIAL`.
- `docs/audits/final_data_semantics.md`

Smoke outputs also exist under `data/processed/*_smoke*`; they are verification artifacts only and not confirmatory outputs.

## Implemented Modules

### `src/predmkt/io/`

Status: complete for Phase 1 inspection and Kalshi raw readers.

Capabilities:

- Inspect raw file columns for CSV/TSV/JSON/JSONL/Parquet.
- Build file manifests for inspected files.
- Validate raw columns against minimum Kalshi contract and price-observation schemas.
- Audit all Kalshi market/trade Parquet schemas without mutating raw data.
- Read Becker Kalshi raw market/trade directories for downstream cleaning.

Limitations:

- Full raw tree hashing is intentionally not the default for the 50G local data.

### `src/predmkt/cleaning/`

Status: partial.

Capabilities:

- Identify resolved binary contracts using `market_type == binary`, `status == finalized`, non-null `close_time`, and `result in {yes,no}`.
- Normalize contracts to one row per `contract_id`.
- Normalize cleaned trade observations to `source_ts`, YES/NO prices, volume, taker side, and source fetch timestamp.
- Filter price observations to resolved binary contract IDs.
- Write exclusion summaries and build summary JSON.

Limitations:

- Uses `close_time` as provisional `resolution_ts`; this still needs family-level verification.
- Excludes ambiguous/unresolved rows by rule, but does not yet produce rich quarantine tables with example rows.
- Full price build can be slow because batches are checked against the resolved contract ID set.

### `src/predmkt/sampling/`

Status: complete for Phase 3 snapshot construction.

Capabilities:

- Config-driven horizon grid: `30d,14d,7d,3d,1d,6h,1h,15m,close`.
- Defines `close` as one minute before `resolution_ts`.
- Builds one row per `contract_id x horizon_bucket`.
- Uses only observations with `source_ts <= forecast_ts`.
- Supports horizon-specific last-trade and short-window VWAP policies.
- Current configured primary snapshot method is last trade for all horizons,
  with horizon-specific VWAP fields retained for robustness diagnostics.
- Current configured staleness limits are `7d` for `30d/14d/7d`, `3d` for
  `3d`, `1d` for `1d`, `6h` for `6h`, `1h` for `1h`, and `5m` for `close`.
- Records staleness and source timestamps.
- Writes summary metadata, effective config, candidate/drop counts, horizon counts, method counts, duplicate checks, and no-look-ahead checks.
- Validation fails on duplicate keys or look-ahead sources.

Limitations:

- Snapshot price is a transaction proxy because historical quotes/order-book depth are unavailable.
- Snapshot policy is horizon-specific but not domain-specific.

### `src/predmkt/taxonomy/`

Status: partial.

Capabilities:

- Adds `domain`, `category`, `event_family_id`, `taxonomy_source`, `taxonomy_confidence`, and `taxonomy_notes`.
- Preserves `event_id`, `title`, `yes_sub_title`, and `no_sub_title`.
- Defaults `event_family_id` to `event_id`, with `contract_id` fallback when `event_id` is missing.
- Defaults `domain` and `category` to `unknown`.
- Supports explicit exact-match `event_id` mapping rules from `configs/taxonomy.yaml`.
- Writes taxonomy-enriched panel, audit table, and summary JSON.
- Validates that every row has event-family, domain, and category fields.

Limitations:

- No title-based inference is enabled.
- Current full taxonomy output has `domain = unknown` and `category = unknown` for all rows.
- Event-family grouping is a conservative proxy, not a final leakage-safe taxonomy.

### `src/predmkt/features/`

Status: partial.

Capabilities:

- Builds `data/processed/modeling_panel.parquet`.
- Adds `raw_probability`, `clipped_probability`, `logit_probability`.
- Adds `horizon_name`, `horizon_timedelta`, `forecast_month`, `listing_month`.
- Carries domain/category/event-family taxonomy fields.
- Adds price staleness, cumulative volume/trade count through `forecast_ts`.
- Adds 24h pre-forecast momentum and volatility using transaction prices.
- Adds 7d liquidity window volume/count and `log(1 + cumulative_volume)` public liquidity proxy.
- Adds explicit missing/inferred flags for taxonomy, event-family, listing timestamp, probability, momentum, volatility, and liquidity.
- Validates no look-ahead feature sources and duplicate keys.

Limitations:

- Domain/category are all unknown until taxonomy mapping is expanded.
- Event-family is inferred from the taxonomy proxy for all current rows.
- Liquidity lacks order-book depth, spreads, and executable quote data.
- Momentum/volatility use transaction prices rather than quote midpoints.

### `src/predmkt/metrics/`

Status: complete for Phase 4 raw baseline evaluation.

Capabilities:

- Computes Brier score and log loss with documented probability clipping.
- Computes fixed-width reliability bins and ECE while retaining empty and sparse bins.
- Fits calibration intercept/slope using a dependency-free logistic IRLS routine.
- Evaluates raw probabilities from `data/processed/modeling_panel.parquet`.
- Writes overall, grouped, reliability, calibration, missing-note, and summary artifacts.
- Uses equal-contract aggregation as the confirmatory default and records aggregation mode in outputs.
- Writes equal-event-family diagnostics using the current event-family proxy.
- Allows trade-weighted robustness only when explicitly enabled in metrics config.

Limitations:

- Phase 4 evaluates raw probabilities only; recalibrators and walk-forward model evaluation are not implemented here.
- Domain/category grouped outputs are not domain-level findings while taxonomy coverage is `unknown`.
- Liquidity/staleness groups use public feature-panel proxies, not executable quote or order-book data.

### `src/predmkt/plots/`

Status: partial.

Capabilities:

- Generates pandas/matplotlib PNG and SVG diagnostic figures from raw baseline metric artifacts.
- Current figures cover metric overview, horizon-level Brier/log-loss/ECE,
  calibration intercept/slope by horizon, overall reliability bins, and
  reliability by horizon.
- Generates raw-baseline audit diagnostics for staleness, snapshot method,
  stricter close/1h variants, balanced-horizon panels, outcome orientation, and
  close timestamp semantics. The current policy reduced close median selected
  price staleness to `74s` and 1h median staleness to `509s`.
- Writes a plot summary JSON with source artifacts and effective config.
- Generates slide-ready presentation figures covering the pipeline, snapshot
  policy, horizon sample counts, scores, reliability, calibration, staleness,
  probability distributions, calibration-gap heatmap, balanced-panel
  comparison, orientation checks, close timestamp semantics, methodology
  refinement, and a summary dashboard.
- Generates manuscript figures from saved full-run artifacts: reliability
  diagrams, calibration-slope heatmap, score comparison, and edge-friction
  sensitivity.

Limitations:

- Raw-baseline diagnostic and presentation figures are not final manuscript
  outputs.
- The near-close audit is diagnostic only and does not select a revised snapshot
  method or stale-price rule.
- Manuscript figures require full walk-forward and edge artifacts by default;
  full artifacts are present locally, but manuscript claims still require
  scientific audit and uncertainty analysis.
- Domain/category plots are omitted while taxonomy coverage is unknown.

### `src/predmkt/reports/`

Status: partial.

Capabilities:

- Generates raw-baseline audit tables and figures for staleness, snapshot-method
  sensitivity, stricter close/1h variants, balanced-horizon composition,
  YES-side outcome orientation, and close timestamp semantics.
- Records whether cleaned contract `close_time` is available separately; current
  cleaned data retains `resolution_ts` but not a separate `close_time` column.
- Writes machine-readable audit artifacts and an effective config summary under
  `data/artifacts/raw_baseline/audit/`.
- Generates manuscript score, calibration, edge-friction, and limitation tables
  from saved full-run artifacts in CSV, Markdown, and LaTeX formats.
- Writes table manifests with source artifacts and effective reporting config.
- Generates non-confirmatory robustness tables for snapshot-method slices,
  liquidity filters, explicit domain-exclusion availability, and friction
  assumptions.
- Runs the Phase 11 saved-artifact audit over interim, processed, split,
  walk-forward, edge, robustness, and manuscript artifacts.
- Writes `artifact_inventory.parquet`, `audit_checks.parquet`,
  `phase_status.parquet`, `summary.json`, and
  `docs/audits/final_data_semantics.md`.
- Validates hard invariants for no-look-ahead snapshots/features, duplicate
  contract-horizon keys, split ordering, prediction/panel key consistency,
  equal-contract aggregation, YES-only simulated edge screens, and full-artifact
  manuscript manifests.

Limitations:

- Raw-baseline audit reports are diagnostic only and do not revise the baseline methodology.
- Manuscript tables require full walk-forward and edge artifacts by default.
- Robustness tables are sensitivity diagnostics, not replacement confirmatory
  results.
- Final audit currently returns `PARTIAL`, not `PASS`, because taxonomy,
  event-family grouping, close-time semantics, clustered uncertainty, and edge
  executability remain open final-deployment blockers.

### `src/predmkt/validation/`

Status: complete for Phase 5 split construction and Phase 7 simple walk-forward
model evaluation.

Capabilities:

- Builds monthly expanding walk-forward folds from `forecast_ts`.
- Uses one-month validation windows immediately before one-month test windows by default.
- Starts the default test sequence at `2024-01` and excludes incomplete final test months.
- Writes row-level split assignments with `fold_id`, `split`, `row_id`, `contract_id`, `horizon`, `forecast_ts`, and `event_family_id`.
- Validates train timestamps precede validation timestamps and validation timestamps precede test timestamps.
- Validates no row appears in multiple splits within the same fold.
- Detects strict event-family overlap across train/validation/test splits.
- Falls back from `event_family_id` to `event_id` when operating on raw snapshot panels.
- Evaluates configured raw/Platt/beta/isotonic calibrators on identical future
  test rows.
- Fits models only on train+validation rows whose `resolution_ts` is at or
  before each fold's test start.
- Writes prediction, fold metric, aggregate metric, calibrator fit,
  event-family leakage, and summary artifacts.
- Records config hash, git commit, and git dirty flag when available.

Limitations:

- Strict event-family overlaps are reported, not automatically filtered.
- Event-family identifiers are still conservative taxonomy proxies until family mapping coverage improves.
- Phase 7 does not implement clustered inference, hierarchical calibrators,
  publication-ready plots, or edge simulation.

### `src/predmkt/calibration/`

Status: complete for Phase 6 reusable simple recalibrators.

Capabilities:

- Provides a common `fit(probabilities, outcomes)` and
  `predict_proba(probabilities)` interface.
- Provides `RawCalibrator`, `PlattCalibrator`, `BetaCalibrator`, and
  `IsotonicCalibrator`.
- Clips every returned prediction to the configured epsilon, currently
  `0.000001` in `configs/models.yaml`.
- Uses dependency-free logistic IRLS for Platt and beta calibration.
- Uses dependency-free pool-adjacent-violators for isotonic calibration.
- Provides a registry with names `raw`, `platt`, `logistic`, `beta`, and
  `isotonic`.
- Loads enabled calibrators from `configs/models.yaml`.
- Falls back to clipped raw probabilities on degenerate Platt/beta folds with
  explicit statuses.
- Treats negative Platt slopes as invalid for confirmatory monotone
  recalibration and falls back to raw.

Limitations:

- These are model components; walk-forward prediction and raw-vs-recalibrated
  score artifacts are written by `src/predmkt/validation/`.
- No hierarchical or partially pooled calibrator exists.
- Hyperparameter selection over folds remains Phase 7.

### `src/predmkt/edge/`

Status: complete for Phase 8 conservative expected-value screens.

Capabilities:

- Loads edge-simulation assumptions from `configs/backtest.yaml`.
- Reads walk-forward predictions and joins modeling-panel metadata by reconstructed `row_id`.
- Screens taker-only YES-side candidates without synthetic NO complement trades.
- Computes configurable Kalshi-style fee proxy, spread haircut, slippage haircut, and annualized capital-lockup charge.
- Emits fee-only, fee+spread, and fee+spread+slippage tiers for comparison.
- Records gross edge, net edge, threshold flags, cost components, and simulated realized net per $1 payout contract.
- Writes candidate, tier-summary, model-tier-summary, exclusion, and summary artifacts.
- Validates nonnegative cost assumptions, probability bounds, timestamp joins, and prediction/panel key consistency.

Limitations:

- Outputs are simulated EV screens, not executable profits or trade recommendations.
- Entry prices are transaction snapshot proxies; no historical executable bid/ask or order-book depth is available.
- Fee formula is a configurable proxy, not a versioned historical exchange billing audit.
- Spread/slippage are assumption haircuts rather than observed execution costs.
- NO-side opportunities are intentionally not simulated until explicit NO-side executable prices are available.

## Test Coverage Registry

Implemented tests:

- Import smoke test.
- Raw inspection and Parquet inspection tests.
- Schema validation tests.
- Timestamp parsing tests.
- Full Kalshi schema audit helpers.
- Cleaning invariants.
- Snapshot default horizons, config loading, no-look-ahead, duplicate-key rejection, stale tolerance, canonical columns.
- Taxonomy default behavior, explicit mapping override, no row drops, config loading.
- Feature config loading, no-look-ahead construction, cumulative volume/trade count, momentum/volatility windows, validation failure.
- Metric regression tests with known Brier/log-loss/ECE values.
- Reliability empty/sparse bin tests.
- Calibration fit and degenerate-group tests.
- Tests proving primary aggregation is not trade-weighted by default and trade weighting is opt-in.
- Raw-baseline plot config loading and PNG/SVG output smoke tests.
- Raw-baseline audit config loading and synthetic staleness/method/balanced/orientation tests.
- Presentation figure config loading and PNG output smoke tests.
- Walk-forward split config loading, expanding monthly fold construction,
  timestamp ordering, deterministic assignment independent of input order,
  event-family leakage detection, no-leakage cases, event-id fallback, missing
  timestamp failure, and script/config artifact smoke tests.
- Recalibrator interface tests for fit/predict shape, probability bounds,
  registry aliases, unknown-name failures, raw clipping, Platt/beta finite
  predictions, degenerate-fold fallbacks, isotonic monotonicity, and model config
  loading.
- Walk-forward evaluation tests for script/config artifact smoke output,
  identical test row IDs across models, exclusion of future-unresolved labels
  from fit rows, split/panel key mismatch failure, bounded recalibrated
  predictions, raw prediction identity, fold/aggregate metric schemas, and
  event-family overlap diagnostics.
- Edge simulation tests for fee subtraction, thresholding, negative-cost config
  failures, nonnegative effective costs, capital-lockup scaling, conservative
  tier ordering, no synthetic NO candidates, exclusion logging, config loading,
  and script/config artifact smoke output.
- Manuscript output tests for reporting config loading, figure/table generation
  from synthetic saved artifacts, CLI overrides, missing full-artifact failures,
  and no calibrator imports in reporting code.

Missing high-priority tests:

- Event-family leakage tests using final expanded taxonomy.
- Full end-to-end small pipeline is exercised by command; unit coverage uses a
  dry-run command-order test rather than rerunning the pipeline inside pytest.

## Research-Grade Gaps Before Claims

Cannot yet claim:

- Domain-level calibration findings.
- Final recalibration gains with clustered uncertainty.
- Executable trading profit or final tradable edge.
- Event-family leakage safety under a final expanded taxonomy.
- Final manuscript claims from figures/tables until Phase 12-17 blockers are
  resolved or explicitly scoped out.

Required next build steps:

1. Expand taxonomy coverage or explicitly decide that initial metrics are overall/horizon-only.
2. Harden event-family grouping and rerun leakage diagnostics.
3. Add clustered uncertainty for raw-vs-recalibrated result tables.
4. Add Murphy decomposition and expanded calibration methods, including bin-based
   correction and hierarchical/partially pooled models when taxonomy supports
   them.
5. Expand robustness to full alternate snapshot-method reruns if the current
   small-sample variants materially change conclusions.
6. Upgrade edge executability only if quote/depth, observed NO-side prices, or
   documented fee-regime data become available.
7. Add a final reproducibility/run-registry gate before any publishable claims.

## Current Phase Recommendation

Next recommended task: start ROADMAP Phase 12 by hardening taxonomy and
event-family mapping, then proceed to clustered uncertainty and confirmatory
inference.

Phase 4 now starts from `data/processed/modeling_panel.parquet`, uses `raw_probability` and `observed_outcome`, preserves one row per `contract_id x horizon_name`, and makes aggregation explicitly equal-contract by default. Domain/category slicing remains exploratory until taxonomy rules are added and audited.
