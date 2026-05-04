"""Inspect raw Kalshi source-file columns and schema compatibility.

This command is read-only: it computes file hashes and reads headers or first JSON records, but
does not write manifests or modify `data/raw/`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predmkt.io.inspection import RawFileInspection, inspect_raw_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-path",
        type=Path,
        default=Path("data/raw"),
        help="Raw data file or directory to inspect. Defaults to data/raw.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format. Defaults to markdown.",
    )
    args = parser.parse_args()

    inspections = inspect_raw_path(args.raw_path)
    if args.format == "json":
        print(json.dumps([_inspection_to_dict(item) for item in inspections], indent=2, sort_keys=True))
    else:
        print(format_markdown(inspections, args.raw_path))
    return 0


def format_markdown(inspections: tuple[RawFileInspection, ...], raw_path: Path) -> str:
    """Format raw inspections as a human-readable report."""

    lines = [f"# Raw Schema Inspection: `{raw_path}`", ""]
    if not inspections:
        lines.extend(
            [
                "No raw files were found.",
                "",
                "This is expected before data is downloaded or copied into `data/raw/`.",
            ]
        )
        return "\n".join(lines)

    for item in inspections:
        path = item.manifest.path
        lines.extend(
            [
                f"## `{path}`",
                "",
                f"- Size: `{item.manifest.size_bytes}` bytes",
                f"- SHA-256: `{item.manifest.sha256}`",
                f"- Format: `{item.format}`",
            ]
        )
        if item.error is not None:
            lines.append(f"- Column inspection error: `{item.error}`")
        else:
            lines.append(f"- Columns: `{', '.join(item.columns) if item.columns else '<none>'}`")

        for result in item.schema_results:
            missing = ", ".join(result.missing_required) if result.missing_required else "<none>"
            extra = ", ".join(result.extra_columns) if result.extra_columns else "<none>"
            status = "ok" if result.ok else "missing required columns"
            lines.extend(
                [
                    "",
                    f"### Schema `{result.schema_name}`: {status}",
                    "",
                    f"- Missing required: `{missing}`",
                    f"- Extra/unmapped columns: `{extra}`",
                ]
            )
            for field in result.fields:
                accepted = ", ".join(field.accepted_names)
                matched = field.matched_column if field.matched_column is not None else "<missing>"
                required = "required" if field.required else "optional"
                lines.append(f"- `{field.field_name}` ({required}): `{matched}`; accepts `{accepted}`")
        lines.append("")
    return "\n".join(lines).rstrip()


def _inspection_to_dict(item: RawFileInspection) -> dict[str, Any]:
    return {
        "manifest": {
            **asdict(item.manifest),
            "path": str(item.manifest.path),
        },
        "columns": item.columns,
        "format": item.format,
        "error": item.error,
        "schema_results": [
            {
                "schema_name": result.schema_name,
                "columns": result.columns,
                "missing_required": result.missing_required,
                "extra_columns": result.extra_columns,
                "ok": result.ok,
                "fields": [asdict(field) for field in result.fields],
            }
            for result in item.schema_results
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
