"""Evaluate Murphy-style Brier decomposition from saved predictions."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.metrics.decomposition import evaluate_decomposition, load_decomposition_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/decomposition.yaml"),
        help="YAML Murphy decomposition config.",
    )
    parser.add_argument(
        "--predictions",
        type=Path,
        default=None,
        help="Walk-forward prediction artifact override.",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help="Output artifact directory override.",
    )
    args = parser.parse_args()

    config = load_decomposition_config(args.config)
    config = replace(
        config,
        predictions_path=args.predictions or config.predictions_path,
        artifact_dir=args.artifact_dir or config.artifact_dir,
    )
    summary = evaluate_decomposition(config)
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
