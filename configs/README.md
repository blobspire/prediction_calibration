# Configs

YAML configuration files will define data paths, sampling rules, model settings, validation windows, edge-simulation assumptions, and figure outputs.

Keep methodological assumptions explicit here rather than hidden in notebooks or scripts.

Current configs:

- `sampling.yaml`: contract-horizon snapshot inputs, outputs, horizon grid, horizon-specific stale-price tolerances, VWAP windows, and snapshot method preferences.
- `taxonomy.yaml`: Phase 12 taxonomy enrichment inputs, outputs, ordered exact-event/prefix/title rules, regex event-family grouping, ambiguity handling, confidence labels, and unknown defaults.
- `features.yaml`: modeling-panel inputs, outputs, probability clipping epsilon, momentum/volatility windows, liquidity window, and missing-feature policies.
- `metrics.yaml`: raw-probability baseline metrics, log-loss clipping epsilon, reliability bins, calibration fit settings, groupings, and explicit equal-contract primary aggregation.
- `figures.yaml`: raw-baseline diagnostic figure inputs, output directory, horizon order, aggregation mode, PNG/SVG formats, and DPI.
- `raw_baseline_audit.yaml`: diagnostic audit settings for staleness, snapshot-method sensitivity, stricter close/1h variants, balanced panels, orientation checks, and close timestamp semantics.
- `presentation.yaml`: slide-ready raw-baseline presentation figure inputs, output directory, horizon order, formats, DPI, and recorded pre-refinement comparison values.
- `validation.yaml`: forecast-time expanding walk-forward split inputs, outputs, monthly train/validation/test windows, event-family fallback policy, and strict overlap leakage rule.
- `models.yaml`: reusable recalibrator defaults, enabled raw/Platt/beta/isotonic/binned-reliability/experimental hierarchical-EB calibrators, probability/outcome/context columns, prediction clipping epsilon, fit controls, and walk-forward evaluation artifact settings.
- `inference.yaml`: Phase 13 clustered uncertainty inputs, output directory, event-family cluster bootstrap settings, confidence level, FDR settings, groupings, and liquidity/staleness bucket definitions.
- `decomposition.yaml`: Phase 14 Murphy-style Brier decomposition inputs, output directory, probability/outcome/model columns, fixed-width bin settings, sparse-bin threshold, and grouping definitions.
- `backtest.yaml`: conservative taker-only YES-side edge-screen inputs, output directory, Kalshi-style fee proxy, capital-lockup assumption, optional staleness/liquidity filters, and fee/spread/slippage friction tiers.
- `reporting.yaml`: manuscript figure/table artifact inputs, including Phase 13 inference and Phase 14 decomposition artifacts, `paper/` output directories, horizon/model ordering, figure/table formats, metric scope, and explicit full-vs-smoke run label.
- `robustness.yaml`: non-confirmatory robustness diagnostics for snapshot-method slices, liquidity filters, domain-exclusion availability, and friction-assumption sensitivity. Outputs are separate from primary artifacts.
- `replication_small.yaml`: deterministic small-sample paper replication path starting from cleaned interim Kalshi tables and writing under replication-specific processed/artifact/paper directories, including inference and decomposition stages.
- `final_audit.yaml`: Phase 11+ saved-artifact and data-semantics audit inputs, expected horizons/models, Phase 13 inference checks, Phase 14 decomposition and experimental-label checks, hard-fail versus partial severity rules, known partial limitations, and output paths for final audit reports.
