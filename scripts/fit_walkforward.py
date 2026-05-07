"""Fit simple recalibrators on past walk-forward folds and score future folds."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.calibration import load_models_config
from predmkt.validation.walkforward import evaluate_walkforward


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/models.yaml"),
        help="YAML model/walk-forward evaluation config.",
    )
    parser.add_argument("--panel", type=Path, default=None, help="Input modeling panel override.")
    parser.add_argument("--splits", type=Path, default=None, help="Input split artifact override.")
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help="Output artifact directory override.",
    )
    parser.add_argument("--limit-folds", type=int, default=None, help="Optional fold limit.")
    parser.add_argument("--limit-rows", type=int, default=None, help="Optional panel row limit.")
    args = parser.parse_args()

    config = load_models_config(args.config)
    config = replace(
        config,
        panel_path=args.panel or config.panel_path,
        splits_path=args.splits or config.splits_path,
        artifact_dir=args.artifact_dir or config.artifact_dir,
        limit_folds=args.limit_folds if args.limit_folds is not None else config.limit_folds,
        limit_rows=args.limit_rows if args.limit_rows is not None else config.limit_rows,
    )
    summary = evaluate_walkforward(config)
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
