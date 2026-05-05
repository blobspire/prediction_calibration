"""Read-only inspection utilities for raw Kalshi source files."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from predmkt.io.manifest import FileManifest, build_file_manifest
from predmkt.io.schema import RAW_KALSHI_SCHEMAS, SchemaValidationResult, validate_columns

SUPPORTED_COLUMN_SUFFIXES = frozenset({".csv", ".tsv", ".json", ".jsonl", ".parquet"})


@dataclass(frozen=True)
class RawFileInspection:
    """Read-only inspection result for one raw file."""

    manifest: FileManifest
    columns: tuple[str, ...]
    format: str
    schema_results: tuple[SchemaValidationResult, ...]
    error: str | None = None


def iter_raw_files(raw_path: Path) -> tuple[Path, ...]:
    """Return raw files below a path in deterministic order."""

    if raw_path.is_file():
        return (raw_path,)
    if not raw_path.exists():
        return ()
    return tuple(sorted(path for path in raw_path.rglob("*") if path.is_file()))


def inspect_raw_path(raw_path: Path) -> tuple[RawFileInspection, ...]:
    """Inspect raw file columns and hashes without writing outputs."""

    return tuple(inspect_raw_file(path) for path in iter_raw_files(raw_path))


def inspect_raw_file(path: Path) -> RawFileInspection:
    """Inspect one raw file without mutating it."""

    manifest = build_file_manifest(path)
    try:
        columns = read_columns(path)
    except ValueError as exc:
        columns = ()
        error = str(exc)
    else:
        error = None

    schema_results = tuple(validate_columns(columns, schema) for schema in RAW_KALSHI_SCHEMAS)
    return RawFileInspection(
        manifest=manifest,
        columns=columns,
        format=path.suffix.lower().lstrip(".") or "unknown",
        schema_results=schema_results,
        error=error,
    )


def read_columns(path: Path) -> tuple[str, ...]:
    """Read column names from a supported delimited or JSON source file."""

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _read_delimited_columns(path, delimiter=",")
    if suffix == ".tsv":
        return _read_delimited_columns(path, delimiter="\t")
    if suffix == ".jsonl":
        return _read_jsonl_columns(path)
    if suffix == ".json":
        return _read_json_columns(path)
    if suffix == ".parquet":
        return _read_parquet_columns(path)
    raise ValueError(f"unsupported file extension: {suffix or '<none>'}")


def _read_delimited_columns(path: Path, delimiter: str) -> tuple[str, ...]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("file is empty") from exc
    return tuple(column.strip() for column in header if column.strip())


def _read_jsonl_columns(path: Path) -> tuple[str, ...]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            value = json.loads(line)
            return _columns_from_json_value(value)
    raise ValueError("file is empty")


def _read_json_columns(path: Path) -> tuple[str, ...]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    return _columns_from_json_value(value)


def _columns_from_json_value(value: Any) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(str(key) for key in value.keys())
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return tuple(str(key) for key in value[0].keys())
    raise ValueError("JSON file must contain an object or a list of objects")


def _read_parquet_columns(path: Path) -> tuple[str, ...]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ValueError("parquet inspection requires pyarrow") from exc
    return tuple(pq.read_schema(path).names)
