"""Build a Kalshi modeling feature panel from processed snapshot data."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.features.kalshi import build_feature_panel, load_feature_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/features.yaml"),
        help="YAML feature build config.",
    )
    parser.add_argument("--panel", type=Path, default=None, help="Input taxonomy panel override.")
    parser.add_argument(
        "--price-observations",
        type=Path,
        default=None,
        help="Input cleaned price observations override.",
    )
    parser.add_argument("--contracts", type=Path, default=None, help="Input contracts override.")
    parser.add_argument("--output", type=Path, default=None, help="Output feature panel override.")
    parser.add_argument("--summary", type=Path, default=None, help="Output summary JSON override.")
    parser.add_argument(
        "--limit-rows",
        type=int,
        default=None,
        help="Optional smoke-build row limit.",
    )
    args = parser.parse_args()

    config = load_feature_config(args.config)
    config = replace(
        config,
        panel_path=args.panel or config.panel_path,
        price_observations_path=args.price_observations or config.price_observations_path,
        contracts_path=args.contracts or config.contracts_path,
        output_path=args.output or config.output_path,
        summary_path=args.summary or config.summary_path,
        limit_rows=args.limit_rows if args.limit_rows is not None else config.limit_rows,
    )
    summary = build_feature_panel(config)
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
