"""Feature construction for Kalshi contract-horizon modeling panels."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import yaml

from predmkt.sampling.snapshots import parse_duration


@dataclass(frozen=True)
class FeatureBuildConfig:
    """Configuration for building a Kalshi modeling feature panel."""

    panel_path: Path
    price_observations_path: Path
    contracts_path: Path
    output_path: Path
    summary_path: Path
    probability_epsilon: float
    momentum_window: timedelta
    volatility_window: timedelta
    liquidity_window: timedelta
    event_family_source: str
    domain_category_source: str
    missing_domain_category_policy: str
    limit_rows: int | None = None
    config_path: Path | None = None
    config_sha256: str | None = None


@dataclass(frozen=True)
class FeatureBuildSummary:
    """Summary of a feature-panel build."""

    input_panel_path: str
    price_observations_path: str
    contracts_path: str
    output_path: str
    summary_path: str
    input_row_count: int
    output_row_count: int
    feature_windows_seconds: dict[str, int]
    probability_epsilon: float
    missing_feature_counts: dict[str, int]
    inferred_feature_counts: dict[str, int]
    no_lookahead_validation: dict[str, int | bool]
    duplicate_key_validation: dict[str, int | bool]
    effective_config: dict[str, Any]
    limitations: list[str]


class FeatureValidationError(ValueError):
    """Raised when feature-panel invariants fail."""


REQUIRED_FEATURE_COLUMNS = (
    "contract_id",
    "horizon_name",
    "forecast_ts",
    "resolution_ts",
    "raw_probability",
    "clipped_probability",
    "logit_probability",
    "domain",
    "category",
    "event_family_id",
    "forecast_month",
    "price_staleness_seconds",
    "cumulative_volume_to_forecast",
    "cumulative_trade_count_to_forecast",
    "short_run_momentum",
    "short_run_volatility",
    "public_liquidity_proxy",
    "max_feature_source_ts",
)


def load_feature_config(path: Path) -> FeatureBuildConfig:
    """Load feature build configuration from YAML."""

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"feature config must be a mapping: {path}")

    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    features = _mapping(raw, "features")

    epsilon = float(_required(features, "probability_epsilon"))
    if not 0.0 < epsilon < 0.5:
        raise ValueError("features.probability_epsilon must be in (0, 0.5)")

    return FeatureBuildConfig(
        panel_path=Path(_required(inputs, "panel_path")),
        price_observations_path=Path(_required(inputs, "price_observations_path")),
        contracts_path=Path(_required(inputs, "contracts_path")),
        output_path=Path(_required(outputs, "panel_path")),
        summary_path=Path(_required(outputs, "summary_path")),
        probability_epsilon=epsilon,
        momentum_window=parse_duration(str(_required(features, "momentum_window"))),
        volatility_window=parse_duration(str(_required(features, "volatility_window"))),
        liquidity_window=parse_duration(str(_required(features, "liquidity_window"))),
        event_family_source=str(features.get("event_family_source", "taxonomy_event_family_id")),
        domain_category_source=str(features.get("domain_category_source", "taxonomy_fields")),
        missing_domain_category_policy=str(
            features.get("missing_domain_category_policy", "keep_unknown_with_flags")
        ),
        limit_rows=_optional_int(features.get("limit_rows")),
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def build_feature_panel(config: FeatureBuildConfig) -> FeatureBuildSummary:
    """Build a feature panel using only observations at or before forecast_ts."""

    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    config.summary_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    try:
        _configure_connection(con)
        _create_base_panel(con, config)
        _create_cumulative_features(con, config)
        _create_window_features(con, config, "momentum", config.momentum_window)
        _create_window_features(con, config, "volatility", config.volatility_window)
        _create_liquidity_features(con, config)
        _create_feature_panel(con, config)
        validation = _validate_feature_panel_sql(con)
        con.execute(f"COPY feature_panel TO {_sql_string(config.output_path)} (FORMAT PARQUET)")
        summary = _build_summary(con, config, validation)
    finally:
        con.close()

    config.summary_path.write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def validate_feature_panel(table: pa.Table) -> None:
    """Validate no-look-ahead and schema invariants for feature panels."""

    missing = [column for column in REQUIRED_FEATURE_COLUMNS if column not in table.column_names]
    if missing:
        raise FeatureValidationError(f"feature panel missing required columns: {missing}")
    if table.num_rows == 0:
        return

    forecast_before_resolution = pc.less(table["forecast_ts"], table["resolution_ts"])
    if _false_count(forecast_before_resolution):
        raise FeatureValidationError("feature rows must satisfy forecast_ts < resolution_ts")

    feature_source_ok = pc.or_(
        pc.is_null(table["max_feature_source_ts"]),
        pc.less_equal(table["max_feature_source_ts"], table["forecast_ts"]),
    )
    if _false_count(feature_source_ok):
        raise FeatureValidationError("max_feature_source_ts must be at or before forecast_ts")

    price_ts_ok = pc.less_equal(table["price_timestamp"], table["forecast_ts"])
    if _false_count(price_ts_ok):
        raise FeatureValidationError("price_timestamp must be at or before forecast_ts")

    keys = list(
        zip(table["contract_id"].to_pylist(), table["horizon_name"].to_pylist(), strict=False)
    )
    if len(keys) != len(set(keys)):
        raise FeatureValidationError("feature panel has duplicate contract_id x horizon rows")


def _configure_connection(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("PRAGMA threads=4")


def _create_base_panel(con: duckdb.DuckDBPyConnection, config: FeatureBuildConfig) -> None:
    panel_sql = f"read_parquet({_sql_string(config.panel_path)})"
    if config.limit_rows is not None:
        if config.limit_rows <= 0:
            raise ValueError("limit_rows must be positive when provided")
        panel_sql = (
            f"(SELECT * FROM {panel_sql} "
            f"ORDER BY contract_id, horizon_bucket LIMIT {config.limit_rows})"
        )
    con.execute(
        f"""
        CREATE TEMP TABLE base_panel AS
        SELECT
            p.*,
            c.created_ts AS contract_created_ts,
            c.open_ts AS contract_open_ts,
            c.volume AS contract_final_volume,
            c.open_interest AS contract_final_open_interest
        FROM {panel_sql} AS p
        LEFT JOIN read_parquet({_sql_string(config.contracts_path)}) AS c
          ON c.contract_id = p.contract_id
        """
    )


def _create_cumulative_features(
    con: duckdb.DuckDBPyConnection,
    config: FeatureBuildConfig,
) -> None:
    prices_sql = f"read_parquet({_sql_string(config.price_observations_path)})"
    con.execute(
        f"""
        CREATE TEMP TABLE cumulative_features AS
        SELECT
            b.contract_id,
            b.horizon_bucket,
            count(p.trade_id) AS cumulative_trade_count_to_forecast,
            COALESCE(sum(p.volume), 0) AS cumulative_volume_to_forecast,
            max(p.source_ts) AS cumulative_max_source_ts
        FROM base_panel AS b
        LEFT JOIN {prices_sql} AS p
          ON p.contract_id = b.contract_id
         AND p.source_ts <= b.forecast_ts
        GROUP BY b.contract_id, b.horizon_bucket
        """
    )


def _create_window_features(
    con: duckdb.DuckDBPyConnection,
    config: FeatureBuildConfig,
    name: str,
    window: timedelta,
) -> None:
    prices_sql = f"read_parquet({_sql_string(config.price_observations_path)})"
    con.execute(
        f"""
        CREATE TEMP TABLE {name}_features AS
        SELECT
            b.contract_id,
            b.horizon_bucket,
            count(p.trade_id) AS {name}_trade_count,
            first(p.yes_price ORDER BY p.source_ts ASC, p.trade_id ASC) AS {name}_first_price,
            first(p.yes_price ORDER BY p.source_ts DESC, p.trade_id DESC) AS {name}_last_price,
            stddev_samp(p.yes_price) AS {name}_volatility,
            max(p.source_ts) AS {name}_max_source_ts
        FROM base_panel AS b
        LEFT JOIN {prices_sql} AS p
          ON p.contract_id = b.contract_id
         AND p.source_ts <= b.forecast_ts
         AND p.source_ts >= b.forecast_ts - INTERVAL {int(window.total_seconds())} SECOND
        GROUP BY b.contract_id, b.horizon_bucket
        """
    )


def _create_liquidity_features(
    con: duckdb.DuckDBPyConnection,
    config: FeatureBuildConfig,
) -> None:
    prices_sql = f"read_parquet({_sql_string(config.price_observations_path)})"
    con.execute(
        f"""
        CREATE TEMP TABLE liquidity_features AS
        SELECT
            b.contract_id,
            b.horizon_bucket,
            count(p.trade_id) AS liquidity_window_trade_count,
            COALESCE(sum(p.volume), 0) AS liquidity_window_volume,
            max(p.source_ts) AS liquidity_max_source_ts
        FROM base_panel AS b
        LEFT JOIN {prices_sql} AS p
          ON p.contract_id = b.contract_id
         AND p.source_ts <= b.forecast_ts
         AND p.source_ts >= b.forecast_ts
            - INTERVAL {int(config.liquidity_window.total_seconds())} SECOND
        GROUP BY b.contract_id, b.horizon_bucket
        """
    )


def _create_feature_panel(con: duckdb.DuckDBPyConnection, config: FeatureBuildConfig) -> None:
    epsilon = config.probability_epsilon
    con.execute(
        f"""
        CREATE TEMP TABLE feature_panel AS
        SELECT
            b.*,
            b.snapshot_price AS raw_probability,
            least(greatest(b.snapshot_price, {epsilon}), {1.0 - epsilon})
                AS clipped_probability,
            ln(
                least(greatest(b.snapshot_price, {epsilon}), {1.0 - epsilon})
                / (1.0 - least(greatest(b.snapshot_price, {epsilon}), {1.0 - epsilon}))
            ) AS logit_probability,
            b.horizon_bucket AS horizon_name,
            b.horizon_timedelta_seconds AS horizon_timedelta,
            strftime(b.forecast_ts, '%Y-%m') AS forecast_month,
            strftime(b.contract_open_ts, '%Y-%m') AS listing_month,
            b.staleness_seconds AS price_staleness_seconds,
            cf.cumulative_volume_to_forecast,
            cf.cumulative_trade_count_to_forecast,
            CASE
                WHEN mf.momentum_trade_count >= 2
                THEN mf.momentum_last_price - mf.momentum_first_price
                ELSE NULL
            END AS short_run_momentum,
            CASE
                WHEN vf.volatility_trade_count >= 2 THEN vf.volatility_volatility
                ELSE NULL
            END AS short_run_volatility,
            lf.liquidity_window_volume,
            lf.liquidity_window_trade_count,
            ln(1.0 + cf.cumulative_volume_to_forecast) AS public_liquidity_proxy,
            greatest(
                cf.cumulative_max_source_ts,
                mf.momentum_max_source_ts,
                vf.volatility_max_source_ts,
                lf.liquidity_max_source_ts
            ) AS max_feature_source_ts,
            b.snapshot_price IS NULL AS raw_probability_missing,
            b.domain IS NULL OR b.domain = 'unknown' AS domain_missing_or_unknown,
            b.category IS NULL OR b.category = 'unknown' AS category_missing_or_unknown,
            b.taxonomy_source = 'event_id_proxy' AS event_family_id_inferred,
            b.event_family_id IS NULL OR b.event_family_id = '' AS event_family_id_missing,
            b.contract_open_ts IS NULL AS listing_ts_missing,
            mf.momentum_trade_count < 2 AS momentum_missing,
            vf.volatility_trade_count < 2 AS volatility_missing,
            cf.cumulative_trade_count_to_forecast = 0 AS liquidity_missing,
            'snapshot_price' AS raw_probability_source,
            'taxonomy_panel' AS domain_category_source,
            'event_family_id' AS event_family_source
        FROM base_panel AS b
        JOIN cumulative_features AS cf
          ON cf.contract_id = b.contract_id
         AND cf.horizon_bucket = b.horizon_bucket
        JOIN momentum_features AS mf
          ON mf.contract_id = b.contract_id
         AND mf.horizon_bucket = b.horizon_bucket
        JOIN volatility_features AS vf
          ON vf.contract_id = b.contract_id
         AND vf.horizon_bucket = b.horizon_bucket
        JOIN liquidity_features AS lf
          ON lf.contract_id = b.contract_id
         AND lf.horizon_bucket = b.horizon_bucket
        """
    )


def _validate_feature_panel_sql(
    con: duckdb.DuckDBPyConnection,
) -> dict[str, dict[str, int | bool]]:
    violations = con.execute(
        """
        SELECT
            sum(CASE WHEN forecast_ts >= resolution_ts THEN 1 ELSE 0 END)
                AS bad_forecast_order,
            sum(CASE
                WHEN max_feature_source_ts IS NOT NULL AND max_feature_source_ts > forecast_ts
                THEN 1 ELSE 0
            END) AS bad_feature_source,
            sum(CASE WHEN price_timestamp > forecast_ts THEN 1 ELSE 0 END)
                AS bad_price_timestamp,
            count(*) - count(DISTINCT contract_id || '|' || horizon_name) AS duplicate_rows
        FROM feature_panel
        """
    ).fetchone()
    names = ("bad_forecast_order", "bad_feature_source", "bad_price_timestamp", "duplicate_rows")
    counts = {name: int(value or 0) for name, value in zip(names, violations, strict=True)}
    failing = {name: value for name, value in counts.items() if value}
    if failing:
        raise FeatureValidationError(f"feature panel invariant violations: {failing}")
    return {
        "no_lookahead_validation": {
            "bad_forecast_order": counts["bad_forecast_order"],
            "bad_feature_source": counts["bad_feature_source"],
            "bad_price_timestamp": counts["bad_price_timestamp"],
            "passed": (
                counts["bad_forecast_order"] == 0
                and counts["bad_feature_source"] == 0
                and counts["bad_price_timestamp"] == 0
            ),
        },
        "duplicate_key_validation": {
            "duplicate_rows": counts["duplicate_rows"],
            "passed": counts["duplicate_rows"] == 0,
        },
    }


def _build_summary(
    con: duckdb.DuckDBPyConnection,
    config: FeatureBuildConfig,
    validation: dict[str, dict[str, int | bool]],
) -> FeatureBuildSummary:
    input_row_count = int(con.execute("SELECT count(*) FROM base_panel").fetchone()[0])
    output_row_count = int(con.execute("SELECT count(*) FROM feature_panel").fetchone()[0])
    missing_feature_counts = _boolean_count_map(
        con,
        (
            "raw_probability_missing",
            "domain_missing_or_unknown",
            "category_missing_or_unknown",
            "event_family_id_missing",
            "listing_ts_missing",
            "momentum_missing",
            "volatility_missing",
            "liquidity_missing",
        ),
    )
    inferred_feature_counts = _boolean_count_map(con, ("event_family_id_inferred",))
    return FeatureBuildSummary(
        input_panel_path=str(config.panel_path),
        price_observations_path=str(config.price_observations_path),
        contracts_path=str(config.contracts_path),
        output_path=str(config.output_path),
        summary_path=str(config.summary_path),
        input_row_count=input_row_count,
        output_row_count=output_row_count,
        feature_windows_seconds={
            "momentum_window": int(config.momentum_window.total_seconds()),
            "volatility_window": int(config.volatility_window.total_seconds()),
            "liquidity_window": int(config.liquidity_window.total_seconds()),
        },
        probability_epsilon=config.probability_epsilon,
        missing_feature_counts=missing_feature_counts,
        inferred_feature_counts=inferred_feature_counts,
        no_lookahead_validation=validation["no_lookahead_validation"],
        duplicate_key_validation=validation["duplicate_key_validation"],
        effective_config=_effective_config(config),
        limitations=[
            "domain/category are inherited from taxonomy panel and may be unknown",
            "event_family_id currently uses the taxonomy layer's event_id proxy",
            "liquidity proxy uses public trade volume/count, not historical order-book depth",
            "momentum/volatility use transaction prices only, not executable quotes",
        ],
    )


def _boolean_count_map(
    con: duckdb.DuckDBPyConnection,
    columns: tuple[str, ...],
) -> dict[str, int]:
    select_sql = ", ".join(f"sum(CASE WHEN {column} THEN 1 ELSE 0 END)" for column in columns)
    values = con.execute(f"SELECT {select_sql} FROM feature_panel").fetchone()
    return {column: int(value or 0) for column, value in zip(columns, values, strict=True)}


def _effective_config(config: FeatureBuildConfig) -> dict[str, Any]:
    return {
        "inputs": {
            "panel_path": str(config.panel_path),
            "price_observations_path": str(config.price_observations_path),
            "contracts_path": str(config.contracts_path),
        },
        "outputs": {
            "panel_path": str(config.output_path),
            "summary_path": str(config.summary_path),
        },
        "features": {
            "probability_epsilon": config.probability_epsilon,
            "momentum_window_seconds": int(config.momentum_window.total_seconds()),
            "volatility_window_seconds": int(config.volatility_window.total_seconds()),
            "liquidity_window_seconds": int(config.liquidity_window.total_seconds()),
            "event_family_source": config.event_family_source,
            "domain_category_source": config.domain_category_source,
            "missing_domain_category_policy": config.missing_domain_category_policy,
            "limit_rows": config.limit_rows,
        },
        "config_path": str(config.config_path) if config.config_path else None,
        "config_sha256": config.config_sha256,
    }


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"feature config missing mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"feature config missing required key: {key}")
    return raw[key]


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _sql_string(path_or_value: Path | str) -> str:
    return "'" + str(path_or_value).replace("'", "''") + "'"


def _false_count(mask: pa.ChunkedArray | pa.Array) -> int:
    inverted = pc.invert(mask)
    return int(pc.sum(pc.cast(inverted, pa.int64())).as_py() or 0)
