# Final Data Semantics Audit

Overall status: **PARTIAL**.

This Phase 11 audit inspects saved artifacts only. It does not rebuild data, refit models, or alter methodology.

## Key Semantic Findings

- `resolution_ts` is the normalized timestamp used by downstream panels.
- Cleaned interim contracts currently do not retain a separate raw `close_time` column, so the resolution/close-time mapping remains a documented semantic limitation.
- Domain/category taxonomy remains non-confirmatory while values are all or mostly `unknown`.
- `event_family_id` remains a conservative proxy until Phase 12 hardens taxonomy.
- Edge outputs remain simulated expected-value screens, not executable trading profits.

## Phase Status

| phase | status | pass_count | partial_count | fail_count |
| --- | --- | --- | --- | --- |
| artifact_inventory | PASS | 24 | 0 | 0 |
| phase_10 | PASS | 2 | 0 | 0 |
| phase_1_2 | PASS | 1 | 0 | 0 |
| phase_2 | PARTIAL | 2 | 1 | 0 |
| phase_3 | PASS | 6 | 0 | 0 |
| phase_4 | PASS | 2 | 0 | 0 |
| phase_4_5 | PASS | 3 | 0 | 0 |
| phase_5 | PASS | 3 | 0 | 0 |
| phase_7 | PARTIAL | 6 | 1 | 0 |
| phase_8 | PARTIAL | 4 | 1 | 0 |
| phase_9 | PASS | 3 | 0 | 0 |
| taxonomy | PARTIAL | 0 | 2 | 0 |

## Partial Checks

| phase | check_id | message |
| --- | --- | --- |
| phase_2 | close_time_not_retained | cleaned contracts do not retain raw close_time separately; resolution_ts is the audited downstream timestamp and remains a semantic limitation |
| taxonomy | domain_category_coverage | domain/category are all unknown and cannot support domain-level final claims |
| taxonomy | event_family_proxy | event_family_id is still effectively the inferred event_id proxy |
| phase_7 | event_family_policy_report_only | event-family overlaps are reported, not filtered, because event_family_id is a proxy |
| phase_8 | edge_executability_limitations | edge remains a simulated screen using transaction-price proxies and assumed frictions |

## Failed Checks

No failed checks.

## Source Config

- Config path: `configs/final_audit.yaml`
- Config SHA256: `39c64c8cbaaff1839a0dbfd009366e3403f333c64702046a5cd4a7ed136cb672`
