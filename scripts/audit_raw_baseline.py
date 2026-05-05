"""Audit raw baseline metric patterns for snapshot artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.reports.raw_baseline_audit import (
    build_raw_baseline_audit,
    load_raw_baseline_audit_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/raw_baseline_audit.yaml"),
        help="YAML raw baseline audit config.",
    )
    parser.add_argument(
        "--modeling-panel",
        type=Path,
        default=None,
        help="Input modeling panel override.",
    )
    parser.add_argument(
        "--price-observations",
        type=Path,
        default=None,
        help="Input cleaned price observations override.",
    )
    parser.add_argument("--audit-dir", type=Path, default=None, help="Output audit directory.")
    args = parser.parse_args()

    config = load_raw_baseline_audit_config(args.config)
    config = replace(
        config,
        modeling_panel_path=args.modeling_panel or config.modeling_panel_path,
        price_observations_path=args.price_observations or config.price_observations_path,
        audit_dir=args.audit_dir or config.audit_dir,
    )
    summary = build_raw_baseline_audit(config)
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
