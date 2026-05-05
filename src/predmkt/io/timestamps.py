"""Timestamp parsing utilities for source-data inspection and cleaning."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

_MILLISECONDS_THRESHOLD: Final[int] = 10_000_000_000


def parse_timestamp_utc(value: object) -> datetime:
    """Parse an explicitly time-zoned timestamp into UTC.

    Naive datetime strings are rejected because the source timezone must be explicit before
    a row can enter confirmatory analysis.
    """

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, int | float):
        epoch_value = float(value)
        epoch_seconds = (
            epoch_value / 1000 if abs(epoch_value) >= _MILLISECONDS_THRESHOLD else epoch_value
        )
        parsed = datetime.fromtimestamp(epoch_seconds, tz=UTC)
    elif isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise ValueError("timestamp is empty")
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        parsed = datetime.fromisoformat(normalized)
    else:
        raise TypeError(f"unsupported timestamp type: {type(value).__name__}")

    if parsed.tzinfo is None:
        raise ValueError("timestamp must include an explicit timezone")
    return parsed.astimezone(UTC)
