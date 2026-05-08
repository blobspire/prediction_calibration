# Paper

Manuscript figures, tables, appendix outputs, and bibliography files live here.

Generate current manuscript-ready outputs from saved full-run artifacts:

```bash
uv run python scripts/make_figures.py --config configs/reporting.yaml
uv run python scripts/make_tables.py --config configs/reporting.yaml
```

Expected generated directories:

```text
paper/figures/
paper/tables/
```

The reporting scripts consume saved artifacts only. They do not fit
recalibrators, recompute metrics, or rerun edge screens.

Current manuscript figures include sample construction, reliability diagrams,
calibration-slope heatmaps, calibration-gain-over-time curves, score
comparisons, edge-friction sensitivity, simulated PnL, and exploratory domain
reliability. Domain outputs require taxonomy-confidence review before
confirmatory claims.
