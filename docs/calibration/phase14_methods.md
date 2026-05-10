# Phase 14 Calibration Methods And Murphy Decomposition

Phase 14 expands the saved walk-forward calibration ladder without changing the
scientific unit of analysis. All models are evaluated on the same
`contract_id x horizon_name` test rows produced by the forecast-time
walk-forward splitter.

## Binned Reliability Correction

`binned_reliability` is a fixed-width reliability-bin recalibrator. It assigns
each input probability to a configured probability bin, estimates the empirical
outcome rate in that bin, and smooths sparse bins toward the global outcome
rate using the configured prior strength.

The default config enables monotone pool-adjacent-violators smoothing across bin
estimates. Empty bins use the global outcome rate before monotone smoothing.
The fitted artifact records bin counts, sparse-bin counts, bin values, prior
strength, and monotonicity status.

## Experimental Hierarchical EB

`hierarchical_eb` is an experimental empirical-Bayes additive logit
recalibrator. It first fits the same global Platt model used by the `platt`
baseline, then estimates shrunk additive offsets for configured context columns,
currently `horizon_name` and `domain`.

Sparse levels below `hierarchical_min_group_rows` receive a zero offset. Unseen
levels at prediction time also fall back to zero offset. This keeps predictions
bounded and reproducible, but it is not a full Bayesian mixed-effects model.
Domain-level claims remain conditional on taxonomy confidence, ambiguity, and
manual review.

## Context Interface

All calibrators retain a common `fit` / `predict_proba` interface. Context-free
calibrators ignore optional context through `fit_with_context` and
`predict_proba_with_context`. Context-aware calibrators declare required context
columns through `requires_context`; the walk-forward evaluator fails clearly if
those columns are absent from the modeling panel.

## Murphy Decomposition

`scripts/evaluate_decomposition.py --config configs/decomposition.yaml` reads
saved out-of-sample predictions only. It writes:

- `data/artifacts/decomposition/murphy_decomposition.parquet`
- `data/artifacts/decomposition/murphy_bins.parquet`
- `data/artifacts/decomposition/summary.json`

The decomposition reports reliability, resolution, uncertainty, decomposed
Brier, raw Brier, and `binning_residual = raw_brier - decomposed_brier`.

Because fixed-width bins can contain varied probabilities, the binned Murphy
components should not be described as an exact identity unless the residual is
negligible for the reported slice. The residual is retained in all tables.

## Phase 14 Scope Limits

Phase 14 does not add new external ML dependencies, does not refit models inside
reporting code, does not alter snapshots, and does not upgrade edge outputs into
executable trading evidence. Edge screens remain simulated and
assumption-dependent.
