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

The current repository is Phase 0 scaffold only. Data download, model fitting, and analysis scripts will be added in later phases.

Expected workflow once those phases exist:

```bash
uv run python scripts/build_snapshot_panel.py --config configs/sampling.yaml
uv run python scripts/fit_walkforward.py --config configs/models.yaml
uv run python scripts/run_edge_sim.py --config configs/backtest.yaml
uv run python scripts/make_figures.py --config configs/figures.yaml
```

Until those scripts are implemented, use the smoke test to verify the package imports:

```bash
uv run pytest
```

## Data Policy

`data/raw/` is immutable source data storage. Do not edit, normalize, deduplicate, or overwrite files in `data/raw/`. All transformations must write to `data/interim/`, `data/processed/`, or `data/artifacts/` and should record enough metadata to reproduce the output.

No data has been downloaded for this scaffold.

## Repository Layout

```text
configs/                  YAML configs for data, sampling, models, backtests, figures
data/raw/                 immutable source data; never modify in place
data/interim/             cleaned normalized tables
data/processed/           contract-horizon panels and modeling datasets
data/artifacts/           cached model outputs, metrics, run results
src/predmkt/              research package
scripts/                  command-line entrypoints
tests/                    smoke and invariant tests
notebooks/                exploratory only
docs/                     methodology and data-source notes
paper/                    manuscript figures, tables, appendix outputs, bibliography
```
