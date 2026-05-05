"""Build cleaned interim Kalshi tables from Becker raw Parquet data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.cleaning.kalshi import KalshiInterimOutputs, build_interim_kalshi
from predmkt.io.kalshi_readers import KalshiRawPaths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-kalshi-path",
        type=Path,
        default=Path("data/raw/becker_prediction_market_analysis/data/kalshi"),
        help="Path containing immutable Becker Kalshi markets/ and trades/ directories.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/interim/kalshi"),
        help="Directory for cleaned interim outputs.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1_000_000,
        help="Trade rows to process per streaming batch.",
    )
    args = parser.parse_args()

    summary = build_interim_kalshi(
        raw_paths=KalshiRawPaths.from_kalshi_root(args.raw_kalshi_path),
        outputs=KalshiInterimOutputs.from_output_dir(args.output_dir),
        batch_size=args.batch_size,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

