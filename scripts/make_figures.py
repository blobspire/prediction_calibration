"""Create manuscript-ready figures from saved result artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.plots.manuscript import make_manuscript_figures
from predmkt.reports.manuscript import ReportingError, load_reporting_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/reporting.yaml"),
        help="YAML manuscript reporting config.",
    )
    parser.add_argument("--walkforward-dir", type=Path, default=None)
    parser.add_argument("--edge-dir", type=Path, default=None)
    parser.add_argument("--raw-baseline-dir", type=Path, default=None)
    parser.add_argument("--inference-dir", type=Path, default=None)
    parser.add_argument("--figure-dir", type=Path, default=None)
    parser.add_argument(
        "--artifact-run-label",
        type=str,
        default=None,
        help="Override reporting artifact_run_label, e.g. smoke for draft artifacts.",
    )
    args = parser.parse_args()

    config = load_reporting_config(args.config)
    config = replace(
        config,
        raw_baseline_artifact_dir=args.raw_baseline_dir or config.raw_baseline_artifact_dir,
        walkforward_artifact_dir=args.walkforward_dir or config.walkforward_artifact_dir,
        edge_artifact_dir=args.edge_dir or config.edge_artifact_dir,
        inference_artifact_dir=args.inference_dir or config.inference_artifact_dir,
        figure_dir=args.figure_dir or config.figure_dir,
        artifact_run_label=args.artifact_run_label or config.artifact_run_label,
    )
    try:
        summary = make_manuscript_figures(config)
    except ReportingError as exc:
        print(f"reporting error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
