# Final Data Semantics Audit

Overall status: **PASS**.

This Phase 11 audit inspects saved artifacts only. It does not rebuild data, refit models, or alter methodology.

## Key Semantic Findings

- `resolution_ts` is the normalized timestamp used by downstream panels.
- Cleaned interim contracts retain raw `close_time` separately from normalized `resolution_ts`; downstream snapshot/modeling/prediction artifacts are audited for the same retained field.
- Domain/category taxonomy is rule-based and audited, but low-confidence title, ambiguous, and unknown assignments remain non-confirmatory.
- `event_family_id` uses audited regex grouping where available and explicit event_id/contract_id fallbacks elsewhere; Phase 13 inference resamples these event-family clusters.
- Phase 14 adds binned reliability correction and an experimental `hierarchical_eb` empirical-Bayes additive recalibrator.
- Murphy decomposition is reported from fixed-width bins, with binning residuals retained rather than treated as exact Brier identities.
- Phase 16 audits edge executability explicitly. Edge outputs remain simulated expected-value screens, not executable trading profits, because quote snapshots lack order-book depth and capacity is assumption-dependent.

## Phase Status

| phase | status | pass_count | partial_count | fail_count |
| --- | --- | --- | --- | --- |
| artifact_inventory | PASS | 38 | 0 | 0 |
| phase_10 | PASS | 2 | 0 | 0 |
| phase_13 | PASS | 4 | 0 | 0 |
| phase_14 | PASS | 6 | 0 | 0 |
| phase_15 | PASS | 4 | 0 | 0 |
| phase_16 | PASS | 4 | 0 | 0 |
| phase_1_2 | PASS | 1 | 0 | 0 |
| phase_2 | PASS | 3 | 0 | 0 |
| phase_3 | PASS | 7 | 0 | 0 |
| phase_4 | PASS | 2 | 0 | 0 |
| phase_4_5 | PASS | 4 | 0 | 0 |
| phase_5 | PASS | 3 | 0 | 0 |
| phase_7 | PASS | 8 | 0 | 0 |
| phase_8 | PASS | 4 | 0 | 0 |
| phase_9 | PASS | 3 | 0 | 0 |
| phase_9_13 | PASS | 2 | 0 | 0 |
| phase_9_14 | PASS | 2 | 0 | 0 |
| taxonomy | PASS | 5 | 0 | 0 |

## Partial Checks

No partial checks.

## Failed Checks

No failed checks.

## Source Config

- Config path: `configs/final_audit.yaml`
- Config SHA256: `c3f441969a26b21b46d247271246da8ea3457fc6b1289f134aa9d0458130f8a3`
