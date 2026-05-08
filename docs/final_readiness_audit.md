# Final Readiness Audit

Status: **READY_WITH_LIMITATIONS**.

This Phase 17 readiness audit records the final run registry, config hashes, selected artifact hashes, data snapshot metadata, and verification command results. It does not change model methodology or reinterpret simulated edge outputs as executable trading profit.

## Run Registry

- Run label: `phase17_readiness_cleanup`
- Artifact run label: `full`
- Started UTC: `2026-05-08T18:50:45.450568+00:00`
- Ended UTC: `2026-05-08T18:51:05.753330+00:00`
- Git commit: `4de9758b929b8709d1c61678bf5a934e7a45ed19`
- Git dirty: `True`
- Final artifact audit status: `PASS`
- Required check status: `PASS`
- Frozen config snapshot: `data/artifacts/final_run_registry/configs_snapshot`

## CI Command Set

| name | status | scope | note |
| --- | --- | --- | --- |
| ruff | PASS | repository lint |  |
| pytest | PASS | full test suite |  |
| mypy_scoped | PASS | typed Phase 16-17 surface | Full `uv run mypy src` is not the CI gate yet because legacy PyArrow/Pandas-heavy modules still need typing cleanup. |
| final_audit | PASS | saved artifact audit |  |

The scoped mypy command is the Phase 17 CI type-check gate. Full `uv run mypy src` is intentionally not the gate yet because older PyArrow/Pandas-heavy modules still require typing cleanup.

## Full Reproduction Commands

Full run command sequence:

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

Small-sample replication command:

```bash
uv run python scripts/run_small_sample_pipeline.py --config configs/replication_small.yaml
```

## Artifact Manifest Preview

| artifact_key | exists | size_bytes | hash_status | row_count |
| --- | --- | --- | --- | --- |
| interim_summary | True | 1470 | sha256 |  |
| quote_summary | True | 948 | sha256 |  |
| snapshot_summary | True | 8752 | sha256 |  |
| taxonomy_summary | True | 3699 | sha256 |  |
| modeling_summary | True | 2483 | sha256 |  |
| split_summary | True | 2070 | sha256 |  |
| raw_baseline_summary | True | 4376 | sha256 |  |
| walkforward_summary | True | 4058 | sha256 |  |
| inference_summary | True | 4899 | sha256 |  |
| decomposition_summary | True | 1824 | sha256 |  |
| edge_summary | True | 5022 | sha256 |  |
| robustness_summary | True | 8871 | sha256 |  |
| figure_manifest | True | 6524 | sha256 |  |
| table_manifest | True | 6600 | sha256 |  |
| final_audit_summary | True | 6198 | sha256 |  |
| final_audit_checks | True | 14116 | sha256 | 102.0 |
| final_audit_phase_status | True | 3593 | sha256 | 18.0 |
| final_audit_inventory | True | 8974 | sha256 | 38.0 |

## Data Snapshot Preview

| snapshot_key | exists | manifest_mode | file_count | size_bytes | row_count |
| --- | --- | --- | --- | --- | --- |
| raw_repo | True | metadata_only | 49593 | 53573488280 |  |
| raw_kalshi_markets | True | metadata_only | 769 | 596291689 |  |
| raw_kalshi_trades | True | metadata_only | 7214 | 3564871299 |  |
| interim_summary | True | summary_or_parquet_metadata | 1 | 1470 |  |
| quote_summary | True | summary_or_parquet_metadata | 1 | 948 | 7682445.0 |
| snapshot_summary | True | summary_or_parquet_metadata | 1 | 8752 | 695940.0 |
| taxonomy_summary | True | summary_or_parquet_metadata | 1 | 3699 | 695940.0 |
| modeling_summary | True | summary_or_parquet_metadata | 1 | 2483 | 695940.0 |
| split_summary | True | summary_or_parquet_metadata | 1 | 2070 | 695940.0 |
| raw_baseline_summary | True | summary_or_parquet_metadata | 1 | 4376 | 695940.0 |
| walkforward_summary | True | summary_or_parquet_metadata | 1 | 4058 | 2955672.0 |
| inference_summary | True | summary_or_parquet_metadata | 1 | 4899 |  |
| decomposition_summary | True | summary_or_parquet_metadata | 1 | 1824 | 2955672.0 |
| edge_summary | True | summary_or_parquet_metadata | 1 | 5022 | 8867016.0 |
| robustness_summary | True | summary_or_parquet_metadata | 1 | 8871 |  |
| figure_manifest | True | summary_or_parquet_metadata | 1 | 6524 |  |
| table_manifest | True | summary_or_parquet_metadata | 1 | 6600 |  |

## Claim Boundaries

- Final claims use contract-horizon rows with equal-contract or explicitly labeled equal-event-family aggregation.
- Domain/category claims require taxonomy confidence and ambiguity review.
- Edge outputs remain simulated expected-value screens, not executable trading profit.
- Current negative simulated PnL is a valid result and should not be tuned away.

## Remaining Limitations

- Phase 17 readiness records and validates existing full artifacts; it does not rerun the full scientific pipeline unless the documented command sequence is executed separately.
- Raw data hashing is metadata-only by default to avoid repeatedly hashing the entire local Becker data clone; configs and selected generated artifacts are hashed directly.
- Domain/category claims remain conditional on taxonomy confidence, ambiguity, and manual review.
- Event-family purging remains a robustness sensitivity; primary walk-forward outputs report overlaps and clustered inference resamples event-family IDs.
- Edge and PnL outputs remain simulated expected-value screens because public quote snapshots lack order-book depth.
- Full-run artifacts are expected to use artifact_run_label=full.
