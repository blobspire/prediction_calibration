| source | limitation |
| --- | --- |
| reporting | Manuscript outputs are generated from saved artifacts only; no model fitting is performed by figure/table code. |
| reporting | Artifact run label: small_sample. |
| raw_baseline | Phase 4 evaluates raw probabilities only; no recalibrators or walk-forward model evaluation are implemented here. |
| raw_baseline | Primary aggregation is equal-contract; trade-weighted metrics are disabled unless explicitly enabled as a robustness output. |
| raw_baseline | Domain/category groups use the audited rule-based taxonomy; title-keyword, ambiguous, and unknown assignments remain exploratory rather than confirmatory domain findings. |
| raw_baseline | Liquidity and staleness groups use public feature-panel proxies, not historical order-book depth or executable quotes. |
| walkforward | Phase 14 includes simple raw/Platt/beta/isotonic, binned reliability, and experimental empirical-Bayes additive recalibrators. |
| walkforward | hierarchical_eb is experimental: it uses horizon/domain additive logit offsets, not a full Bayesian mixed model. |
| walkforward | Fit data uses train+validation rows with labels resolved by each test fold start; rows with later resolutions are excluded from fitting. |
| walkforward | Event-family overlaps are reported but not filtered; Phase 12 family IDs are audited regex/event fallbacks, with clustered inference deferred to Phase 13. |
| walkforward | Metrics are equal-contract over contract-horizon test rows; no trade weighting or edge simulation is implemented here. |
| edge_simulation | Edge outputs are simulated expected-value screens, not executable trading profits or trade recommendations. |
| edge_simulation | The first edge layer is YES-side only; NO trades are not synthesized from 1 minus the YES price. |
| edge_simulation | Entry prices are snapshot-based transaction proxies because historical executable bid/ask quotes and order-book depth are unavailable. |
| edge_simulation | The taker fee is a configurable Kalshi-style proxy, not a versioned audit of exact historical exchange billing. |
| edge_simulation | Spread and slippage tiers are conservative haircuts, not observed execution costs. |
| edge_simulation | Summaries are equal contract-horizon prediction rows and do not use trade weights. |
| inference | Inference consumes saved walk-forward prediction artifacts and does not refit calibrators or rebuild data. |
| inference | Confirmatory intervals resample audited event-family clusters, not iid rows or trades. |
| inference | Point estimates remain equal-contract over contract-horizon prediction rows. |
| inference | Domain/category inference remains conditional on taxonomy confidence, ambiguity, and unknown-rate audits. |
| decomposition | Murphy components use fixed-width probability bins from saved predictions; the Brier identity is approximate when bins contain varied probabilities. |
| decomposition | binning_residual is reported as raw_brier - decomposed_brier and should not be suppressed. |
| decomposition | No models are refit and no feature or snapshot methodology is changed. |
