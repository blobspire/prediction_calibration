# AGENTS.md

## Project identity
This is a Python research package for prediction-market calibration, recalibration, and edge detection. The initial project studies public Kalshi data, starting from Jon Becker's prediction-market-analysis data/repository. The main empirical design is market-level / horizon-level analysis, not trade-level analysis.

## Primary scientific rule
The confirmatory unit of analysis is `contract × forecast_horizon_bucket`. Do not accidentally convert the project into a trade-weighted analysis unless the task explicitly asks for a robustness check.

## Core research objective
Test whether market-weighted, walk-forward recalibration of Kalshi probabilities improves out-of-sample probability forecasts, then test whether those improvements survive conservative frictions: fees, spreads/slippage proxies, liquidity filters, stale-price controls, and capital lockup.

## Repository layout
Expected structure:

```text
configs/                  YAML configs for data, sampling, models, backtests, figures
data/raw/                 immutable source data; never modify in place
data/interim/             cleaned normalized tables
data/processed/           contract-horizon panels and modeling datasets
data/artifacts/           cached model outputs, metrics, run results
src/predmkt/io/           data readers, API adapters, schema validators
src/predmkt/cleaning/     timestamp normalization, resolution filters, delist/void filters
src/predmkt/taxonomy/     category and event-family mapping
src/predmkt/sampling/     contract-horizon snapshot construction
src/predmkt/features/     liquidity, staleness, momentum, volatility features
src/predmkt/metrics/      Brier, log loss, ECE, calibration slope/intercept, reliability decomposition
src/predmkt/calibration/  raw baseline, isotonic, beta, logistic, hierarchical models
src/predmkt/validation/   expanding-window splits and leakage checks
src/predmkt/edge/         fee, slippage, liquidity, lockup-aware edge simulation
src/predmkt/plots/        publication figures
src/predmkt/reports/      manuscript-ready tables and summaries
scripts/                  command-line entrypoints
notebooks/                exploratory only; not confirmatory analysis
paper/                    manuscript figures, tables, appendix outputs, bibliography
tests/                    schema, leakage, metric, and backtest tests
```

## Non-negotiable constraints
- Never modify files under `data/raw/`.
- Do not use random train/test splits for confirmatory analysis.
- Split by forecast timestamp, not by row order or resolution timestamp, unless a task explicitly asks for a robustness check.
- Never use observations after a forecast timestamp to construct that forecast's features or snapshot price.
- Do not let one large market dominate primary results. Equal-contract or equal-event-family weighting should be the primary estimand.
- Do not present simulated edge as executable trading profit unless the simulation includes conservative fees, liquidity, slippage/staleness assumptions, and the limitations are documented.
- Notebooks are exploratory only. Reusable logic belongs under `src/predmkt/`.
- Every new data transformation should either preserve a manifest/hash or produce enough logging to reproduce the output.

## Development workflow
Before implementation:
1. Read this file, `PROJECT_BRIEF.md`, and `ROADMAP.md`.
2. Inspect relevant source files.
3. For multi-file or ambiguous tasks, propose a plan before editing.

During implementation:
1. Prefer small, reviewable changes.
2. Add tests with the implementation.
3. Keep scientific assumptions explicit in config or docs.
4. Use deterministic seeds where randomness is involved.
5. Favor simple inspectable models before high-dimensional or black-box models.

After implementation:
1. Run the relevant tests.
2. Report what changed.
3. Report what was not verified.
4. Mention any assumptions or data limitations.

## Suggested commands
These may evolve as the repo is scaffolded:

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy src
uv run python scripts/build_snapshot_panel.py --config configs/sampling.yaml
uv run python scripts/fit_walkforward.py --config configs/models.yaml
uv run python scripts/run_edge_sim.py --config configs/backtest.yaml
uv run python scripts/make_figures.py --config configs/figures.yaml
```

If the repo does not yet define these commands, create the smallest working equivalent rather than pretending they exist.

## Coding conventions
- Use type hints for public functions.
- Prefer dataclasses or typed config objects for structured inputs.
- Keep I/O, transformation, modeling, validation, and plotting separated.
- Do not hide important methodological choices inside notebooks.
- Avoid global mutable state.
- Make time zones explicit.
- Clip probabilities for log loss using a documented epsilon.
- Record configuration values used to produce each artifact.

## Testing requirements
Add or update tests whenever changing behavior.

High-priority tests:
- Schema validation tests.
- Timestamp parsing tests.
- No-look-ahead tests for snapshot construction.
- Walk-forward split integrity tests.
- Event-family leakage tests.
- Metric regression tests with known values.
- Recalibrator fit/predict interface tests.
- Edge simulation invariant tests.

Minimum no-look-ahead invariant:
```text
For every contract-horizon row, all source observations used to compute features or price must satisfy source_ts <= forecast_ts < resolution_ts.
```

Minimum weighting invariant:
```text
Primary metric aggregation must not weight rows by number of trades unless the config explicitly requests a trade-weighted robustness check.
```

## Data and methodology documentation
Document:
- Source data path and version.
- Columns used and inferred.
- Exclusion filters.
- Horizon grid and tolerance windows.
- Snapshot method: last trade, VWAP, midpoint, or executable quote.
- Fee schedule assumptions.
- Slippage/liquidity assumptions.
- Validation split dates.
- Known limitations.

## Done definition
A task is done only when:
- The requested behavior is implemented.
- Relevant tests pass or failures are clearly reported.
- New assumptions are documented.
- Outputs are reproducible from configs or scripts.
- The final response summarizes changed files and verification steps.

## Documentation Updates
When completing any implementation task or phase, evaluate whether `README.md` should be updated.

Update `README.md` when the change affects:
- setup or installation
- CLI commands
- configuration files
- expected data layout
- generated outputs
- testing or validation commands
- user-facing workflow
- supported project functionality
- known limitations or assumptions

Do not update `README.md` for purely internal refactors, minor test-only changes, formatting-only changes, or implementation details that do not affect how a human or future agent should use the project.

When updating `README.md`:
- Keep it concise and operational.
- Prefer command examples over prose.
- Document only functionality that actually exists.
- Do not claim scientific results unless they were produced from real data and saved outputs.
- Link or refer to deeper docs when details belong elsewhere.

## Review focus
When asked to review code, prioritize:
1. Look-ahead leakage.
2. Accidental trade weighting.
3. Event-family contamination.
4. Raw-data mutation.
5. Incorrect probability or fee math.
6. Stale-price artifacts.
7. Non-reproducible outputs.
8. Overstated edge claims.
