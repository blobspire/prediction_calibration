"""Build canonical quote observations from Becker Kalshi market snapshots."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pyarrow.dataset as ds
import yaml  # type: ignore[import-untyped]

QUOTE_COLUMNS = (
    "ticker",
    "yes_bid",
    "yes_ask",
    "no_bid",
    "no_ask",
    "_fetched_at",
)


@dataclass(frozen=True)
class QuoteObservationConfig:
    """Configuration for building Kalshi quote observations."""

    markets_dir: Path
    output_path: Path
    exclusion_summary_path: Path
    summary_path: Path
    quote_source: str
    fetched_at_timezone: str
    limit_rows: int | None = None
    config_path: Path | None = None
    config_sha256: str | None = None


@dataclass(frozen=True)
class QuoteObservationSummary:
    """Summary metadata for quote-observation construction."""

    markets_dir: str
    output_path: str
    exclusion_summary_path: str
    raw_row_count: int
    output_row_count: int
    excluded_row_count: int
    exclusion_counts: dict[str, int]
    quote_source: str
    fetched_at_timezone: str
    depth_available: bool
    config_sha256: str | None
    git_commit: str | None
    git_dirty: bool | None
    limitations: list[str]


class QuoteObservationError(ValueError):
    """Raised when quote-observation inputs are invalid."""


def load_quote_observation_config(path: Path) -> QuoteObservationConfig:
    """Load quote-observation build settings from YAML."""

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"quote config must be a mapping: {path}")
    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    quotes = _mapping(raw, "quotes")
    return QuoteObservationConfig(
        markets_dir=Path(_required(inputs, "markets_dir")),
        output_path=Path(_required(outputs, "quote_observations_path")),
        exclusion_summary_path=Path(_required(outputs, "exclusion_summary_path")),
        summary_path=Path(_required(outputs, "summary_path")),
        quote_source=str(quotes.get("quote_source", "becker_market_snapshot")),
        fetched_at_timezone=str(quotes.get("fetched_at_timezone", "UTC")),
        limit_rows=_optional_int(quotes.get("limit_rows")),
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def build_quote_observations(config: QuoteObservationConfig) -> QuoteObservationSummary:
    """Normalize raw Kalshi market bid/ask snapshots into quote observations."""

    _validate_config(config)
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    config.exclusion_summary_path.parent.mkdir(parents=True, exist_ok=True)
    config.summary_path.parent.mkdir(parents=True, exist_ok=True)

    raw = _read_market_quotes(config)
    raw_row_count = int(len(raw))
    if config.limit_rows is not None:
        raw = raw.head(config.limit_rows).copy()
    normalized = _normalize_quotes(raw, config)
    reasons = _exclusion_reasons(normalized)
    valid = reasons == ""
    output = normalized.loc[valid, _output_columns()].copy()
    exclusions = _exclusion_counts(reasons)

    output.to_parquet(config.output_path, index=False)
    _write_exclusion_summary(
        config.exclusion_summary_path,
        exclusions,
        raw_rows=len(normalized),
        output_rows=len(output),
    )

    git_commit, git_dirty = _git_state()
    summary = QuoteObservationSummary(
        markets_dir=str(config.markets_dir),
        output_path=str(config.output_path),
        exclusion_summary_path=str(config.exclusion_summary_path),
        raw_row_count=raw_row_count,
        output_row_count=int(len(output)),
        excluded_row_count=int(len(normalized) - len(output)),
        exclusion_counts=exclusions,
        quote_source=config.quote_source,
        fetched_at_timezone=config.fetched_at_timezone,
        depth_available=False,
        config_sha256=config.config_sha256,
        git_commit=git_commit,
        git_dirty=git_dirty,
        limitations=[
            "Quote observations come from Becker market-snapshot bid/ask fields.",
            "_fetched_at is treated as a UTC quote-snapshot timestamp.",
            "The public Becker Kalshi market snapshots do not include order-book depth.",
            "Quote snapshots are not modified in data/raw; this builder writes only "
            "derived interim artifacts.",
        ],
    )
    config.summary_path.write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return summary


def _read_market_quotes(config: QuoteObservationConfig) -> pd.DataFrame:
    if not config.markets_dir.exists():
        raise QuoteObservationError(f"markets_dir does not exist: {config.markets_dir}")
    table = ds.dataset(str(config.markets_dir), format="parquet").to_table(  # type: ignore[no-untyped-call]
        columns=list(QUOTE_COLUMNS)
    )
    return table.to_pandas()


def _normalize_quotes(
    raw: pd.DataFrame,
    config: QuoteObservationConfig,
) -> pd.DataFrame:
    missing = sorted(set(QUOTE_COLUMNS) - set(raw.columns))
    if missing:
        raise QuoteObservationError(f"raw market quote table missing columns: {missing}")
    frame = raw.copy()
    frame["contract_id"] = frame["ticker"].astype("string")
    frame["quote_ts"] = pd.to_datetime(
        frame["_fetched_at"],
        utc=config.fetched_at_timezone.upper() == "UTC",
        errors="coerce",
    )
    if config.fetched_at_timezone.upper() != "UTC":
        raise QuoteObservationError("only fetched_at_timezone=UTC is currently supported")
    for side in ("yes_bid", "yes_ask", "no_bid", "no_ask"):
        frame[f"{side}_cents"] = pd.to_numeric(frame[side], errors="coerce")
        frame[side] = frame[f"{side}_cents"] / 100.0
    frame["quote_source"] = config.quote_source
    frame["depth_available"] = False
    return frame


def _exclusion_reasons(frame: pd.DataFrame) -> pd.Series:
    reasons = pd.Series("", index=frame.index, dtype="object")
    reasons = _append_reason(
        reasons,
        frame["contract_id"].isna() | (frame["contract_id"].astype(str).str.len() == 0),
        "missing_contract_id",
    )
    reasons = _append_reason(reasons, frame["quote_ts"].isna(), "missing_quote_ts")
    for side in ("yes_bid", "yes_ask", "no_bid", "no_ask"):
        cents = frame[f"{side}_cents"]
        reasons = _append_reason(
            reasons,
            cents.isna() | ~cents.between(0, 100),
            f"invalid_{side}",
        )
    reasons = _append_reason(
        reasons,
        frame["yes_bid_cents"] > frame["yes_ask_cents"],
        "yes_bid_above_ask",
    )
    reasons = _append_reason(
        reasons,
        frame["no_bid_cents"] > frame["no_ask_cents"],
        "no_bid_above_ask",
    )
    return reasons


def _append_reason(reasons: pd.Series, mask: pd.Series, reason: str) -> pd.Series:
    updated = reasons.copy()
    mask = mask.fillna(True)
    updated.loc[mask & (updated == "")] = reason
    updated.loc[mask & (updated != reason) & (updated != "")] += f";{reason}"
    return updated


def _exclusion_counts(reasons: pd.Series) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in reasons[reasons != ""]:
        first_reason = str(value).split(";")[0]
        counts[first_reason] = counts.get(first_reason, 0) + 1
    return counts


def _write_exclusion_summary(
    path: Path,
    counts: dict[str, int],
    *,
    raw_rows: int,
    output_rows: int,
) -> None:
    rows = [
        {"reason": reason, "count": count}
        for reason, count in sorted(counts.items())
    ]
    rows.append({"reason": "raw_rows", "count": raw_rows})
    rows.append({"reason": "output_rows", "count": output_rows})
    pd.DataFrame(rows).to_parquet(path, index=False)


def _output_columns() -> list[str]:
    return [
        "contract_id",
        "quote_ts",
        "yes_bid",
        "yes_ask",
        "no_bid",
        "no_ask",
        "yes_bid_cents",
        "yes_ask_cents",
        "no_bid_cents",
        "no_ask_cents",
        "quote_source",
        "depth_available",
    ]


def _validate_config(config: QuoteObservationConfig) -> None:
    if config.limit_rows is not None and config.limit_rows <= 0:
        raise QuoteObservationError("limit_rows must be positive when provided")
    if config.fetched_at_timezone.upper() != "UTC":
        raise QuoteObservationError("only fetched_at_timezone=UTC is currently supported")


def _git_state() -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return commit, bool(status.strip())
    except (OSError, subprocess.CalledProcessError):
        return None, None


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"quote config missing mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"quote config missing required key: {key}")
    return raw[key]


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, (str, int)):
        raise ValueError(f"expected integer value or null, got {value!r}")
    return int(value)
