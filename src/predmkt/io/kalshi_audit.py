"""Read-only audit helpers for Becker Kalshi Parquet data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from predmkt.io.inspection import read_columns
from predmkt.io.schema import TableSchema, validate_columns


@dataclass(frozen=True)
class SchemaGroup:
    """A unique column layout observed across one raw table directory."""

    columns: tuple[str, ...]
    file_count: int
    example_path: Path


@dataclass(frozen=True)
class DirectorySchemaAudit:
    """Read-only schema audit for one directory of raw files."""

    path: Path
    file_count: int
    schema_groups: tuple[SchemaGroup, ...]
    unreadable_files: tuple[tuple[Path, str], ...]


def audit_directory_schemas(path: Path, pattern: str = "*.parquet") -> DirectorySchemaAudit:
    """Read column metadata for all matching files below a directory.

    This intentionally does not hash file contents. Use `inspect_raw_schema.py` on specific files
    when reproducibility hashes are needed.
    """

    files = tuple(sorted(path.glob(pattern)))
    groups: dict[tuple[str, ...], list[Path]] = {}
    unreadable: list[tuple[Path, str]] = []

    for file_path in files:
        try:
            columns = read_columns(file_path)
        except ValueError as exc:
            unreadable.append((file_path, str(exc)))
            continue
        groups.setdefault(columns, []).append(file_path)

    schema_groups = tuple(
        SchemaGroup(columns=columns, file_count=len(paths), example_path=paths[0])
        for columns, paths in sorted(groups.items(), key=lambda item: str(item[1][0]))
    )
    return DirectorySchemaAudit(
        path=path,
        file_count=len(files),
        schema_groups=schema_groups,
        unreadable_files=tuple(unreadable),
    )


def count_rows(path: Path, pattern: str = "*.parquet") -> int:
    """Count rows across a Parquet directory without materializing columns."""

    try:
        import pyarrow.dataset as ds
    except ImportError as exc:
        raise ValueError("row counting requires pyarrow") from exc
    return int(ds.dataset(str(path), format="parquet").count_rows())


def schema_ok_for_all(audit: DirectorySchemaAudit, schema: TableSchema) -> bool:
    """Return whether every readable unique schema satisfies the requested table schema."""

    return all(validate_columns(group.columns, schema).ok for group in audit.schema_groups)

