# Project Brief: Prediction Market Calibration, Recalibration, and Edge Detection

## One-sentence goal
Build a reproducible Python research package that tests whether public Kalshi prediction-market prices can be recalibrated into better out-of-sample probability forecasts, and whether any statistical gains survive conservative trading frictions.

## Research motivation
Prediction-market prices are informative, but they should not be treated automatically as true physical probabilities. Calibration can vary by horizon, domain, liquidity, market design, and microstructure. The main research opportunity is to move beyond descriptive, trade-weighted, or one-off train/test analyses and run a market-weighted, horizon-indexed, strictly walk-forward study on public Kalshi data.

The project should explicitly separate two questions:

1. **Forecasting question:** Do recalibrated probabilities improve future probabilistic accuracy relative to raw market prices?
2. **Trading question:** Do those improvements imply conservative executable edge after fees, slippage, liquidity filters, stale-price controls, and capital lockup?

A positive result is valuable, but a negative result can also be publishable if the methodology is stronger than prior work and clearly shows where apparent miscalibration disappears once tested out of sample or after frictions.

## Primary project
**Market-Weighted Walk-Forward Recalibration of Kalshi Probabilities with Friction-Aware Edge Translation**

### Main research question
Are equally weighted Kalshi contract-horizon snapshots systematically miscalibrated out of sample, and can walk-forward recalibration improve future probability estimates enough to imply conservative, executable edge after fees and liquidity haircuts?

### Main hypotheses
- **H1:** Raw Kalshi probabilities are informative but miscalibrated in specific domain-horizon slices, with stronger distortions in tails and at longer horizons.
- **H2:** Market-weighted expanding-window recalibration improves Brier score, log loss, calibration intercept/slope, and expected calibration error relative to raw prices.
- **H3:** Only a subset of statistical gains survives conservative frictions; surviving edge, if any, is concentrated in better-liquidity and lower-staleness slices rather than across all contracts.

## Scope

### Version 1: Kalshi-first
Start with Jon Becker's `prediction-market-analysis` repository / dataset as the initial public-data source. Do not require proprietary data. Supplement with direct Kalshi API or documented market-data endpoints only after the baseline pipeline works.

### Later extensions
- Polymarket calibration atlas.
- Calibration residual persistence.
- Kalshi-Polymarket duplicate-contract / law-of-one-price analysis.
- Liquidity/adverse-selection conditioning with richer quote or order-book data.

## Unit of analysis
The confirmatory unit of analysis is **contract × forecast horizon bucket**, not trade.

A contract can contribute at most one representative price snapshot per horizon bucket. This avoids allowing large markets, highly active markets, or large traders to dominate the calibration estimate.

Recommended initial horizon grid:

```text
30d, 14d, 7d, 3d, 1d, 6h, 1h, close
```

Include an observation only if the contract was unresolved at the forecast timestamp and has a valid pre-horizon price within a predefined tolerance window.

## Market-level snapshot construction
For each resolved binary contract and each eligible horizon bucket:

1. Determine the forecast timestamp implied by the resolution time minus the horizon.
2. Select a representative pre-horizon probability from available data.
3. Prefer a trailing-window VWAP or volume-weighted effective transaction price over a single last trade when quote history is unavailable.
4. Record price staleness and data source metadata.
5. Never use information observed after the forecast timestamp.
6. If future quote/order-book data becomes available, replace transaction-price proxy with midpoint or executable side-specific quote nearest the horizon cutoff.

## Inclusion criteria
Include contracts only when they satisfy all of the following:

- Resolved binary contract.
- Valid resolution outcome.
- Valid resolution timestamp.
- At least one usable pre-resolution price observation.
- Enough activity to construct a credible contract-horizon snapshot.
- Non-ambiguous timestamp fields after normalization.

## Exclusion criteria
Exclude or quarantine:

- Voided, canceled, delisted, or ambiguous-resolution markets.
- Contracts with inconsistent timestamps.
- Contracts whose representative pre-horizon price is too stale under the configured tolerance.
- Markets with rules that make binary resolution ambiguous.
- Data rows that require future information to classify or feature-engineer.

For mutually exclusive multi-contract event families, include contracts individually but cluster inference by event family because outcomes are dependent.

## Core features
Minimum feature set:

- Raw probability `p`.
- Clipped/logit probability `logit(p)`.
- Horizon bucket.
- Domain/category.
- Event-family tag.
- Listing month or forecast month.
- Price staleness.
- Cumulative volume to forecast timestamp.
- Cumulative trade count to forecast timestamp.
- Short-run momentum before forecast timestamp.
- Short-run volatility before forecast timestamp.
- Liquidity proxy from public data.

Optional if available:

- YES/NO side asymmetry.
- Maker/taker role information.
- Order-flow imbalance.
- Spread, depth, or book-derived liquidity measures.

## Forecast metrics
Confirmatory metrics:

- Brier score.
- Log loss, with probability clipping documented.
- Calibration intercept.
- Calibration slope.
- Expected calibration error.
- Reliability diagrams.
- Murphy-style reliability / resolution / uncertainty decomposition where feasible.

All models must be evaluated by the same metric functions.

## Recalibration methods
Implement models in a ladder from simple to complex:

1. Raw price baseline.
2. Bin-based reliability correction.
3. Logistic / Platt recalibration on logit price.
4. Beta calibration.
5. Isotonic regression.
6. Hierarchical or partially pooled logistic model with domain and horizon effects.

The hierarchical model is the most promising research model, but simple one-dimensional methods are required baselines.

## Validation design
Use strict time-ordered validation only.

Preferred design:

- Split by forecast date, not by resolution date.
- Use expanding-window or rolling-window walk-forward evaluation.
- Tune hyperparameters only on past data.
- Test only on future forecast windows.
- Prevent event-family leakage across train and test at the same forecast timestamp.
- Do not use random train/test splits in confirmatory analysis.

Example:

```text
train: all eligible forecast snapshots through month t
validation: short block after t, if needed for hyperparameters
test: month or quarter t+1
roll forward and repeat
```

## Edge simulation
Translate each out-of-sample calibrated probability into a conservative expected-value screen.

For a YES entry:

```text
gross_edge = calibrated_probability - effective_yes_price
```

For a NO entry, use directly observed NO-side price when available. Do not assume frictionless complementarity unless the data supports it.

Net edge must subtract:

- Platform fees, versioned by date where possible.
- Spread or half-spread proxy.
- Slippage haircut.
- Liquidity haircut or minimum liquidity threshold.
- Price staleness filter.
- Capital-lockup charge tied to time until resolution.

Only enter hypothetical trades when net edge exceeds a pre-specified threshold and the liquidity/staleness filters pass.

The first version may provide a conservative edge feasibility envelope rather than a precise capacity estimate if full historical quote depth is unavailable.

## Statistical testing
Use inference appropriate for dependent market data:

- Cluster bootstrap by event family or contract family.
- Clustered regressions for calibration intercept/slope tests.
- Diebold-Mariano-style comparisons for scoring losses where appropriate.
- False-discovery-rate correction across domain-horizon slices.
- Report confidence intervals on all core effect sizes.

Do not use iid trade bootstrap for confirmatory market-level results.

## Robustness checks
Minimum robustness checks:

1. Equal-contract weighting vs. trade weighting.
2. Equal-contract weighting vs. equal-event-family weighting.
3. Last-trade snapshot vs. short-window VWAP vs. longer-window VWAP.
4. Excluding low-liquidity markets.
5. Re-estimating with and without sports.
6. Re-estimating with and without mutually exclusive bucket-event families.
7. Stricter fee/slippage assumptions.
8. Stricter stale-price filters.

If an edge result survives only the optimistic backtest, report it as fragile rather than tradable.

## Expected outputs
Publication-style outputs should include:

- Sample-construction flowchart.
- Reliability diagrams by horizon and domain.
- Calibration intercept/slope heatmaps.
- Raw vs. recalibrated score tables with clustered confidence intervals.
- Calibration-gain curves over time.
- Friction-layering figure showing how statistical edge shrinks after fees, slippage, liquidity filters, and capital lockup.
- Cumulative hypothetical PnL under conservative assumptions, clearly labeled as simulated and assumption-dependent.

## Threats to validity
The project must explicitly track and report:

- Look-ahead leakage.
- Same-event-family leakage.
- Stale-price contamination.
- Dependence across event-family contracts.
- Changing fee regimes.
- Incomplete historical quote depth.
- Physical probability vs. risk-neutral market-implied probability distinction.
- Survivorship bias from excluding unresolved or ambiguous contracts.
- Semantic ambiguity in event-family grouping.

## Reproducibility standard
The codebase should be a research package, not a notebook collection.

Required practices:

- Immutable `data/raw/`.
- Pinned Python environment using `uv.lock` or equivalent.
- Deterministic random seeds where relevant.
- Data manifests with file hashes.
- Config-driven runs.
- A run registry that logs git commit, config hash, data snapshot, start/end time, and output paths.
- Programmatically generated tables and figures.
- CI-ready tests for schema, leakage, metrics, and backtest invariants.

## Definition of done for the first publishable version
The first complete version is done when it can:

1. Build a clean contract-horizon panel from public Kalshi data.
2. Evaluate raw market probabilities on the chosen horizon grid.
3. Run strict walk-forward recalibration with at least logistic, isotonic, and beta baselines.
4. Compare raw vs. recalibrated forecasts using Brier score, log loss, slope/intercept, ECE, and reliability diagrams.
5. Apply conservative fee/slippage/liquidity/staleness assumptions to convert probability improvements into edge estimates.
6. Produce manuscript-ready tables and figures from saved result objects.
7. Pass tests for schema validity, no look-ahead leakage, split integrity, metric correctness, and edge-simulation invariants.
