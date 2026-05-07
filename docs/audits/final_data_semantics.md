# Final Data Semantics Audit

Overall status: **PARTIAL**.

This Phase 11 audit inspects saved artifacts only. It does not rebuild data, refit models, or alter methodology.

## Key Semantic Findings

- `resolution_ts` is the normalized timestamp used by downstream panels.
- Cleaned interim contracts currently do not retain a separate raw `close_time` column, so the resolution/close-time mapping remains a documented semantic limitation.
- Domain/category taxonomy is rule-based and audited, but low-confidence title, ambiguous, and unknown assignments remain non-confirmatory.
- `event_family_id` uses audited regex grouping where available and explicit event_id/contract_id fallbacks elsewhere; clustered inference remains Phase 13.
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
| taxonomy | PASS | 5 | 0 | 0 |

## Partial Checks

| phase | check_id | message |
| --- | --- | --- |
| phase_2 | close_time_not_retained | cleaned contracts do not retain raw close_time separately; resolution_ts is the audited downstream timestamp and remains a semantic limitation |
| phase_7 | event_family_policy_report_only | event-family overlaps are reported, not filtered; clustered handling is Phase 13 |
| phase_8 | edge_executability_limitations | edge remains a simulated screen using transaction-price proxies and assumed frictions |

## Failed Checks

No failed checks.

## Source Config

- Config path: `configs/final_audit.yaml`
- Config SHA256: `5dea6d216155c10d326039156bded10b6efe7454c21c44ead9c654fc2dcb7092`
