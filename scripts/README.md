# Scripts

Command-line entrypoints for reproducible workflows will live here.

Scripts should read explicit configs and write outputs to the appropriate data or paper directories.

Current data-build scripts:

- `build_interim_kalshi.py`: immutable raw Kalshi Parquet to cleaned interim tables.
- `build_quote_observations.py`: immutable raw Becker/Kalshi market snapshots to Phase 16 canonical quote observations under `data/interim/kalshi/`, with bid/ask validation and depth marked unavailable.
- `build_snapshot_panel.py`: cleaned interim tables to contract-horizon snapshot panel.
- `build_taxonomy_panel.py`: snapshot panel plus cleaned contract metadata to the Phase 12 taxonomy-enriched panel, using ordered exact-event, prefix, title-keyword, and event-family regex rules with audit outputs.
- `build_feature_panel.py`: taxonomy-enriched panel plus cleaned trades/contracts to the modeling feature panel.
- `evaluate_raw.py`: modeling feature panel to raw baseline forecast metrics under `data/artifacts/raw_baseline/`.
- `plot_raw_baseline.py`: raw baseline metric artifacts to pandas/matplotlib PNG and SVG diagnostic figures under `data/artifacts/raw_baseline/figures/`.
- `audit_raw_baseline.py`: raw baseline diagnostic audit for staleness, snapshot-method sensitivity, stricter close/1h variants, balanced panels, orientation, and close timestamp semantics.
- `make_presentation_figures.py`: current raw-baseline artifacts to slide-ready PNG/SVG figures under `data/artifacts/presentation/figures/`.
- `build_walkforward_splits.py`: processed contract-horizon/modeling panel to strict forecast-time expanding walk-forward split assignments and integrity diagnostics.
- `fit_walkforward.py`: modeling panel plus walk-forward splits to raw-vs-recalibrated fold predictions, metrics, calibrator fits, leakage diagnostics, and summary artifacts.
- `run_inference.py`: saved walk-forward predictions plus the modeling panel to Phase 13 event-family clustered confidence intervals, paired score differences, FDR adjustments, calibration intervals, and paired-loss diagnostics.
- `evaluate_decomposition.py`: saved walk-forward predictions to Phase 14 Murphy-style Brier decomposition artifacts with fixed-width bins and reported binning residuals.
- `run_edge_sim.py`: walk-forward predictions plus modeling-panel metadata to conservative simulated edge screens under transaction-proxy or quote-snapshot entry assumptions, explicit YES/NO side rules, configurable fees, spread/slippage, capacity, PnL, and capital-lockup assumptions.
- `make_figures.py`: saved full-run raw/walk-forward/edge/inference/decomposition artifacts to manuscript-ready figures, including sample construction, calibration-gain-over-time, exploratory domain reliability, and simulated edge PnL, under `paper/figures/`.
- `make_tables.py`: saved full-run raw/walk-forward/edge/inference/decomposition artifacts to manuscript-ready CSV, Markdown, and LaTeX tables with clustered uncertainty, exploratory domain reliability, Murphy decomposition, and Phase 16 edge-executability audit columns under `paper/tables/`.
- `run_robustness.py`: saved full-run artifacts to separately labeled Phase 15 robustness tables for snapshot methods, stale/liquidity filters, weighting sensitivity, domain/sports/taxonomy exclusions, event-family-purged sensitivity, friction assumptions, and optional full alternate snapshot-variant reruns.
- `run_small_sample_pipeline.py`: deterministic small-sample end-to-end replication command path from cleaned interim data through inference, decomposition, and paper figures/tables; supports `--dry-run` for command-order verification.
- `audit_final_artifacts.py`: Phase 11+ reporting-only audit of saved Phase 2-16 artifacts and data semantics, writing PASS/PARTIAL/FAIL checks under `data/artifacts/final_audit/` and `docs/audits/`.
- `build_final_run_registry.py`: Phase 17 final run registry and readiness audit, including config hashes, selected artifact hashes, data snapshot metadata, scoped CI check results, full-run command documentation, and `docs/final_readiness_audit.md`.
