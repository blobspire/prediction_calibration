"""Build a taxonomy-enriched contract-horizon panel."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.taxonomy.kalshi import build_taxonomy_panel, load_taxonomy_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/taxonomy.yaml"),
        help="YAML taxonomy config.",
    )
    parser.add_argument(
        "--panel",
        type=Path,
        default=None,
        help="Input snapshot panel parquet. Overrides config when provided.",
    )
    parser.add_argument(
        "--contracts",
        type=Path,
        default=None,
        help="Cleaned interim contracts parquet. Overrides config when provided.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output taxonomy-enriched panel parquet. Overrides config when provided.",
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=None,
        help="Output taxonomy audit parquet. Overrides config when provided.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="Output taxonomy summary JSON. Overrides config when provided.",
    )
    args = parser.parse_args()

    config = load_taxonomy_config(args.config)
    config = replace(
        config,
        panel_path=args.panel or config.panel_path,
        contracts_path=args.contracts or config.contracts_path,
        output_panel_path=args.output or config.output_panel_path,
        audit_path=args.audit or config.audit_path,
        summary_path=args.summary or config.summary_path,
    )
    summary = build_taxonomy_panel(config)
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
