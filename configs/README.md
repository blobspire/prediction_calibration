# Configs

YAML configuration files will define data paths, sampling rules, model settings, validation windows, edge-simulation assumptions, and figure outputs.

Keep methodological assumptions explicit here rather than hidden in notebooks or scripts.

Current configs:

- `sampling.yaml`: contract-horizon snapshot inputs, outputs, horizon grid, horizon-specific stale-price tolerances, VWAP windows, and snapshot method preferences.
- `taxonomy.yaml`: conservative taxonomy enrichment inputs, outputs, event-family proxy, explicit event-id mapping rules, and unknown-domain defaults.
- `features.yaml`: modeling-panel inputs, outputs, probability clipping epsilon, momentum/volatility windows, liquidity window, and missing-feature policies.
- `metrics.yaml`: raw-probability baseline metrics, log-loss clipping epsilon, reliability bins, calibration fit settings, groupings, and explicit equal-contract primary aggregation.
- `figures.yaml`: raw-baseline diagnostic figure inputs, output directory, horizon order, aggregation mode, PNG/SVG formats, and DPI.
- `raw_baseline_audit.yaml`: diagnostic audit settings for staleness, snapshot-method sensitivity, stricter close/1h variants, balanced panels, orientation checks, and close timestamp semantics.
- `presentation.yaml`: slide-ready raw-baseline presentation figure inputs, output directory, horizon order, formats, DPI, and recorded pre-refinement comparison values.
- `validation.yaml`: forecast-time expanding walk-forward split inputs, outputs, monthly train/validation/test windows, event-family fallback policy, and strict overlap leakage rule.
