"""Build a contract-horizon snapshot panel from cleaned interim Kalshi data."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.sampling.snapshots import (
    DEFAULT_HORIZON_NAMES,
    SnapshotBuildConfig,
    build_snapshot_panel,
    load_snapshot_config,
    parse_duration,
    parse_horizons,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="YAML sampling config. Primary workflow: configs/sampling.yaml.",
    )
    parser.add_argument(
        "--contracts",
        type=Path,
        default=None,
        help="Cleaned interim contracts parquet. Overrides config when provided.",
    )
    parser.add_argument(
        "--price-observations",
        type=Path,
        default=None,
        help="Cleaned interim price observations parquet. Overrides config when provided.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output processed panel parquet. Overrides config when provided.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="Output build summary JSON. Overrides config when provided.",
    )
    parser.add_argument(
        "--horizons",
        default=None,
        help="Comma-separated horizons such as `30d,14d,7d,3d,1d,6h,1h,close`. Overrides config.",
    )
    parser.add_argument(
        "--max-staleness",
        default=None,
        help="Maximum age for last-trade snapshots. Overrides config when provided.",
    )
    parser.add_argument(
        "--vwap-window",
        default=None,
        help="Trailing window for VWAP snapshots. Overrides config when provided.",
    )
    parser.add_argument(
        "--snapshot-methods",
        default=None,
        help=(
            "Comma-separated snapshot method preference, e.g. `vwap,last_trade`. "
            "Overrides config."
        ),
    )
    parser.add_argument(
        "--limit-contracts",
        type=int,
        default=None,
        help="Optional deterministic contract limit for smoke builds.",
    )
    args = parser.parse_args()

    if args.config is not None:
        config = load_snapshot_config(args.config)
    else:
        config = SnapshotBuildConfig(
            contracts_path=Path("data/interim/kalshi/contracts.parquet"),
            price_observations_path=Path("data/interim/kalshi/price_observations.parquet"),
            output_path=Path("data/processed/contract_horizon_panel.parquet"),
            summary_path=Path("data/processed/contract_horizon_panel_summary.json"),
            horizons=parse_horizons(DEFAULT_HORIZON_NAMES),
            max_staleness=parse_duration("7d"),
            vwap_window=parse_duration("6h"),
        )

    config = replace(
        config,
        contracts_path=args.contracts or config.contracts_path,
        price_observations_path=args.price_observations or config.price_observations_path,
        output_path=args.output or config.output_path,
        summary_path=args.summary or config.summary_path,
        horizons=parse_horizons(args.horizons) if args.horizons else config.horizons,
        max_staleness=parse_duration(args.max_staleness)
        if args.max_staleness
        else config.max_staleness,
        vwap_window=parse_duration(args.vwap_window) if args.vwap_window else config.vwap_window,
        snapshot_methods=tuple(part.strip() for part in args.snapshot_methods.split(","))
        if args.snapshot_methods
        else config.snapshot_methods,
        limit_contracts=(
            args.limit_contracts if args.limit_contracts is not None else config.limit_contracts
        ),
    )
    summary = build_snapshot_panel(config)
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
