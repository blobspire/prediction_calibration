"""Build canonical Kalshi quote observations from Becker market snapshots."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.io.kalshi_quotes import (  # noqa: E402
    QuoteObservationError,
    build_quote_observations,
    load_quote_observation_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/quotes.yaml"),
        help="YAML quote-observation config.",
    )
    parser.add_argument("--markets-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--limit-rows", type=int, default=None)
    args = parser.parse_args()

    config = load_quote_observation_config(args.config)
    config = replace(
        config,
        markets_dir=args.markets_dir or config.markets_dir,
        output_path=args.output or config.output_path,
        summary_path=args.summary or config.summary_path,
        limit_rows=args.limit_rows if args.limit_rows is not None else config.limit_rows,
    )
    if args.output is not None:
        config = replace(
            config,
            exclusion_summary_path=args.output.with_name(
                f"{args.output.stem}_exclusion_summary.parquet"
            ),
        )
    try:
        summary = build_quote_observations(config)
    except QuoteObservationError as exc:
        print(f"quote observation error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
