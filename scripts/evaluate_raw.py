"""Evaluate raw Kalshi probabilities with baseline forecast metrics."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.metrics.evaluation import evaluate_raw_panel, load_metrics_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/metrics.yaml"),
        help="YAML raw metric evaluation config.",
    )
    parser.add_argument("--panel", type=Path, default=None, help="Input modeling panel override.")
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help="Output artifact directory override.",
    )
    parser.add_argument(
        "--limit-rows",
        type=int,
        default=None,
        help="Optional smoke-evaluation row limit.",
    )
    args = parser.parse_args()

    config = load_metrics_config(args.config)
    config = replace(
        config,
        panel_path=args.panel or config.panel_path,
        artifact_dir=args.artifact_dir or config.artifact_dir,
        limit_rows=args.limit_rows if args.limit_rows is not None else config.limit_rows,
    )
    summary = evaluate_raw_panel(config)
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
