# Configs

YAML configuration files will define data paths, sampling rules, model settings, validation windows, edge-simulation assumptions, and figure outputs.

Keep methodological assumptions explicit here rather than hidden in notebooks or scripts.

Current configs:

- `sampling.yaml`: contract-horizon snapshot inputs, outputs, horizon grid, stale-price tolerance, VWAP window, and snapshot method preference.
- `taxonomy.yaml`: conservative taxonomy enrichment inputs, outputs, event-family proxy, explicit event-id mapping rules, and unknown-domain defaults.
