# Current Capabilities

Last updated: 2026-05-08.

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
- Domain-level findings remain conditional: taxonomy now has audited rule-based coverage, but low-confidence title, ambiguous, and unknown rows are not confirmatory.
- Event-family leakage checks use hardened Phase 12 family IDs where rules match, and Phase 13 uncertainty resamples `event_family_id` clusters. Overlaps are still reported, not filtered.

## Phase Gate Summary

| Area | Status | Current State | Main Remaining Gap |
|---|---|---|---|
| Phase 0 repository bootstrap | complete | Package scaffold, configs/data/docs/scripts/tests layout, import smoke test, README/data policy. | None material. |
| Phase 1 raw schema inspection | complete | Read-only raw inspection, Parquet schema audit, schema validators, timestamp parsing tests. | Raw hash manifests are available for representative files, not all 50G by default. |
| Becker raw data setup | complete | Becker repo/data present under `data/raw/becker_prediction_market_analysis`; raw repo clean. | Raw data is local and ignored; another machine must clone/download separately. |
| Phase 2 raw-to-interim Kalshi cleaning | complete | Resolved binary contracts and cleaned price observations are built and logged; raw `close_time` is retained separately from normalized `resolution_ts`. | Richer void/delist semantic review by family remains a possible future audit extension. |
| Phase 3 contract-horizon snapshots | complete | Config-driven full horizon grid, horizon-specific last-trade/VWAP policy, no-look-ahead validation, canonical panel schema. | Snapshot uses trade proxy only; no historical quotes/order book. |
| Phase 12 taxonomy layer | complete | Ordered exact-event, event-family regex, prefix, title-keyword, and default-unknown rules produce audited domain/category/sports/event-family fields with confidence and ambiguity flags. | Domain/category claims still require confidence/ambiguity filters and manual review for low-confidence or unknown rows. |
| Forecast feature panel | partial | Config-driven modeling panel with probabilities, horizon fields, Phase 12 taxonomy fields, staleness, cumulative activity, momentum, volatility, liquidity proxy. | Liquidity is public trade proxy only; momentum/volatility use transaction prices. |
| Phase 4 baseline forecast metrics | complete | Config-driven raw baseline metrics, equal-contract primary aggregation, reliability bins, ECE, calibration slope/intercept, grouped artifacts, and known-value tests. | Domain/category grouped outputs are taxonomy-rule based and exploratory until uncertainty/manual review supports claims. |
| Phase 5 walk-forward validation | complete | Config-driven monthly expanding splits by `forecast_ts`, one-month validation/test windows, split-integrity artifacts, and strict event-family overlap diagnostics. | Event-family overlaps are reported, not filtered. |
| Phase 6 recalibrators | complete | Common interface, raw/Platt/beta/isotonic/binned-reliability calibrators, experimental hierarchical-EB, model config, registry, bounded predictions, and synthetic tests. | `hierarchical_eb` remains experimental and not a full Bayesian mixed model. |
| Phase 7 walk-forward evaluation | complete | Config-driven raw-vs-recalibrated evaluation with identical test folds, label-available fit rows, expanded Phase 14 model set, fold/aggregate metrics, fit artifacts, config hash, git commit, and leakage diagnostics. | Full-scale audited edge interpretation remains later work. |
| Phase 8/16 edge simulation and executability | complete | Config-driven simulated edge screens now support transaction-proxy and explicit quote-snapshot entry modes, versioned fee proxy schedules, capacity/PnL assumptions, YES/NO side checks, and executability audit artifacts. | Full trading claims remain out of scope; Becker snapshots lack order-book depth, so capacity and PnL remain assumption-dependent. |
| Phase 9 plots/reports | complete | Config-driven manuscript figures and tables are generated from saved raw/walk-forward/edge/inference/decomposition/edge-executability artifacts under `paper/`, including sample construction, calibration gain over time, exploratory domain reliability, and simulated PnL. | Domain figures remain exploratory until taxonomy review. |
| Phase 10 replication/robustness | complete | Config-driven robustness diagnostics and deterministic small-sample replication command path are implemented with separated non-confirmatory outputs. | Phase 15 expands robustness further; all robustness outputs remain sensitivity diagnostics. |
| Phase 11 final scientific audit | complete | Config-driven saved-artifact audit writes inventory, checks, phase status, summary JSON, and `docs/audits/final_data_semantics.md`; Phase 16 adds explicit edge-executability checks. | Phase 17 final run-registry/readiness hardening remains. |
| Phase 13 confirmatory inference | complete | Config-driven event-family clustered uncertainty reads saved walk-forward predictions, writes score intervals, paired deltas, calibration intervals, FDR adjustments, paired-loss diagnostics, and summary artifacts. | Domain/category claims remain conditional on taxonomy confidence and ambiguity. |
| Phase 14 expanded calibration and decomposition | complete | Default walk-forward now includes `binned_reliability` and experimental `hierarchical_eb`; Murphy-style decomposition artifacts and manuscript table are generated from saved predictions. | `hierarchical_eb` is experimental; Murphy components are binned and retain `binning_residual`. |
| Phase 15 full robustness reruns | complete | Full robustness now covers stale/liquidity filters, equal-event-family and trade-weighted sensitivity, sports/domain/taxonomy exclusions, event-family-purged sensitivity, friction scenarios, and three full alternate snapshot-variant downstream reruns. | Robustness outputs are diagnostic and non-confirmatory; default methodology should change only if separated robustness evidence justifies it. |
| Phase 17 final readiness | complete | Final run registry, config/artifact/data manifests, scoped CI command set, and `docs/final_readiness_audit.md` are implemented under `configs/final_run.yaml` and `scripts/build_final_run_registry.py`. | Full `uv run mypy src` remains outside the CI gate until legacy PyArrow/Pandas-heavy modules are typed. |
| Final deployment readiness | partial | Phase 0-17 implementation is a working v1 research package with local full artifacts, final audit outputs, run registry, clustered inference, expanded calibrators, decomposition, full robustness artifacts, and edge-executability audits. | Publishable claims must still respect taxonomy, event-family, and simulated-edge limitations. |

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
uv run python scripts/run_inference.py --config configs/inference.yaml
uv run python scripts/run_edge_sim.py --config configs/backtest.yaml
uv run python scripts/evaluate_decomposition.py --config configs/decomposition.yaml
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

Latest local verification used `uv run pytest` and passed `131 passed`
after Phase 17 tests were added.
`uv run ruff check .` also passes. The Phase 17 scoped `mypy` CI gate passes
for `src/predmkt/io/kalshi_quotes.py`, `src/predmkt/edge`,
`src/predmkt/reports/manuscript.py`, `src/predmkt/plots/manuscript.py`,
`src/predmkt/reports/final_audit.py`, and
`src/predmkt/reports/final_readiness.py`. Full `uv run mypy src` is not yet
the CI gate because older PyArrow/Pandas-heavy modules need typing cleanup.
Full walk-forward, inference,
edge-simulation, Murphy decomposition, manuscript, robustness, small-sample
replication, quote, final-audit, and final-run-registry artifacts exist under
their configured output roots after the Phase 17 readiness run.

## Config Registry

| Config | Status | Purpose |
|---|---|---|
| `configs/sampling.yaml` | complete | Snapshot inputs/outputs, horizon grid, `close = resolution_ts - 1 minute`, horizon-specific staleness/VWAP windows, and snapshot method preference. |
| `configs/taxonomy.yaml` | complete | Phase 12 ordered exact-event, event-family regex, prefix, title-keyword, default-unknown, confidence, ambiguity, sports flag, and fallback event-family rules. |
| `configs/features.yaml` | partial | Modeling feature inputs/outputs, probability epsilon, 24h momentum/volatility windows, 7d liquidity window, missing-feature policy. |
| `configs/quotes.yaml` | complete | Phase 16 immutable Becker/Kalshi market snapshot bid/ask normalization to interim quote observations with `_fetched_at` as UTC quote timestamp and depth unavailable. |
| `configs/metrics.yaml` | complete | Raw baseline metric input/output paths, log-loss clipping epsilon, reliability bins, calibration fit settings, groupings, and equal-contract primary aggregation. |
| `configs/figures.yaml` | partial | Raw-baseline diagnostic figure inputs, output directory, horizon order, aggregation mode, PNG/SVG formats, and DPI. |
| `configs/raw_baseline_audit.yaml` | partial | Diagnostics for staleness, snapshot-method sensitivity, stricter close/1h variants, balanced panels, orientation, and close timestamp semantics. |
| `configs/presentation.yaml` | partial | Slide-ready raw-baseline figure inputs, presentation output directory, horizon order, formats, DPI, and recorded pre-refinement comparison values. |
| `configs/models.yaml` | complete | Recalibrator input/context columns, enabled raw/Platt/beta/isotonic/binned-reliability/experimental hierarchical-EB model names, prediction clipping epsilon, fit controls, metric settings, fit-label policy, and walk-forward artifact directory. |
| `configs/validation.yaml` | complete | Forecast-time expanding walk-forward split inputs/outputs, monthly window settings, event-family fallback policy, and strict overlap leakage diagnostics. |
| `configs/backtest.yaml` | complete | Conservative edge-screen inputs, transaction-proxy or quote-snapshot execution mode, explicit YES/NO side policy, versioned fee proxy schedule, spread/slippage haircuts, capacity/PnL assumptions, optional liquidity/staleness/quote filters, and artifact directory. |
| `configs/inference.yaml` | complete | Phase 13 saved-artifact inference inputs, event-family bootstrap unit, iteration count, confidence level, FDR alpha, sparse-group thresholds, groupings, and bucket definitions. |
| `configs/decomposition.yaml` | complete | Phase 14 saved-prediction Murphy-style decomposition inputs, output directory, fixed-width bin settings, sparse-bin threshold, and grouping definitions. |
| `configs/reporting.yaml` | complete | Manuscript figure/table input artifact dirs including inference and decomposition, `paper/` output dirs, model/horizon order, figure/table formats, metric scope, and explicit full-vs-smoke run label. |
| `configs/robustness.yaml` | complete | Non-confirmatory robustness inputs/outputs, snapshot-method slices, liquidity filters, taxonomy-rule domain exclusions, friction scenarios, and small snapshot variants. |
| `configs/replication_small.yaml` | complete | Deterministic small-sample replication paths, stage configs including inference/decomposition, limits, run label, and separate processed/artifact/paper output roots. |
| `configs/final_audit.yaml` | complete | Phase 11+ saved-artifact and data-semantics audit inputs, Phase 13 inference checks, Phase 14 decomposition/experimental-label checks, Phase 15 robustness checks, Phase 16 edge-executability checks, expected horizons/models, full-run labels, hard-fail/partial severity rules, known limitations, and audit output paths. |
| `configs/final_run.yaml` | complete | Phase 17 final run registry inputs, full-run and small-sample command documentation, config/artifact/data manifest policy, scoped CI command set, and readiness audit output paths. |

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
- `data/interim/kalshi/quote_observations.parquet`: 7,682,445 Phase 16 explicit bid/ask quote snapshots from Becker market files.
- `data/interim/kalshi/quote_observations_summary.json`
- Contract exclusions: 368,070 rows.
- Price-observation exclusions: 4,410,376 rows.

Processed outputs:

- `data/processed/contract_horizon_panel.parquet`: 695,940 rows.
- `data/processed/contract_horizon_panel_summary.json`
- `data/processed/contract_horizon_panel_taxonomy.parquet`: 695,940 rows.
- `data/processed/contract_horizon_taxonomy_audit.parquet`
- `data/processed/contract_horizon_taxonomy_examples.parquet`
- `data/processed/contract_horizon_taxonomy_summary.json`
  - unknown rows: 92,904 (`13.35%`)
  - ambiguous rows: 1,209 (`0.17%`)
  - sports rows: 259,647 (`37.31%`)
  - event-family regex rows: 120,843; event-id fallback rows: 575,097
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
- `data/artifacts/walkforward/predictions.parquet`: full 22-fold walk-forward output with 2,955,672 model prediction rows from six models.
- `data/artifacts/walkforward/fold_metrics.parquet`: 1,320 fold-level metric rows.
- `data/artifacts/walkforward/aggregate_metrics.parquet`: 120 pooled and fold-macro metric rows.
- `data/artifacts/walkforward/calibrator_fits.parquet`
- `data/artifacts/walkforward/event_family_leakage.parquet`: 318 reported fit/test event-family overlaps.
- `data/artifacts/walkforward/summary.json`
- `data/artifacts/inference/score_intervals.parquet`: 774 score interval rows.
- `data/artifacts/inference/paired_score_differences.parquet`: 645 paired model-vs-raw rows with p-values/q-values.
- `data/artifacts/inference/calibration_intervals.parquet`: 120 calibration coefficient interval rows.
- `data/artifacts/inference/multiple_comparison_adjustments.parquet`: 645 Benjamini-Hochberg adjustment rows.
- `data/artifacts/inference/paired_loss_diagnostics.parquet`: 430 event-family paired-loss diagnostic rows.
- `data/artifacts/inference/bootstrap_replicates.parquet`: 1,506,000 replicate rows from 1,000 event-family bootstrap iterations.
- `data/artifacts/inference/summary.json`: 70,876 event-family clusters.
- `data/artifacts/decomposition/murphy_decomposition.parquet`: 60 Murphy component rows.
- `data/artifacts/decomposition/murphy_bins.parquet`: 600 Murphy bin rows.
- `data/artifacts/decomposition/summary.json`
- `data/artifacts/edge_sim_smoke/edge_candidates.parquet`: one-fold smoke edge-screen output, not confirmatory.
- `data/artifacts/edge_sim_smoke/edge_summary_by_tier.parquet`
- `data/artifacts/edge_sim_smoke/edge_summary_by_model_tier.parquet`
- `data/artifacts/edge_sim_smoke/excluded_rows.parquet`
- `data/artifacts/edge_sim_smoke/summary.json`
- `data/artifacts/edge_sim/edge_candidates.parquet`: full edge-screen output with 8,867,016 candidate rows.
- `data/artifacts/edge_sim/edge_summary_by_tier.parquet`
- `data/artifacts/edge_sim/edge_summary_by_model_tier.parquet`
- `data/artifacts/edge_sim/edge_summary_by_side_model_tier.parquet`
- `data/artifacts/edge_sim/excluded_rows.parquet`
- `data/artifacts/edge_sim/executability_audit.parquet`
- `data/artifacts/edge_sim/fee_schedule_audit.parquet`
- `data/artifacts/edge_sim/capacity_summary.parquet`
- `data/artifacts/edge_sim/simulated_pnl.parquet`
- `data/artifacts/edge_sim/summary.json`
- `paper/figures/figure_manifest.json`
- `paper/figures/manuscript_*.{png,svg,pdf}`
- `paper/tables/table_manifest.json`
- `paper/tables/*.csv`
- `paper/tables/*.md`
- `paper/tables/*.tex`
- `data/artifacts/robustness/summary.json`: full robustness run over 2,955,672 saved prediction rows.
- `data/artifacts/robustness/snapshot_method_slices.parquet`
- `data/artifacts/robustness/liquidity_filter_sensitivity.parquet`
- `data/artifacts/robustness/staleness_filter_sensitivity.parquet`
- `data/artifacts/robustness/weighting_sensitivity.parquet`
- `data/artifacts/robustness/event_family_exclusion_sensitivity.parquet`
- `data/artifacts/robustness/domain_exclusion_status.parquet`: records non-confirmatory domain/category exclusion sensitivity using Phase 12 taxonomy.
- `data/artifacts/robustness/friction_assumption_sensitivity.parquet`
- `data/artifacts/robustness/snapshot_variant_runs.parquet`: two small-sample snapshot variant summaries.
- `data/artifacts/robustness/full_snapshot_variant_runs.parquet`
- `data/artifacts/robustness/full_snapshot_variant_metrics.parquet`
- `data/artifacts/robustness/full_snapshot_variants/*`: separated alternate snapshot-method downstream robustness artifacts.
- `paper/robustness/tables/*.csv`
- `paper/robustness/tables/*.md`
- `data/processed/replication_small/contract_horizon_taxonomy_examples.parquet`
- `data/processed/replication_small/modeling_panel.parquet`: deterministic small-sample replication panel with 8,882 rows.
- `data/artifacts/replication/small_sample/replication_manifest.json`: all 11 stages completed.
- `data/artifacts/replication/small_sample/walkforward/predictions.parquet`: 2,454 small-sample walk-forward predictions over 2 evaluated folds.
- `data/artifacts/replication/small_sample/inference/summary.json`
- `data/artifacts/replication/small_sample/decomposition/summary.json`
- `data/artifacts/replication/small_sample/edge_sim/edge_candidates.parquet`: 7,362 small-sample simulated edge candidate rows.
- `paper/replication/small_sample/figures/figure_manifest.json`
- `paper/replication/small_sample/figures/manuscript_*.{png,svg,pdf}`
- `paper/replication/small_sample/tables/table_manifest.json`
- `paper/replication/small_sample/tables/*.{csv,md,tex}`
- `data/artifacts/final_audit/artifact_inventory.parquet`
- `data/artifacts/final_audit/audit_checks.parquet`: current full audit has
  102 checks, 102 PASS, 0 PARTIAL, and 0 FAIL.
- `data/artifacts/final_audit/phase_status.parquet`
- `data/artifacts/final_audit/summary.json`: current overall status is
  `PASS`.
- `docs/audits/final_data_semantics.md`
- `data/artifacts/final_run_registry/run_registry.json`
- `data/artifacts/final_run_registry/config_manifest.parquet`
- `data/artifacts/final_run_registry/configs_snapshot/`
- `data/artifacts/final_run_registry/artifact_manifest.parquet`
- `data/artifacts/final_run_registry/data_snapshot_manifest.parquet`
- `data/artifacts/final_run_registry/check_results.parquet`: current required
  checks are Ruff PASS, pytest PASS, scoped mypy PASS, and final audit PASS.
- `data/artifacts/final_run_registry/summary.json`: current readiness status is
  `READY_WITH_LIMITATIONS`.
- `docs/final_readiness_audit.md`

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
- Retain raw Becker/Kalshi `close_time` separately from normalized
  `resolution_ts` for downstream semantic audits.
- Normalize cleaned trade observations to `source_ts`, YES/NO prices, volume, taker side, and source fetch timestamp.
- Filter price observations to resolved binary contract IDs.
- Write exclusion summaries and build summary JSON.

Limitations:

- Uses `close_time` as provisional `resolution_ts`; the raw field is retained,
  but family-level verification of outcome-knowledge timing remains future work.
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
- Adds `is_sports`, `taxonomy_rule_id`, `taxonomy_ambiguous`, `event_family_source`, and `event_family_confidence`.
- Preserves `event_id`, `title`, `yes_sub_title`, and `no_sub_title`.
- Applies fixed precedence: `exact_event_id > event_family_regex > prefix_regex > title_keyword > default_unknown`.
- Supports explicit finance, sports, weather, politics, and entertainment prefix/title rules from `configs/taxonomy.yaml`.
- Uses regex event-family grouping where available, then explicit `event_id` and `contract_id` fallbacks with source/confidence fields.
- Marks conflicting title-keyword classifications ambiguous rather than silently choosing one.
- Writes taxonomy-enriched panel, audit table, unknown/ambiguous examples, and summary JSON.
- Validates that every row has event-family, domain, and category fields.

Limitations:

- Title-keyword inference is lower confidence and config-only.
- Current full taxonomy still has 92,904 unknown rows and 1,209 ambiguous rows.
- Many rows use `event_id` fallback because regex family grouping is available only for configured patterns.
- Domain-level claims need confidence/ambiguity filters and manual review.

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

- Domain/category include unknown and ambiguous rows from the Phase 12 taxonomy.
- Event-family uses regex grouping where available and fallback IDs elsewhere.
- Liquidity lacks order-book depth, spreads, and executable quote data.
- Momentum/volatility use transaction prices rather than quote midpoints.

### `src/predmkt/metrics/`

Status: complete for Phase 4 raw baseline evaluation and Phase 14
decomposition.

Capabilities:

- Computes Brier score and log loss with documented probability clipping.
- Computes fixed-width reliability bins and ECE while retaining empty and sparse bins.
- Fits calibration intercept/slope using a dependency-free logistic IRLS routine.
- Evaluates raw probabilities from `data/processed/modeling_panel.parquet`.
- Writes overall, grouped, reliability, calibration, missing-note, and summary artifacts.
- Uses equal-contract aggregation as the confirmatory default and records aggregation mode in outputs.
- Writes equal-event-family diagnostics using the Phase 12 event-family field.
- Allows trade-weighted robustness only when explicitly enabled in metrics config.
- Computes Murphy-style reliability/resolution/uncertainty decomposition from
  saved walk-forward predictions.
- Reports `raw_brier`, `decomposed_brier`, and `binning_residual` because
  fixed-width bins can contain varied probabilities.

Limitations:

- Phase 4 raw baseline evaluation scores raw probabilities only; walk-forward
  recalibrators are evaluated by `src/predmkt/validation/`.
- Murphy decomposition is binned and should not be described as an exact
  identity when the residual is nonzero.
- Domain/category grouped outputs are taxonomy-rule based and remain exploratory without confidence/ambiguity filters and clustered uncertainty.
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
- Manuscript figures/tables require full walk-forward, edge, inference, and
  decomposition artifacts by default.
- Domain/category manuscript plots remain exploratory because taxonomy coverage includes lower-confidence title, ambiguous, and unknown rows.

### `src/predmkt/inference/`

Status: complete for Phase 13 event-family clustered uncertainty.

Capabilities:

- Loads saved walk-forward predictions and the modeling panel from
  `configs/inference.yaml`.
- Validates prediction/panel row-key consistency and identical test row IDs
  across raw/recalibrated models.
- Computes equal-contract Brier, log-loss, ECE, calibration intercept/slope
  point estimates.
- Computes event-family clustered confidence intervals for score levels,
  paired model-vs-raw score differences, and calibration coefficients.
- Writes Benjamini-Hochberg q-values, sparse-group statuses, paired-loss
  diagnostics, bootstrap replicates, config hash, and run summary artifacts.
- Rejects iid row/trade bootstrap modes for confirmatory inference.

Limitations:

- Cluster IDs depend on Phase 12 event-family rules and fallbacks.
- Calibration coefficient intervals use a cluster influence bootstrap
  approximation rather than full refitting inside each bootstrap replicate.
- Domain/category inference remains conditional on taxonomy confidence and
  ambiguity review.

### `src/predmkt/reports/`

Status: partial.

Capabilities:

- Generates raw-baseline audit tables and figures for staleness, snapshot-method
  sensitivity, stricter close/1h variants, balanced-horizon composition,
  YES-side outcome orientation, and close timestamp semantics.
- Records that cleaned contract `close_time` is available separately from
  normalized `resolution_ts` and propagates through snapshot, modeling,
  split, prediction, and edge metadata artifacts.
- Writes machine-readable audit artifacts and an effective config summary under
  `data/artifacts/raw_baseline/audit/`.
- Generates manuscript score, calibration, edge-friction, and limitation tables
  from saved full-run artifacts in CSV, Markdown, and LaTeX formats, including
  Phase 13 confidence intervals, p-values/q-values, and effective cluster
  counts.
- Writes table manifests with source artifacts and effective reporting config.
- Generates non-confirmatory robustness tables for snapshot-method slices,
  liquidity filters, explicit domain-exclusion availability, and friction
  assumptions.
- Runs the Phase 11+ saved-artifact audit over interim, processed, split,
  walk-forward, inference, edge, robustness, and manuscript artifacts.
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
- Final audit can still return `PARTIAL`, not `PASS`, because event-family
  overlap policy and edge executability remain open final-deployment blockers.

### `src/predmkt/validation/`

Status: complete for Phase 5 split construction and Phase 7/14 walk-forward
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
- Evaluates configured raw/Platt/beta/isotonic/binned-reliability/hierarchical-EB
  calibrators on identical future test rows.
- Fits models only on train+validation rows whose `resolution_ts` is at or
  before each fold's test start.
- Writes prediction, fold metric, aggregate metric, calibrator fit,
  event-family leakage, and summary artifacts.
- Records config hash, git commit, and git dirty flag when available.

Limitations:

- Strict event-family overlaps are reported, not automatically filtered.
- Event-family identifiers are still conservative taxonomy proxies where regex
  grouping is unavailable.
- `hierarchical_eb` is experimental and reportable only with that label.

### `src/predmkt/calibration/`

Status: complete for Phase 6 reusable simple recalibrators and Phase 14
expanded baselines.

Capabilities:

- Provides a common `fit(probabilities, outcomes)` and
  `predict_proba(probabilities)` interface, plus optional context-aware methods.
- Provides `RawCalibrator`, `PlattCalibrator`, `BetaCalibrator`, and
  `IsotonicCalibrator`.
- Provides `BinnedReliabilityCalibrator` and experimental
  `HierarchicalEBCalibrator`.
- Clips every returned prediction to the configured epsilon, currently
  `0.000001` in `configs/models.yaml`.
- Uses dependency-free logistic IRLS for Platt and beta calibration.
- Uses dependency-free pool-adjacent-violators for isotonic calibration.
- Provides a registry with names `raw`, `platt`, `logistic`, `beta`,
  `isotonic`, `binned_reliability`, and `hierarchical_eb`.
- Loads enabled calibrators from `configs/models.yaml`.
- Falls back to clipped raw probabilities on degenerate Platt/beta folds with
  explicit statuses.
- Treats negative Platt slopes as invalid for confirmatory monotone
  recalibration and falls back to raw.

Limitations:

- These are model components; walk-forward prediction and raw-vs-recalibrated
  score artifacts are written by `src/predmkt/validation/`.
- `hierarchical_eb` is an empirical-Bayes additive approximation, not a full
  Bayesian mixed model.
- Hyperparameter selection over folds is not automated.

### `src/predmkt/edge/`

Status: complete for Phase 8 conservative expected-value screens and Phase 16
executability audit support.

Capabilities:

- Loads edge-simulation assumptions from `configs/backtest.yaml`.
- Reads walk-forward predictions and joins modeling-panel metadata by reconstructed `row_id`.
- Screens configured YES and, in quote mode only, explicit NO-side candidates
  without synthetic NO complement prices.
- Supports transaction snapshot proxies and quote-snapshot proxies built from
  Becker `yes_bid`/`yes_ask`/`no_bid`/`no_ask` fields.
- Computes configurable versioned Kalshi-style fee proxy, spread haircut,
  slippage haircut, fixed capacity assumption, simulated PnL, and annualized
  capital-lockup charge.
- Emits fee-only, fee+spread, and fee+spread+slippage tiers for comparison.
- Records gross edge, net edge, threshold flags, cost components, and simulated realized net per $1 payout contract.
- Writes candidate, tier-summary, model-tier-summary, side/model/tier summary,
  exclusion, executability-audit, fee-schedule, capacity, simulated-PnL, and
  summary artifacts.
- Validates nonnegative cost assumptions, probability bounds, timestamp joins, and prediction/panel key consistency.

Limitations:

- Outputs are simulated EV screens, not executable profits or trade recommendations.
- Entry prices are transaction or quote-snapshot proxies; quote snapshots do
  not prove executable fills.
- Becker quote snapshots do not include order-book depth or queue position.
- Fee schedules are configurable proxy assumptions unless a source note
  documents a historical billing regime.
- Spread/slippage are assumption haircuts rather than observed execution costs.
- NO-side opportunities are allowed only from explicit observed NO asks in quote
  mode; no NO prices are synthesized from complementarity.

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
- Inference tests for Benjamini-Hochberg q-values, effective cluster counts,
  event-family clustered intervals, deterministic seeds, sparse-group statuses,
  iid-bootstrap rejection, prediction/panel key mismatch failure, known paired
  Brier deltas, and script/config smoke output.
- Edge simulation tests for fee subtraction, thresholding, negative-cost config
  failures, nonnegative effective costs, capital-lockup scaling, conservative
  tier ordering, no synthetic NO candidates, exclusion logging, config loading,
  and script/config artifact smoke output.
- Manuscript output tests for reporting config loading, figure/table generation
  from synthetic saved artifacts, CLI overrides, missing full-artifact failures,
  and no calibrator imports in reporting code.

Remaining test coverage limitations:

- Full end-to-end small pipeline is exercised by command; unit coverage uses a
  dry-run command-order test rather than rerunning the pipeline inside pytest.
- Full `uv run mypy src` is intentionally not part of the CI command set yet;
  the scoped Phase 17 mypy command is the current gate.

## Research-Grade Gaps Before Claims

Cannot yet claim:

- Domain-level calibration findings.
- Executable trading profit or final tradable edge.
- Event-family leakage safety under a primary exclusion policy; current
  confirmatory overlaps are reported, uncertainty is clustered by event family,
  and Phase 15 adds event-family-purged sensitivity diagnostics.
- Any claims that exceed the Phase 17 readiness boundaries recorded in
  `docs/final_readiness_audit.md`.

Required next build steps:

1. Manually review low-confidence, ambiguous, and unknown taxonomy slices before confirmatory domain claims.
2. Treat Phase 15 robustness outputs as diagnostic sensitivity checks; do not
   promote threshold or snapshot-policy changes without separated evidence that
   the default is materially fragile.
3. Treat `docs/final_readiness_audit.md` and `data/artifacts/final_run_registry/`
   as the source of truth for final reproducibility status.

## Current Phase Recommendation

Next recommended task: use the Phase 17 registry/readiness outputs to draft the
paper narrative and decide whether to manually review taxonomy slices before
making any domain-level claims. Phase 16 adds quote-snapshot and NO-side support
where explicit asks exist, but edge outputs remain simulated screens because
order-book depth is unavailable.

Phase 4 starts from `data/processed/modeling_panel.parquet`, uses
`raw_probability` and `observed_outcome`, preserves one row per
`contract_id x horizon_name`, and makes aggregation explicitly equal-contract by
default. Domain/category slicing now uses audited Phase 12 taxonomy rules, but
low-confidence, ambiguous, and unknown rows remain exploratory until reviewed.
