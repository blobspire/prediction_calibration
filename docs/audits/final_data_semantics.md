# Final Data Semantics Audit

Overall status: **PARTIAL**.

This Phase 11 audit inspects saved artifacts only. It does not rebuild data, refit models, or alter methodology.

## Key Semantic Findings

- `resolution_ts` is the normalized timestamp used by downstream panels.
- Cleaned interim contracts currently do not retain a separate raw `close_time` column, so the resolution/close-time mapping remains a documented semantic limitation.
- Domain/category taxonomy is rule-based and audited, but low-confidence title, ambiguous, and unknown assignments remain non-confirmatory.
- `event_family_id` uses audited regex grouping where available and explicit event_id/contract_id fallbacks elsewhere; Phase 13 inference resamples these event-family clusters.
- Phase 14 adds binned reliability correction and an experimental `hierarchical_eb` empirical-Bayes additive recalibrator.
- Murphy decomposition is reported from fixed-width bins, with binning residuals retained rather than treated as exact Brier identities.
- Edge outputs remain simulated expected-value screens, not executable trading profits.

## Phase Status

| phase | status | pass_count | partial_count | fail_count |
| --- | --- | --- | --- | --- |
| artifact_inventory | PASS | 33 | 0 | 0 |
| phase_10 | PASS | 2 | 0 | 0 |
| phase_13 | PASS | 4 | 0 | 0 |
| phase_14 | PASS | 6 | 0 | 0 |
| phase_1_2 | PASS | 1 | 0 | 0 |
| phase_2 | PARTIAL | 2 | 1 | 0 |
| phase_3 | PASS | 6 | 0 | 0 |
| phase_4 | PASS | 2 | 0 | 0 |
| phase_4_5 | PASS | 3 | 0 | 0 |
| phase_5 | PASS | 3 | 0 | 0 |
| phase_7 | PARTIAL | 6 | 1 | 0 |
| phase_8 | PARTIAL | 4 | 1 | 0 |
| phase_9 | PASS | 3 | 0 | 0 |
| phase_9_13 | PASS | 2 | 0 | 0 |
| phase_9_14 | PASS | 2 | 0 | 0 |
| taxonomy | PASS | 5 | 0 | 0 |

## Partial Checks

| phase | check_id | message |
| --- | --- | --- |
| phase_2 | close_time_not_retained | cleaned contracts do not retain raw close_time separately; resolution_ts is the audited downstream timestamp and remains a semantic limitation |
| phase_7 | event_family_policy_report_only | event-family overlaps are reported, not filtered; Phase 13 clusters uncertainty by event family but does not exclude overlaps |
| phase_8 | edge_executability_limitations | edge remains a simulated screen using transaction-price proxies and assumed frictions |

## Failed Checks

No failed checks.

## Source Config

- Config path: `configs/final_audit.yaml`
- Config SHA256: `46eedb00550c3fdca14fc3e449332441db3ca9436101bea84267d4a6b00e67b3`
