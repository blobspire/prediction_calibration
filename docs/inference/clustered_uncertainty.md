# Clustered Uncertainty Methodology

Phase 13 computes uncertainty from saved walk-forward prediction artifacts. It
does not refit recalibrators, rebuild snapshots, or mutate `data/raw/`.

## Confirmatory Unit

Point estimates remain equal-contract over `contract_id x horizon_name`
prediction rows. Trade counts and volume are not used as confirmatory weights.

## Bootstrap Unit

Confirmatory intervals resample `event_family_id` clusters. This reflects
dependence among contracts that belong to the same audited event family. The
current family field combines Phase 12 regex grouping where available with
explicit `event_id` or `contract_id` fallbacks, so domain/family-level claims
still require coverage and ambiguity review.

IID row, iid trade, and trade-weighted bootstraps are not allowed for
confirmatory inference.

## Intervals And Tests

The inference script writes:

- score intervals for Brier score, log loss, and ECE;
- paired model-vs-raw score differences on identical test row IDs;
- calibration intercept and slope intervals;
- Benjamini-Hochberg q-values for paired score comparisons;
- paired-loss diagnostics by event-family cluster.

Brier and log-loss intervals are cluster bootstrap averages. ECE intervals
bootstrap event-family cluster bin counts. Calibration intercept/slope intervals
use an event-family cluster influence bootstrap around the saved prediction
rows; degenerate or sparse groups are marked with explicit statuses and null CI
bounds.

## Sparse Groups

Groups below configured `min_rows` or `min_clusters` are retained in the output
with `too_few_rows` or `too_few_clusters`. They are not silently dropped.

## FDR Family

The default multiple-comparison adjustment applies Benjamini-Hochberg FDR across
saved paired score-difference rows. The configured alpha is recorded in
`configs/inference.yaml` and `data/artifacts/inference/summary.json`.

## Limitations

Clustered uncertainty does not make simulated edge screens executable trading
evidence. It also does not resolve remaining taxonomy ambiguity, quote-depth
limitations, or the absence of observed executable bid/ask history.
