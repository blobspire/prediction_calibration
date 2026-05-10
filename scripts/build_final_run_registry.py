"""Build the Phase 17 final run registry and readiness audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.reports.final_readiness import (
    FinalReadinessError,
    build_final_readiness,
    load_final_run_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/final_run.yaml"),
        help="YAML final run registry config.",
    )
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help="Write manifests and readiness docs without running configured checks.",
    )
    args = parser.parse_args()

    try:
        config = load_final_run_config(args.config)
        summary = build_final_readiness(
            config,
            run_checks=not args.skip_checks,
            invoked_command=tuple(sys.argv),
        )
    except FinalReadinessError as exc:
        print(f"final readiness error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
