"""Contract-horizon snapshot construction from cleaned interim Kalshi tables."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import yaml


@dataclass(frozen=True)
class HorizonSpec:
    """A forecast horizon bucket."""

    name: str
    duration: timedelta


@dataclass(frozen=True)
class SnapshotBuildConfig:
    """Configuration for building a contract-horizon snapshot panel."""

    contracts_path: Path
    price_observations_path: Path
    output_path: Path
    summary_path: Path
    horizons: tuple[HorizonSpec, ...]
    max_staleness: timedelta
    vwap_window: timedelta
    snapshot_methods: tuple[str, ...] = ("vwap", "last_trade")
    limit_contracts: int | None = None
    config_path: Path | None = None
    config_sha256: str | None = None


@dataclass(frozen=True)
class SnapshotBuildSummary:
    """Summary of a snapshot panel build."""

    output_path: str
    summary_path: str
    row_count: int
    horizon_counts: dict[str, int]
    snapshot_method_counts: dict[str, int]
    candidate_count: int
    dropped_no_price_count: int
    dropped_stale_count: int
    duplicate_key_validation: dict[str, int | bool]
    no_lookahead_validation: dict[str, int | bool]
    contracts_path: str
    price_observations_path: str
    horizons: dict[str, int]
    max_staleness_seconds: int
    vwap_window_seconds: int
    snapshot_methods: list[str]
    limit_contracts: int | None
    effective_config: dict[str, Any]
    assumptions: dict[str, str]


class SnapshotValidationError(ValueError):
    """Raised when a snapshot panel violates construction invariants."""


DEFAULT_HORIZONS = (
    HorizonSpec("30d", timedelta(days=30)),
    HorizonSpec("14d", timedelta(days=14)),
    HorizonSpec("7d", timedelta(days=7)),
    HorizonSpec("3d", timedelta(days=3)),
    HorizonSpec("1d", timedelta(days=1)),
    HorizonSpec("6h", timedelta(hours=6)),
    HorizonSpec("1h", timedelta(hours=1)),
    HorizonSpec("close", timedelta(minutes=1)),
)

DEFAULT_HORIZON_NAMES = ",".join(horizon.name for horizon in DEFAULT_HORIZONS)

REQUIRED_SNAPSHOT_COLUMNS = (
    "contract_id",
    "event_id",
    "outcome",
    "observed_outcome",
    "horizon_bucket",
    "horizon_timedelta_seconds",
    "forecast_ts",
    "resolution_ts",
    "snapshot_price",
    "snapshot_method",
    "price_timestamp",
    "staleness_seconds",
    "last_trade_ts",
    "max_source_ts",
    "vwap_volume",
    "vwap_trade_count",
)


def parse_duration(value: str) -> timedelta:
    """Parse a small duration string such as `7d`, `6h`, `30m`, or `close`."""

    if value.strip().lower() == "close":
        return timedelta(minutes=1)

    match = re.fullmatch(r"\s*(\d+)\s*([dhm])\s*", value)
    if match is None:
        raise ValueError(f"unsupported duration: {value!r}")
    amount = int(match.group(1))
    unit = match.group(2)
    if amount <= 0:
        raise ValueError("duration must be positive")
    if unit == "d":
        return timedelta(days=amount)
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(minutes=amount)


def parse_horizons(value: str) -> tuple[HorizonSpec, ...]:
    """Parse a comma-separated horizon list."""

    horizons = tuple(
        HorizonSpec(part.strip(), parse_duration(part.strip()))
        for part in value.split(",")
        if part.strip()
    )
    if not horizons:
        raise ValueError("at least one horizon is required")
    return horizons


def load_snapshot_config(path: Path) -> SnapshotBuildConfig:
    """Load a snapshot build config from YAML."""

    import hashlib

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"snapshot config must be a mapping: {path}")

    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    sampling = _mapping(raw, "sampling")

    horizons_value = sampling.get("horizons", DEFAULT_HORIZON_NAMES)
    if isinstance(horizons_value, str):
        horizons = parse_horizons(horizons_value)
    elif isinstance(horizons_value, list):
        horizons = parse_horizons(",".join(str(item) for item in horizons_value))
    else:
        raise ValueError("sampling.horizons must be a comma-separated string or list")

    close_definition = str(sampling.get("close_horizon_definition", ""))
    if any(horizon.name == "close" for horizon in horizons) and "1 minute" not in close_definition:
        raise ValueError("sampling.close_horizon_definition must document `close` as 1 minute")

    snapshot_methods = tuple(
        str(item) for item in sampling.get("snapshot_methods", ("vwap", "last_trade"))
    )
    _validate_snapshot_methods(snapshot_methods)

    return SnapshotBuildConfig(
        contracts_path=Path(_required(inputs, "contracts_path")),
        price_observations_path=Path(_required(inputs, "price_observations_path")),
        output_path=Path(_required(outputs, "panel_path")),
        summary_path=Path(_required(outputs, "summary_path")),
        horizons=horizons,
        max_staleness=parse_duration(str(_required(sampling, "max_staleness"))),
        vwap_window=parse_duration(str(_required(sampling, "vwap_window"))),
        snapshot_methods=snapshot_methods,
        limit_contracts=_optional_int(sampling.get("limit_contracts")),
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def build_snapshot_panel(config: SnapshotBuildConfig) -> SnapshotBuildSummary:
    """Build a one-row-per-contract-horizon snapshot panel."""

    _validate_snapshot_methods(config.snapshot_methods)
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    config.summary_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    try:
        _configure_connection(con)
        _create_horizons(con, config.horizons, config.max_staleness, config.vwap_window)
        _create_candidates(con, config)
        _create_latest_pre_forecast(con, config)
        _create_last_trade(con, config)
        _create_vwap(con, config)
        _create_panel(con, config)
        validation_counts = _validate_panel_sql(con)
        con.execute(f"COPY panel TO {_sql_string(config.output_path)} (FORMAT PARQUET)")
        summary = _build_summary(con, config, validation_counts)
    finally:
        con.close()

    config.summary_path.write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def validate_snapshot_panel(table: pa.Table) -> None:
    """Validate no-look-ahead and one-row-per-contract-horizon invariants."""

    missing = [column for column in REQUIRED_SNAPSHOT_COLUMNS if column not in table.column_names]
    if missing:
        raise SnapshotValidationError(f"snapshot panel missing required columns: {missing}")

    if table.num_rows == 0:
        return
    forecast_before_resolution = pc.less(table["forecast_ts"], table["resolution_ts"])
    if _false_count(forecast_before_resolution):
        raise SnapshotValidationError("snapshot rows must satisfy forecast_ts < resolution_ts")

    last_trade_ok = pc.less_equal(table["last_trade_ts"], table["forecast_ts"])
    if _false_count(last_trade_ok):
        raise SnapshotValidationError("last_trade_ts must be at or before forecast_ts")

    max_source = table["max_source_ts"]
    source_ok = pc.or_(pc.is_null(max_source), pc.less_equal(max_source, table["forecast_ts"]))
    if _false_count(source_ok):
        raise SnapshotValidationError("max_source_ts must be at or before forecast_ts")

    price_timestamp_ok = pc.less_equal(table["price_timestamp"], table["forecast_ts"])
    if _false_count(price_timestamp_ok):
        raise SnapshotValidationError("price_timestamp must be at or before forecast_ts")

    keys = list(
        zip(table["contract_id"].to_pylist(), table["horizon_bucket"].to_pylist(), strict=False)
    )
    if len(keys) != len(set(keys)):
        raise SnapshotValidationError(
            "snapshot panel has duplicate contract_id x horizon_bucket rows"
        )


def _configure_connection(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("PRAGMA threads=4")


def _create_horizons(
    con: duckdb.DuckDBPyConnection,
    horizons: Iterable[HorizonSpec],
    max_staleness: timedelta,
    vwap_window: timedelta,
) -> None:
    values = ", ".join(
        "("
        f"{_sql_string(horizon.name)}, "
        f"{int(horizon.duration.total_seconds())}, "
        f"INTERVAL {int(horizon.duration.total_seconds())} SECOND, "
        f"INTERVAL {int(max_staleness.total_seconds())} SECOND, "
        f"INTERVAL {int(vwap_window.total_seconds())} SECOND"
        ")"
        for horizon in horizons
    )
    con.execute(
        "CREATE TEMP TABLE horizons("
        "horizon_bucket, horizon_timedelta_seconds, horizon_interval, "
        "max_staleness_interval, vwap_window_interval"
        f") AS SELECT * FROM (VALUES {values})"
    )


def _create_candidates(con: duckdb.DuckDBPyConnection, config: SnapshotBuildConfig) -> None:
    contracts_sql = f"read_parquet({_sql_string(config.contracts_path)})"
    if config.limit_contracts is not None:
        if config.limit_contracts <= 0:
            raise ValueError("limit_contracts must be positive when provided")
        contracts_sql = (
            f"(SELECT * FROM {contracts_sql} ORDER BY contract_id LIMIT {config.limit_contracts})"
        )
    con.execute(
        f"""
        CREATE TEMP TABLE candidates AS
        SELECT
            c.contract_id,
            c.event_id,
            c.outcome,
            c.resolution_ts,
            h.horizon_bucket,
            h.horizon_timedelta_seconds,
            h.horizon_interval,
            h.max_staleness_interval,
            h.vwap_window_interval,
            c.resolution_ts - h.horizon_interval AS forecast_ts
        FROM {contracts_sql} AS c
        CROSS JOIN horizons AS h
        WHERE c.resolution_ts - h.horizon_interval < c.resolution_ts
        """
    )


def _create_latest_pre_forecast(
    con: duckdb.DuckDBPyConnection,
    config: SnapshotBuildConfig,
) -> None:
    prices_sql = f"read_parquet({_sql_string(config.price_observations_path)})"
    con.execute(
        f"""
        CREATE TEMP TABLE latest_pre_forecast AS
        SELECT
            contract_id,
            horizon_bucket,
            source_ts,
            yes_price,
            yes_price_cents,
            volume
        FROM (
            SELECT
                c.contract_id,
                c.horizon_bucket,
                c.forecast_ts,
                p.source_ts,
                p.yes_price,
                p.yes_price_cents,
                p.volume,
                row_number() OVER (
                    PARTITION BY c.contract_id, c.horizon_bucket
                    ORDER BY p.source_ts DESC, p.trade_id DESC
                ) AS rn
            FROM candidates AS c
            JOIN {prices_sql} AS p
              ON p.contract_id = c.contract_id
             AND p.source_ts <= c.forecast_ts
        )
        WHERE rn = 1
        """
    )


def _create_last_trade(con: duckdb.DuckDBPyConnection, config: SnapshotBuildConfig) -> None:
    con.execute(
        """
        CREATE TEMP TABLE last_trade AS
        SELECT
            c.contract_id,
            c.horizon_bucket,
            p.source_ts AS last_trade_ts,
            p.yes_price AS last_trade_price,
            p.yes_price_cents AS last_trade_price_cents,
            p.volume AS last_trade_volume,
            date_diff('second', p.source_ts, c.forecast_ts) AS last_trade_staleness_seconds
        FROM candidates AS c
        JOIN latest_pre_forecast AS p
          ON p.contract_id = c.contract_id
         AND p.horizon_bucket = c.horizon_bucket
         AND p.source_ts >= c.forecast_ts - c.max_staleness_interval
        """
    )


def _create_vwap(con: duckdb.DuckDBPyConnection, config: SnapshotBuildConfig) -> None:
    prices_sql = f"read_parquet({_sql_string(config.price_observations_path)})"
    con.execute(
        f"""
        CREATE TEMP TABLE vwap AS
        SELECT
            c.contract_id,
            c.horizon_bucket,
            sum(p.yes_price * p.volume) / nullif(sum(p.volume), 0) AS vwap_price,
            sum(p.yes_price_cents * p.volume) / nullif(sum(p.volume), 0) AS vwap_price_cents,
            count(*) AS vwap_trade_count,
            sum(p.volume) AS vwap_volume,
            max(p.source_ts) AS max_source_ts
        FROM candidates AS c
        JOIN {prices_sql} AS p
          ON p.contract_id = c.contract_id
         AND p.source_ts <= c.forecast_ts
         AND p.source_ts >= c.forecast_ts - c.vwap_window_interval
        GROUP BY c.contract_id, c.horizon_bucket
        """
    )


def _create_panel(con: duckdb.DuckDBPyConnection, config: SnapshotBuildConfig) -> None:
    prefer_vwap = config.snapshot_methods[0] == "vwap"
    snapshot_price = (
        "CASE WHEN v.vwap_trade_count IS NOT NULL THEN v.vwap_price "
        "ELSE lt.last_trade_price END"
    )
    snapshot_price_cents = (
        "CASE WHEN v.vwap_trade_count IS NOT NULL THEN v.vwap_price_cents "
        "ELSE lt.last_trade_price_cents END"
    )
    snapshot_method = "CASE WHEN v.vwap_trade_count IS NOT NULL THEN 'vwap' ELSE 'last_trade' END"
    price_timestamp = (
        "CASE WHEN v.vwap_trade_count IS NOT NULL THEN v.max_source_ts "
        "ELSE lt.last_trade_ts END"
    )
    if not prefer_vwap:
        snapshot_price = "lt.last_trade_price"
        snapshot_price_cents = "lt.last_trade_price_cents"
        snapshot_method = "'last_trade'"
        price_timestamp = "lt.last_trade_ts"

    con.execute(
        f"""
        CREATE TEMP TABLE panel AS
        SELECT
            c.contract_id,
            c.event_id,
            c.outcome,
            CASE WHEN c.outcome = 'yes' THEN 1 WHEN c.outcome = 'no' THEN 0 ELSE NULL END
                AS observed_outcome,
            c.horizon_bucket,
            c.horizon_timedelta_seconds,
            c.forecast_ts,
            c.resolution_ts,
            lt.last_trade_price,
            lt.last_trade_price_cents,
            lt.last_trade_ts,
            lt.last_trade_volume,
            lt.last_trade_staleness_seconds,
            v.vwap_price,
            v.vwap_price_cents,
            v.vwap_trade_count,
            v.vwap_volume,
            v.max_source_ts,
            {snapshot_price} AS snapshot_price,
            {snapshot_price_cents} AS snapshot_price_cents,
            {snapshot_method} AS snapshot_method,
            {price_timestamp} AS price_timestamp,
            date_diff('second', {price_timestamp}, c.forecast_ts) AS staleness_seconds
        FROM candidates AS c
        JOIN last_trade AS lt
          ON lt.contract_id = c.contract_id
         AND lt.horizon_bucket = c.horizon_bucket
        LEFT JOIN vwap AS v
          ON v.contract_id = c.contract_id
         AND v.horizon_bucket = c.horizon_bucket
        """
    )


def _validate_panel_sql(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, int | bool]]:
    violations = con.execute(
        """
        SELECT
            sum(CASE WHEN forecast_ts >= resolution_ts THEN 1 ELSE 0 END) AS bad_forecast_order,
            sum(CASE WHEN last_trade_ts > forecast_ts THEN 1 ELSE 0 END) AS bad_last_trade,
            sum(CASE
                WHEN max_source_ts IS NOT NULL AND max_source_ts > forecast_ts THEN 1
                ELSE 0
            END)
                AS bad_vwap_source,
            sum(CASE WHEN price_timestamp > forecast_ts THEN 1 ELSE 0 END) AS bad_price_timestamp,
            count(*) - count(DISTINCT contract_id || '|' || horizon_bucket) AS duplicate_rows
        FROM panel
        """
    ).fetchone()
    names = (
        "bad_forecast_order",
        "bad_last_trade",
        "bad_vwap_source",
        "bad_price_timestamp",
        "duplicate_rows",
    )
    values = violations or (0, 0, 0, 0, 0)
    counts = {name: int(value or 0) for name, value in zip(names, values, strict=True)}
    failing = {name: int(value or 0) for name, value in zip(names, values, strict=True)}
    failing = {name: value for name, value in failing.items() if value}
    if failing:
        raise SnapshotValidationError(f"snapshot panel invariant violations: {failing}")
    return {
        "duplicate_key_validation": {
            "duplicate_rows": counts["duplicate_rows"],
            "passed": counts["duplicate_rows"] == 0,
        },
        "no_lookahead_validation": {
            "bad_forecast_order": counts["bad_forecast_order"],
            "bad_last_trade": counts["bad_last_trade"],
            "bad_vwap_source": counts["bad_vwap_source"],
            "bad_price_timestamp": counts["bad_price_timestamp"],
            "passed": all(
                counts[name] == 0
                for name in (
                    "bad_forecast_order",
                    "bad_last_trade",
                    "bad_vwap_source",
                    "bad_price_timestamp",
                )
            ),
        },
    }


def _build_summary(
    con: duckdb.DuckDBPyConnection,
    config: SnapshotBuildConfig,
    validation_counts: dict[str, dict[str, int | bool]],
) -> SnapshotBuildSummary:
    row_count = int(con.execute("SELECT count(*) FROM panel").fetchone()[0])
    candidate_count = int(con.execute("SELECT count(*) FROM candidates").fetchone()[0])
    stale_counts = con.execute(
        """
        SELECT
            sum(CASE WHEN p.contract_id IS NULL THEN 1 ELSE 0 END) AS no_price,
            sum(CASE
                WHEN p.contract_id IS NOT NULL
                 AND p.source_ts < c.forecast_ts - c.max_staleness_interval
                THEN 1 ELSE 0
            END) AS stale
        FROM candidates AS c
        LEFT JOIN latest_pre_forecast AS p
          ON p.contract_id = c.contract_id
         AND p.horizon_bucket = c.horizon_bucket
        """
    ).fetchone()
    horizon_counts = {
        str(row[0]): int(row[1])
        for row in con.execute(
            "SELECT horizon_bucket, count(*) FROM panel GROUP BY 1 ORDER BY 1"
        ).fetchall()
    }
    snapshot_method_counts = {
        str(row[0]): int(row[1])
        for row in con.execute(
            "SELECT snapshot_method, count(*) FROM panel GROUP BY 1 ORDER BY 1"
        ).fetchall()
    }
    return SnapshotBuildSummary(
        output_path=str(config.output_path),
        summary_path=str(config.summary_path),
        row_count=row_count,
        horizon_counts=horizon_counts,
        snapshot_method_counts=snapshot_method_counts,
        candidate_count=candidate_count,
        dropped_no_price_count=int(stale_counts[0] or 0),
        dropped_stale_count=int(stale_counts[1] or 0),
        duplicate_key_validation=validation_counts["duplicate_key_validation"],
        no_lookahead_validation=validation_counts["no_lookahead_validation"],
        contracts_path=str(config.contracts_path),
        price_observations_path=str(config.price_observations_path),
        horizons={
            horizon.name: int(horizon.duration.total_seconds()) for horizon in config.horizons
        },
        max_staleness_seconds=int(config.max_staleness.total_seconds()),
        vwap_window_seconds=int(config.vwap_window.total_seconds()),
        snapshot_methods=list(config.snapshot_methods),
        limit_contracts=config.limit_contracts,
        effective_config=_effective_config(config),
        assumptions={
            "unit_of_analysis": "one row per contract_id x horizon_bucket",
            "forecast_timestamp": "resolution_ts - horizon",
            "lookahead_rule": "all source observations must satisfy source_ts <= forecast_ts",
            "last_trade": (
                "nearest cleaned price observation at or before forecast_ts "
                "within max_staleness"
            ),
            "vwap": (
                "volume-weighted average over cleaned observations in "
                "[forecast_ts - vwap_window, forecast_ts]"
            ),
            "primary_snapshot_price": "short-window VWAP when available, otherwise last trade",
            "close_horizon": (
                "`close` is one minute before resolution_ts to preserve "
                "forecast_ts < resolution_ts"
            ),
        },
    )


def _effective_config(config: SnapshotBuildConfig) -> dict[str, Any]:
    return {
        "inputs": {
            "contracts_path": str(config.contracts_path),
            "price_observations_path": str(config.price_observations_path),
        },
        "outputs": {
            "panel_path": str(config.output_path),
            "summary_path": str(config.summary_path),
        },
        "sampling": {
            "horizons": [horizon.name for horizon in config.horizons],
            "horizon_seconds": {
                horizon.name: int(horizon.duration.total_seconds()) for horizon in config.horizons
            },
            "close_horizon_definition": "close = resolution_ts - 1 minute",
            "max_staleness": _format_duration(config.max_staleness),
            "max_staleness_seconds": int(config.max_staleness.total_seconds()),
            "vwap_window": _format_duration(config.vwap_window),
            "vwap_window_seconds": int(config.vwap_window.total_seconds()),
            "snapshot_methods": list(config.snapshot_methods),
            "limit_contracts": config.limit_contracts,
        },
        "config_path": str(config.config_path) if config.config_path else None,
        "config_sha256": config.config_sha256,
    }


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"snapshot config missing mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"snapshot config missing required key: {key}")
    return raw[key]


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _validate_snapshot_methods(methods: tuple[str, ...]) -> None:
    supported = {"vwap", "last_trade"}
    if not methods:
        raise ValueError("at least one snapshot method is required")
    unknown = [method for method in methods if method not in supported]
    if unknown:
        raise ValueError(f"unsupported snapshot methods: {unknown}")
    if "last_trade" not in methods:
        raise ValueError("last_trade must be present as the fallback snapshot method")


def _format_duration(value: timedelta) -> str:
    seconds = int(value.total_seconds())
    if seconds % 86_400 == 0:
        return f"{seconds // 86_400}d"
    if seconds % 3_600 == 0:
        return f"{seconds // 3_600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def _sql_string(path_or_value: Path | str) -> str:
    return "'" + str(path_or_value).replace("'", "''") + "'"


def _false_count(mask: pa.ChunkedArray | pa.Array) -> int:
    inverted = pc.invert(mask)
    return int(pc.sum(pc.cast(inverted, pa.int64())).as_py() or 0)
