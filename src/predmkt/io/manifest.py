"""Read-only raw-data manifest helpers."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class FileManifest:
    """Reproducibility metadata for one raw file."""

    path: Path
    size_bytes: int
    sha256: str


def hash_file(path: Path) -> str:
    """Return a SHA-256 digest without modifying the file."""

    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_file_manifest(path: Path) -> FileManifest:
    """Build a manifest row for one file."""

    return FileManifest(path=path, size_bytes=path.stat().st_size, sha256=hash_file(path))

