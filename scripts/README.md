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
