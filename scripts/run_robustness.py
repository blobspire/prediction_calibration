"""Run non-confirmatory robustness diagnostics from saved artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.reports.robustness import load_robustness_config, run_robustness


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/robustness.yaml"),
        help="YAML robustness config.",
    )
    parser.add_argument("--panel", type=Path, default=None, help="Modeling panel override.")
    parser.add_argument(
        "--walkforward-dir",
        type=Path,
        default=None,
        help="Walk-forward artifact directory override.",
    )
    parser.add_argument(
        "--edge-dir",
        type=Path,
        default=None,
        help="Edge artifact directory override.",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help="Robustness artifact directory override.",
    )
    parser.add_argument(
        "--table-dir",
        type=Path,
        default=None,
        help="Robustness table directory override.",
    )
    parser.add_argument("--limit-rows", type=int, default=None, help="Optional smoke row limit.")
    parser.add_argument(
        "--skip-snapshot-variants",
        action="store_true",
        help="Skip legacy small-sample alternate snapshot reruns.",
    )
    parser.add_argument(
        "--skip-full-snapshot-variants",
        action="store_true",
        help="Skip Phase 15 full downstream alternate snapshot reruns.",
    )
    parser.add_argument(
        "--variant-limit-contracts",
        type=int,
        default=None,
        help="Optional deterministic contract limit for full snapshot variants.",
    )
    args = parser.parse_args()

    config = load_robustness_config(args.config)
    artifact_dir = args.artifact_dir or config.artifact_dir
    full_variant_output_dir = config.full_snapshot_variant_output_dir
    full_variant_processed_dir = config.full_snapshot_variant_processed_dir
    if args.artifact_dir is not None:
        full_variant_output_dir = artifact_dir / "full_snapshot_variants"
        try:
            relative_artifact_dir = artifact_dir.relative_to(Path("data/artifacts"))
            full_variant_processed_dir = (
                Path("data/processed") / relative_artifact_dir / "full_snapshot_variants"
            )
        except ValueError:
            full_variant_processed_dir = artifact_dir / "processed_full_snapshot_variants"
    config = replace(
        config,
        panel_path=args.panel or config.panel_path,
        walkforward_artifact_dir=args.walkforward_dir or config.walkforward_artifact_dir,
        edge_artifact_dir=args.edge_dir or config.edge_artifact_dir,
        artifact_dir=artifact_dir,
        table_dir=args.table_dir or config.table_dir,
        limit_rows=args.limit_rows if args.limit_rows is not None else config.limit_rows,
        snapshot_variants_enabled=(
            False if args.skip_snapshot_variants else config.snapshot_variants_enabled
        ),
        full_snapshot_variants_enabled=(
            False if args.skip_full_snapshot_variants else config.full_snapshot_variants_enabled
        ),
        full_snapshot_variant_output_dir=full_variant_output_dir,
        full_snapshot_variant_processed_dir=full_variant_processed_dir,
        full_snapshot_variant_limit_contracts=(
            args.variant_limit_contracts
            if args.variant_limit_contracts is not None
            else config.full_snapshot_variant_limit_contracts
        ),
    )
    summary = run_robustness(config)
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
