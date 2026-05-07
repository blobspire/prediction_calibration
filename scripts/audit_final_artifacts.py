"""Audit full saved artifacts and data semantics for Phase 11."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.reports.final_audit import build_final_audit, load_final_audit_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/final_audit.yaml"),
        help="YAML final-audit config.",
    )
    parser.add_argument("--audit-dir", type=Path, default=None, help="Audit output override.")
    parser.add_argument(
        "--semantics-doc",
        type=Path,
        default=None,
        help="Markdown data-semantics report override.",
    )
    args = parser.parse_args()

    config = load_final_audit_config(args.config)
    config = replace(
        config,
        audit_dir=args.audit_dir or config.audit_dir,
        semantics_doc_path=args.semantics_doc or config.semantics_doc_path,
    )
    summary = build_final_audit(config)
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True, default=str))
    return 2 if summary.overall_status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
