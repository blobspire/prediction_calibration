from datetime import UTC

import pytest

from predmkt.io.timestamps import parse_timestamp_utc


def test_parse_timestamp_utc_accepts_z_suffix() -> None:
    parsed = parse_timestamp_utc("2024-01-02T03:04:05Z")

    assert parsed.tzinfo == UTC
    assert parsed.isoformat() == "2024-01-02T03:04:05+00:00"


def test_parse_timestamp_utc_converts_offsets_to_utc() -> None:
    parsed = parse_timestamp_utc("2024-01-02T03:04:05-05:00")

    assert parsed.isoformat() == "2024-01-02T08:04:05+00:00"


def test_parse_timestamp_utc_accepts_epoch_milliseconds() -> None:
    parsed = parse_timestamp_utc(1_704_164_645_000)

    assert parsed.isoformat() == "2024-01-02T03:04:05+00:00"


def test_parse_timestamp_utc_rejects_naive_strings() -> None:
    with pytest.raises(ValueError, match="explicit timezone"):
        parse_timestamp_utc("2024-01-02T03:04:05")
