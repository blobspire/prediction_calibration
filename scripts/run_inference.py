"""Run clustered inference on saved walk-forward prediction artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.inference import InferenceError, load_inference_config, run_inference


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/inference.yaml"),
        help="YAML clustered inference config.",
    )
    parser.add_argument("--predictions", type=Path, default=None)
    parser.add_argument("--panel", type=Path, default=None)
    parser.add_argument("--artifact-dir", type=Path, default=None)
    parser.add_argument("--bootstrap-iterations", type=int, default=None)
    parser.add_argument("--random-seed", type=int, default=None)
    args = parser.parse_args()

    config = load_inference_config(args.config)
    config = replace(
        config,
        predictions_path=args.predictions or config.predictions_path,
        panel_path=args.panel or config.panel_path,
        artifact_dir=args.artifact_dir or config.artifact_dir,
        bootstrap_iterations=(
            args.bootstrap_iterations
            if args.bootstrap_iterations is not None
            else config.bootstrap_iterations
        ),
        random_seed=args.random_seed if args.random_seed is not None else config.random_seed,
    )
    try:
        summary = run_inference(config)
    except InferenceError as exc:
        print(f"inference error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
