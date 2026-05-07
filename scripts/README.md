# Scripts

Command-line entrypoints for reproducible workflows will live here.

Scripts should read explicit configs and write outputs to the appropriate data or paper directories.

Current data-build scripts:

- `build_interim_kalshi.py`: immutable raw Kalshi Parquet to cleaned interim tables.
- `build_snapshot_panel.py`: cleaned interim tables to contract-horizon snapshot panel.
- `build_taxonomy_panel.py`: snapshot panel plus cleaned contract metadata to taxonomy-enriched panel and taxonomy audit outputs.
- `build_feature_panel.py`: taxonomy-enriched panel plus cleaned trades/contracts to the modeling feature panel.
- `evaluate_raw.py`: modeling feature panel to raw baseline forecast metrics under `data/artifacts/raw_baseline/`.
- `plot_raw_baseline.py`: raw baseline metric artifacts to pandas/matplotlib PNG and SVG diagnostic figures under `data/artifacts/raw_baseline/figures/`.
- `audit_raw_baseline.py`: raw baseline diagnostic audit for staleness, snapshot-method sensitivity, stricter close/1h variants, balanced panels, orientation, and close timestamp semantics.
- `make_presentation_figures.py`: current raw-baseline artifacts to slide-ready PNG/SVG figures under `data/artifacts/presentation/figures/`.
- `build_walkforward_splits.py`: processed contract-horizon/modeling panel to strict forecast-time expanding walk-forward split assignments and integrity diagnostics.
- `fit_walkforward.py`: modeling panel plus walk-forward splits to raw-vs-recalibrated fold predictions, metrics, calibrator fits, leakage diagnostics, and summary artifacts.
