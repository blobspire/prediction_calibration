"""Build forecast-time walk-forward split assignments."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.validation.splits import build_walkforward_splits, load_validation_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/validation.yaml"),
        help="YAML walk-forward validation config.",
    )
    parser.add_argument("--panel", type=Path, default=None, help="Input panel override.")
    parser.add_argument("--splits", type=Path, default=None, help="Output split parquet override.")
    parser.add_argument(
        "--integrity",
        type=Path,
        default=None,
        help="Output split integrity parquet override.",
    )
    parser.add_argument("--summary", type=Path, default=None, help="Output summary JSON override.")
    parser.add_argument(
        "--limit-rows",
        type=int,
        default=None,
        help="Optional smoke-build row limit.",
    )
    args = parser.parse_args()

    config = load_validation_config(args.config)
    config = replace(
        config,
        panel_path=args.panel or config.panel_path,
        splits_path=args.splits or config.splits_path,
        integrity_path=args.integrity or config.integrity_path,
        summary_path=args.summary or config.summary_path,
        limit_rows=args.limit_rows if args.limit_rows is not None else config.limit_rows,
    )
    summary = build_walkforward_splits(config)
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
