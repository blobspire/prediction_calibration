"""Create SVG visualizations for raw baseline forecast metrics."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.plots.raw_baseline import build_raw_baseline_plots, load_raw_baseline_plot_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/figures.yaml"),
        help="YAML figure config.",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help="Raw baseline artifact directory override.",
    )
    parser.add_argument(
        "--figure-dir",
        type=Path,
        default=None,
        help="Output figure directory override.",
    )
    args = parser.parse_args()

    config = load_raw_baseline_plot_config(args.config)
    config = replace(
        config,
        artifact_dir=args.artifact_dir or config.artifact_dir,
        figure_dir=args.figure_dir or config.figure_dir,
    )
    summary = build_raw_baseline_plots(config)
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
