"""Run conservative fee-aware edge screens on walk-forward predictions."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.edge import load_edge_simulation_config, run_edge_simulation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/backtest.yaml"),
        help="YAML edge-simulation config.",
    )
    parser.add_argument(
        "--predictions",
        type=Path,
        default=None,
        help="Walk-forward predictions override.",
    )
    parser.add_argument("--panel", type=Path, default=None, help="Modeling panel override.")
    parser.add_argument(
        "--quotes",
        type=Path,
        default=None,
        help="Quote-observation artifact override.",
    )
    parser.add_argument(
        "--execution-mode",
        type=str,
        default=None,
        choices=("transaction_proxy", "quote_snapshot_proxy"),
        help="Entry-price mode override.",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help="Output artifact directory override.",
    )
    parser.add_argument("--limit-rows", type=int, default=None, help="Optional row limit.")
    args = parser.parse_args()

    config = load_edge_simulation_config(args.config)
    config = replace(
        config,
        predictions_path=args.predictions or config.predictions_path,
        panel_path=args.panel or config.panel_path,
        quote_observations_path=args.quotes or config.quote_observations_path,
        execution_mode=args.execution_mode or config.execution_mode,
        artifact_dir=args.artifact_dir or config.artifact_dir,
        limit_rows=args.limit_rows if args.limit_rows is not None else config.limit_rows,
    )
    summary = run_edge_simulation(config)
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
