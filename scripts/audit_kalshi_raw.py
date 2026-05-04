"""Read-only audit of Becker Kalshi raw Parquet directories."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.io.kalshi_audit import audit_directory_schemas, count_rows, schema_ok_for_all
from predmkt.io.schema import CONTRACTS_SCHEMA, PRICE_OBSERVATIONS_SCHEMA


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kalshi-path",
        type=Path,
        default=Path("data/raw/becker_prediction_market_analysis/data/kalshi"),
        help="Path containing Becker Kalshi markets/ and trades/ directories.",
    )
    args = parser.parse_args()

    markets_path = args.kalshi_path / "markets"
    trades_path = args.kalshi_path / "trades"

    markets_audit = audit_directory_schemas(markets_path)
    trades_audit = audit_directory_schemas(trades_path)

    print(f"# Kalshi Raw Audit: `{args.kalshi_path}`")
    print()
    _print_directory("markets", markets_audit, CONTRACTS_SCHEMA)
    print(f"- Row count: `{count_rows(markets_path)}`")
    print()
    _print_directory("trades", trades_audit, PRICE_OBSERVATIONS_SCHEMA)
    print(f"- Row count: `{count_rows(trades_path)}`")
    return 0


def _print_directory(name: str, audit, schema) -> None:
    print(f"## `{name}`")
    print()
    print(f"- Files: `{audit.file_count}`")
    print(f"- Unique schemas: `{len(audit.schema_groups)}`")
    print(f"- Unreadable files: `{len(audit.unreadable_files)}`")
    print(f"- Satisfies `{schema.name}` schema for all unique schemas: `{schema_ok_for_all(audit, schema)}`")
    for index, group in enumerate(audit.schema_groups, start=1):
        print(f"- Schema {index} file count: `{group.file_count}`")
        print(f"- Schema {index} example: `{group.example_path}`")
        print(f"- Schema {index} columns: `{', '.join(group.columns)}`")


if __name__ == "__main__":
    raise SystemExit(main())

