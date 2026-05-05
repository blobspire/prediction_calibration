"""Create presentation-ready figures from current baseline artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.plots.presentation import (
    build_presentation_figures,
    load_presentation_figure_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/presentation.yaml"),
        help="YAML presentation figure config.",
    )
    parser.add_argument(
        "--figure-dir",
        type=Path,
        default=None,
        help="Output presentation figure directory override.",
    )
    args = parser.parse_args()

    config = load_presentation_figure_config(args.config)
    config = replace(
        config,
        figure_dir=args.figure_dir or config.figure_dir,
    )
    summary = build_presentation_figures(config)
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
