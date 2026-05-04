# TASK_LOG.md

This file is for Codex to maintain progress during implementation. Update it after each completed task or blocker.

## Current objective

Build a reproducible Python research package for market-weighted, horizon-indexed, walk-forward recalibration of Kalshi prediction-market probabilities, followed by conservative friction-aware edge simulation.

## Current task

None.

## Completed tasks

| Date | Task | Files changed | Tests run | Notes |
|---|---|---|---|---|
| 2026-05-04 | Phase 0 repository bootstrap | `.gitignore`, `README.md`, `pyproject.toml`, `configs/README.md`, `data/README.md`, `data/interim/README.md`, `data/processed/README.md`, `data/artifacts/README.md`, `docs/README.md`, `notebooks/README.md`, `paper/README.md`, `scripts/README.md`, `src/predmkt/**/__init__.py`, `tests/test_import.py` | `.venv/bin/python -m pytest`; `.venv/bin/python -c "import sys; sys.path.insert(0, 'src'); import predmkt; print(predmkt.__version__)"` | Scaffolded package layout only. No data downloaded. No models implemented. `data/raw/` is documented as immutable and left without tracked files. `uv` was not installed locally, so verification used a local virtualenv. |

## Blockers

None.

## Methodological decisions requiring human approval

- Changing the unit of analysis from `contract × forecast_horizon_bucket`.
- Changing the primary weighting scheme.
- Changing the walk-forward validation design.
- Changing the horizon grid after confirmatory analysis begins.
- Adding or changing fee, liquidity, slippage, capital-lockup, or tradeability assumptions.
- Presenting simulated edge as executable trading profit.
- Treating exploratory results as confirmatory.

## Next candidate tasks

1. Phase 0 — Repository bootstrap.
2. Phase 1 — Inspect source data and define schemas.
3. Phase 2 — Raw-to-cleaned Kalshi data pipeline.
4. Phase 3 — Contract-horizon snapshot panel.
5. Phase 4 — Baseline forecast metrics.
6. Phase 5 — Walk-forward splitter and leakage checks.
7. Phase 6 — Recalibrator registry and simple baselines.
8. Phase 7 — Walk-forward model evaluation.
9. Phase 8 — Edge simulation MVP.
10. Phase 9 — Publication figures and tables.
11. Phase 10 — Robustness and paper replication command.
