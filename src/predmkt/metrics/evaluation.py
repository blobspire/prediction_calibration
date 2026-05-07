"""Config-driven raw forecast metric evaluation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from predmkt.metrics.calibration import fit_calibration_intercept_slope


@dataclass(frozen=True)
class GroupingConfig:
    """Named grouping dimensions for metric tables."""

    name: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class BucketConfig:
    """Config for deterministic numeric buckets."""

    column: str
    output_column: str
    edges: tuple[float, ...]
    labels: tuple[str, ...]


@dataclass(frozen=True)
class MetricsConfig:
    """Configuration for raw baseline metric evaluation."""

    panel_path: Path
    artifact_dir: Path
    probability_column: str
    outcome_column: str
    log_loss_epsilon: float
    reliability_bin_count: int
    reliability_min_bin_count: int
    calibration_min_rows: int
    calibration_max_iterations: int
    calibration_tolerance: float
    primary_aggregation: str
    secondary_aggregations: tuple[str, ...]
    include_trade_weighted_robustness: bool
    trade_weight_column: str
    groupings: tuple[GroupingConfig, ...]
    buckets: tuple[BucketConfig, ...]
    limit_rows: int | None = None
    config_path: Path | None = None
    config_sha256: str | None = None


@dataclass(frozen=True)
class MetricsEvaluationSummary:
    """Summary of a raw baseline metric run."""

    input_panel_path: str
    artifact_dir: str
    input_row_count: int
    scored_row_count: int
    dropped_missing_required_count: int
    aggregation_modes: list[str]
    primary_aggregation: str
    groupings_evaluated: list[str]
    groupings_skipped: dict[str, list[str]]
    reliability_bin_count: int
    reliability_min_bin_count: int
    log_loss_epsilon: float
    artifact_paths: dict[str, str]
    missing_feature_note_count: int
    calibration_status_counts: dict[str, int]
    effective_config: dict[str, Any]
    limitations: list[str]


class MetricsValidationError(ValueError):
    """Raised when metric inputs violate required invariants."""


CANONICAL_GROUP_COLUMNS = (
    "horizon_name",
    "domain",
    "category",
    "liquidity_bucket",
    "staleness_bucket",
)


def load_metrics_config(path: Path) -> MetricsConfig:
    """Load metric evaluation configuration from YAML."""

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"metrics config must be a mapping: {path}")

    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    metrics = _mapping(raw, "metrics")
    reliability = _mapping(raw, "reliability")
    calibration = _mapping(raw, "calibration")
    aggregation = _mapping(raw, "aggregation")
    grouping = _mapping(raw, "grouping")
    buckets = _mapping(raw, "buckets")

    epsilon = float(_required(metrics, "log_loss_epsilon"))
    if not 0.0 < epsilon < 0.5:
        raise ValueError("metrics.log_loss_epsilon must be in (0, 0.5)")

    bucket_configs = tuple(
        _load_bucket_config(name, value)
        for name, value in buckets.items()
        if isinstance(value, dict)
    )

    return MetricsConfig(
        panel_path=Path(_required(inputs, "panel_path")),
        artifact_dir=Path(_required(outputs, "artifact_dir")),
        probability_column=str(_required(metrics, "probability_column")),
        outcome_column=str(_required(metrics, "outcome_column")),
        log_loss_epsilon=epsilon,
        reliability_bin_count=int(_required(reliability, "bin_count")),
        reliability_min_bin_count=int(_required(reliability, "min_bin_count")),
        calibration_min_rows=int(_required(calibration, "min_rows")),
        calibration_max_iterations=int(_required(calibration, "max_iterations")),
        calibration_tolerance=float(_required(calibration, "tolerance")),
        primary_aggregation=str(_required(aggregation, "primary")),
        secondary_aggregations=tuple(str(value) for value in aggregation.get("secondary", [])),
        include_trade_weighted_robustness=bool(
            aggregation.get("include_trade_weighted_robustness", False)
        ),
        trade_weight_column=str(aggregation.get("trade_weight_column", "")),
        groupings=tuple(
            GroupingConfig(
                name=str(_required(value, "name")),
                columns=tuple(str(column) for column in value.get("columns", [])),
            )
            for value in grouping.get("dimensions", [])
            if isinstance(value, dict)
        ),
        buckets=bucket_configs,
        limit_rows=_optional_int(metrics.get("limit_rows")),
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def evaluate_raw_panel(config: MetricsConfig) -> MetricsEvaluationSummary:
    """Evaluate raw probabilities and write machine-readable metric artifacts."""

    if config.primary_aggregation != "equal_contract":
        raise MetricsValidationError("Phase 4 primary aggregation must be equal_contract")
    if config.reliability_bin_count <= 0:
        raise MetricsValidationError("reliability_bin_count must be positive")
    if config.reliability_min_bin_count < 0:
        raise MetricsValidationError("reliability_min_bin_count cannot be negative")

    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths = _artifact_paths(config.artifact_dir)

    con = duckdb.connect()
    try:
        con.execute("PRAGMA threads=4")
        _create_base_panel(con, config)
        input_row_count = int(con.execute("SELECT count(*) FROM base_panel").fetchone()[0])
        available_columns = set(_table_columns(con, "base_panel"))
        missing_required = [
            column
            for column in (
                config.probability_column,
                config.outcome_column,
                "contract_id",
                "horizon_name",
            )
            if column not in available_columns
        ]
        if missing_required:
            raise MetricsValidationError(
                f"metric input missing required columns: {missing_required}"
            )
        _validate_probability_and_outcome_ranges(con, config)
        _create_scored_panel(con, config, available_columns)
        scored_row_count = int(con.execute("SELECT count(*) FROM scored_panel").fetchone()[0])
        dropped_missing_required_count = input_row_count - scored_row_count
        if scored_row_count == 0:
            raise MetricsValidationError(
                "no rows with valid probability and outcome were available"
            )

        scored_columns = set(_table_columns(con, "scored_panel"))
        groupings, skipped_groupings = _usable_groupings(config.groupings, scored_columns)
        if not groupings:
            raise MetricsValidationError("no usable metric groupings configured")

        missing_notes = _missing_feature_notes(
            con,
            requested_groupings=config.groupings,
            skipped_groupings=skipped_groupings,
            available_columns=scored_columns,
            config=config,
        )
        _write_pylist_table(missing_notes, _missing_notes_schema(), artifact_paths["missing_notes"])

        _create_metric_tables(con, config, groupings, scored_columns)
        _create_reliability_table(con, config, groupings)
        _create_metrics_with_ece(con)
        con.execute(
            f"COPY metrics_by_group TO {_sql_string(artifact_paths['metrics_by_group'])} "
            "(FORMAT PARQUET)"
        )
        con.execute(
            """
            CREATE TEMP TABLE metrics_overall AS
            SELECT * FROM metrics_by_group
            WHERE grouping_name = 'overall'
            """
        )
        con.execute(
            f"COPY metrics_overall TO {_sql_string(artifact_paths['metrics_overall'])} "
            "(FORMAT PARQUET)"
        )
        con.execute(
            f"COPY reliability_bins TO {_sql_string(artifact_paths['reliability_bins'])} "
            "(FORMAT PARQUET)"
        )

        calibration_rows = _calibration_rows(con, config, groupings)
        _write_pylist_table(
            calibration_rows,
            _calibration_schema(),
            artifact_paths["calibration_fits"],
        )
        calibration_status_counts = _status_counts(calibration_rows)
        aggregation_modes = [
            row[0]
            for row in con.execute(
                "SELECT DISTINCT aggregation_mode FROM metrics_by_group ORDER BY aggregation_mode"
            ).fetchall()
        ]

        summary = MetricsEvaluationSummary(
            input_panel_path=str(config.panel_path),
            artifact_dir=str(config.artifact_dir),
            input_row_count=input_row_count,
            scored_row_count=scored_row_count,
            dropped_missing_required_count=dropped_missing_required_count,
            aggregation_modes=aggregation_modes,
            primary_aggregation=config.primary_aggregation,
            groupings_evaluated=[grouping.name for grouping in groupings],
            groupings_skipped=skipped_groupings,
            reliability_bin_count=config.reliability_bin_count,
            reliability_min_bin_count=config.reliability_min_bin_count,
            log_loss_epsilon=config.log_loss_epsilon,
            artifact_paths={key: str(value) for key, value in artifact_paths.items()},
            missing_feature_note_count=len(missing_notes),
            calibration_status_counts=calibration_status_counts,
            effective_config=_effective_config(config),
            limitations=[
                "Phase 4 evaluates raw probabilities only; no recalibrators or walk-forward "
                "model evaluation are implemented here.",
                "Primary aggregation is equal-contract; trade-weighted metrics are disabled "
                "unless explicitly enabled as a robustness output.",
                "Domain/category groups use the audited rule-based taxonomy; title-keyword, "
                "ambiguous, and unknown assignments remain exploratory rather than "
                "confirmatory domain findings.",
                "Liquidity and staleness groups use public feature-panel proxies, not "
                "historical order-book depth or executable quotes.",
            ],
        )
    finally:
        con.close()

    artifact_paths["summary"].write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def _create_base_panel(con: duckdb.DuckDBPyConnection, config: MetricsConfig) -> None:
    panel_sql = f"read_parquet({_sql_string(config.panel_path)})"
    if config.limit_rows is not None:
        if config.limit_rows <= 0:
            raise MetricsValidationError("limit_rows must be positive when provided")
        panel_sql = f"(SELECT * FROM {panel_sql} LIMIT {config.limit_rows})"
    con.execute(f"CREATE TEMP TABLE base_panel AS SELECT * FROM {panel_sql}")


def _validate_probability_and_outcome_ranges(
    con: duckdb.DuckDBPyConnection,
    config: MetricsConfig,
) -> None:
    probability = _ident(config.probability_column)
    outcome = _ident(config.outcome_column)
    bad_values = con.execute(
        f"""
        SELECT
            sum(CASE
                WHEN {probability} IS NOT NULL
                 AND ({probability} < 0 OR {probability} > 1)
                THEN 1 ELSE 0
            END) AS invalid_probability,
            sum(CASE
                WHEN {outcome} IS NOT NULL
                 AND CAST({outcome} AS DOUBLE) NOT IN (0.0, 1.0)
                THEN 1 ELSE 0
            END) AS invalid_outcome
        FROM base_panel
        """
    ).fetchone()
    invalid_probability = int(bad_values[0] or 0)
    invalid_outcome = int(bad_values[1] or 0)
    if invalid_probability or invalid_outcome:
        raise MetricsValidationError(
            "metric input has invalid probability/outcome values: "
            f"invalid_probability={invalid_probability}, invalid_outcome={invalid_outcome}"
        )


def _create_scored_panel(
    con: duckdb.DuckDBPyConnection,
    config: MetricsConfig,
    available_columns: set[str],
) -> None:
    probability = _ident(config.probability_column)
    outcome = _ident(config.outcome_column)
    epsilon = config.log_loss_epsilon
    bucket_selects = [
        f"{_bucket_case_sql(bucket)} AS {_ident(bucket.output_column)}"
        for bucket in config.buckets
        if bucket.column in available_columns
    ]
    if not bucket_selects:
        bucket_sql = ""
    else:
        bucket_sql = ",\n            " + ",\n            ".join(bucket_selects)

    optional_event_family = (
        "CAST(event_family_id AS VARCHAR) AS event_family_id,"
        if "event_family_id" in available_columns
        else "CAST(contract_id AS VARCHAR) AS event_family_id,"
    )
    con.execute(
        f"""
        CREATE TEMP TABLE scored_panel AS
        SELECT
            *,
            CAST({probability} AS DOUBLE) AS metric_probability,
            CAST({outcome} AS DOUBLE) AS metric_outcome,
            least(greatest(CAST({probability} AS DOUBLE), {epsilon}), {1.0 - epsilon})
                AS metric_clipped_probability,
            {optional_event_family}
            power(CAST({probability} AS DOUBLE) - CAST({outcome} AS DOUBLE), 2.0)
                AS brier_loss,
            -(
                CAST({outcome} AS DOUBLE)
                    * ln(least(greatest(CAST({probability} AS DOUBLE), {epsilon}), {1.0 - epsilon}))
                + (1.0 - CAST({outcome} AS DOUBLE))
                    * ln(
                        1.0 - least(
                            greatest(CAST({probability} AS DOUBLE), {epsilon}),
                            {1.0 - epsilon}
                        )
                    )
            ) AS log_loss{bucket_sql}
        FROM base_panel
        WHERE {probability} IS NOT NULL
          AND {outcome} IS NOT NULL
          AND CAST({outcome} AS DOUBLE) IN (0.0, 1.0)
        """
    )


def _create_metric_tables(
    con: duckdb.DuckDBPyConnection,
    config: MetricsConfig,
    groupings: list[GroupingConfig],
    scored_columns: set[str],
) -> None:
    queries: list[str] = []
    for grouping in groupings:
        queries.append(_equal_contract_metrics_sql(grouping))
        if "equal_event_family" in config.secondary_aggregations:
            queries.append(_equal_event_family_metrics_sql(grouping))
        if config.include_trade_weighted_robustness:
            if not config.trade_weight_column or config.trade_weight_column not in scored_columns:
                raise MetricsValidationError(
                    "trade-weighted robustness requested, but trade_weight_column is unavailable"
                )
            queries.append(_trade_weighted_metrics_sql(grouping, config.trade_weight_column))
    con.execute("CREATE TEMP TABLE raw_metrics_by_group AS\n" + "\nUNION ALL\n".join(queries))


def _create_reliability_table(
    con: duckdb.DuckDBPyConnection,
    config: MetricsConfig,
    groupings: list[GroupingConfig],
) -> None:
    queries = [_reliability_sql(grouping, config) for grouping in groupings]
    con.execute("CREATE TEMP TABLE reliability_bins AS\n" + queries[0])
    for query in queries[1:]:
        con.execute("INSERT INTO reliability_bins\n" + query)


def _create_metrics_with_ece(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TEMP TABLE ece_by_group AS
        SELECT
            grouping_name,
            group_key,
            sum(ece_contribution) AS expected_calibration_error
        FROM reliability_bins
        GROUP BY grouping_name, group_key
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE metrics_by_group AS
        SELECT
            m.*,
            CASE
                WHEN m.aggregation_mode = 'equal_contract'
                THEN e.expected_calibration_error
                ELSE NULL
            END AS expected_calibration_error
        FROM raw_metrics_by_group AS m
        LEFT JOIN ece_by_group AS e
          ON e.grouping_name = m.grouping_name
         AND e.group_key = m.group_key
        """
    )


def _equal_contract_metrics_sql(grouping: GroupingConfig) -> str:
    group_cols = _group_columns_sql(grouping)
    group_by = _group_by_sql(grouping)
    return f"""
    SELECT
        'equal_contract' AS aggregation_mode,
        '{_sql_literal(grouping.name)}' AS grouping_name,
        {_group_key_expr(grouping)} AS group_key,
        {group_cols},
        count(*) AS row_count,
        count(DISTINCT contract_id) AS contract_count,
        count(DISTINCT event_family_id) AS event_family_count,
        CAST(NULL AS DOUBLE) AS total_weight,
        avg(brier_loss) AS brier_score,
        avg(log_loss) AS log_loss
    FROM scored_panel
    {group_by}
    """


def _equal_event_family_metrics_sql(grouping: GroupingConfig) -> str:
    inner_cols = _actual_group_columns(grouping)
    inner_select = _select_actual_group_columns(inner_cols)
    inner_group = _group_by_names([*inner_cols, "event_family_id"])
    outer_cols = _group_columns_sql(grouping)
    outer_group = _group_by_sql(grouping)
    return f"""
    SELECT
        'equal_event_family' AS aggregation_mode,
        '{_sql_literal(grouping.name)}' AS grouping_name,
        {_group_key_expr(grouping)} AS group_key,
        {outer_cols},
        sum(family_row_count) AS row_count,
        CAST(NULL AS BIGINT) AS contract_count,
        count(*) AS event_family_count,
        CAST(NULL AS DOUBLE) AS total_weight,
        avg(family_brier_loss) AS brier_score,
        avg(family_log_loss) AS log_loss
    FROM (
        SELECT
            {inner_select}
            event_family_id,
            count(*) AS family_row_count,
            avg(brier_loss) AS family_brier_loss,
            avg(log_loss) AS family_log_loss
        FROM scored_panel
        {inner_group}
    ) AS family_losses
    {outer_group}
    """


def _trade_weighted_metrics_sql(grouping: GroupingConfig, weight_column: str) -> str:
    group_cols = _group_columns_sql(grouping)
    group_by = _group_by_sql(grouping)
    weight = _ident(weight_column)
    return f"""
    SELECT
        'trade_weighted' AS aggregation_mode,
        '{_sql_literal(grouping.name)}' AS grouping_name,
        {_group_key_expr(grouping)} AS group_key,
        {group_cols},
        count(*) AS row_count,
        count(DISTINCT contract_id) AS contract_count,
        count(DISTINCT event_family_id) AS event_family_count,
        sum({weight}) AS total_weight,
        sum(brier_loss * {weight}) / NULLIF(sum({weight}), 0) AS brier_score,
        sum(log_loss * {weight}) / NULLIF(sum({weight}), 0) AS log_loss
    FROM scored_panel
    WHERE {weight} IS NOT NULL AND {weight} > 0
    {group_by}
    """


def _reliability_sql(grouping: GroupingConfig, config: MetricsConfig) -> str:
    bin_count = config.reliability_bin_count
    min_bin_count = config.reliability_min_bin_count
    actual_cols = _actual_group_columns(grouping)
    select_cols = _select_actual_group_columns(actual_cols)
    group_key = _group_key_expr(grouping)
    join_conditions = " AND ".join(_null_safe_join_condition(column) for column in actual_cols)
    if not join_conditions:
        join_conditions = "TRUE"
    group_cols = _group_columns_sql(grouping, table_alias="g")
    partition = "grouping_name, group_key"
    return f"""
    WITH row_bins AS (
        SELECT
            {select_cols}
            {group_key} AS group_key,
            least(CAST(floor(metric_probability * {bin_count}) AS INTEGER), {bin_count - 1})
                AS bin_index,
            metric_probability,
            metric_outcome
        FROM scored_panel
    ),
    groups AS (
        SELECT DISTINCT
            {select_cols}
            group_key
        FROM row_bins
    ),
    bins AS (
        SELECT range AS bin_index FROM range({bin_count})
    ),
    aggregated AS (
        SELECT
            {select_cols}
            group_key,
            bin_index,
            count(*) AS row_count,
            avg(metric_probability) AS mean_predicted_probability,
            avg(metric_outcome) AS observed_frequency
        FROM row_bins
        {_group_by_names([*actual_cols, "group_key", "bin_index"])}
    ),
    completed AS (
        SELECT
            '{_sql_literal(grouping.name)}' AS grouping_name,
            g.group_key,
            {group_cols},
            b.bin_index,
            CAST(b.bin_index AS DOUBLE) / {bin_count} AS bin_lower,
            CAST(b.bin_index + 1 AS DOUBLE) / {bin_count} AS bin_upper,
            COALESCE(a.row_count, 0) AS row_count,
            a.mean_predicted_probability,
            a.observed_frequency,
            CASE
                WHEN a.row_count IS NULL OR a.row_count = 0 THEN NULL
                ELSE abs(a.mean_predicted_probability - a.observed_frequency)
            END AS absolute_calibration_gap,
            COALESCE(a.row_count, 0) = 0 AS is_empty,
            COALESCE(a.row_count, 0) > 0 AND COALESCE(a.row_count, 0) < {min_bin_count}
                AS is_sparse
        FROM groups AS g
        CROSS JOIN bins AS b
        LEFT JOIN aggregated AS a
          ON a.group_key = g.group_key
         AND a.bin_index = b.bin_index
         AND {join_conditions}
    )
    SELECT
        'equal_contract' AS aggregation_mode,
        *,
        sum(row_count) OVER (PARTITION BY {partition}) AS total_row_count,
        CASE
            WHEN row_count = 0 THEN 0.0
            ELSE
                (CAST(row_count AS DOUBLE) / sum(row_count) OVER (PARTITION BY {partition}))
                * absolute_calibration_gap
        END AS ece_contribution
    FROM completed
    """


def _calibration_rows(
    con: duckdb.DuckDBPyConnection,
    config: MetricsConfig,
    groupings: list[GroupingConfig],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for grouping in groupings:
        actual_cols = _actual_group_columns(grouping)
        select_cols = _select_actual_group_columns(actual_cols)
        query = f"""
        SELECT
            {_group_key_expr(grouping)} AS group_key,
            {select_cols}
            list(metric_probability ORDER BY contract_id, horizon_name) AS probabilities,
            list(metric_outcome ORDER BY contract_id, horizon_name) AS outcomes,
            count(*) AS row_count
        FROM scored_panel
        {_group_by_names([*actual_cols, "group_key"])}
        """
        for result in con.execute(query).fetchall():
            group_key = result[0]
            group_values = dict(zip(actual_cols, result[1 : 1 + len(actual_cols)], strict=True))
            probabilities = result[1 + len(actual_cols)]
            outcomes = result[2 + len(actual_cols)]
            fit = fit_calibration_intercept_slope(
                probabilities,
                outcomes,
                epsilon=config.log_loss_epsilon,
                min_rows=config.calibration_min_rows,
                max_iterations=config.calibration_max_iterations,
                tolerance=config.calibration_tolerance,
            )
            rows.append(
                {
                    "aggregation_mode": "equal_contract",
                    "grouping_name": grouping.name,
                    "group_key": group_key,
                    **_canonical_group_values(group_values),
                    "row_count": fit.row_count,
                    "intercept": fit.intercept,
                    "slope": fit.slope,
                    "iterations": fit.iterations,
                    "converged": fit.converged,
                    "status": fit.status,
                }
            )
    return rows


def _missing_feature_notes(
    con: duckdb.DuckDBPyConnection,
    *,
    requested_groupings: tuple[GroupingConfig, ...],
    skipped_groupings: dict[str, list[str]],
    available_columns: set[str],
    config: MetricsConfig,
) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    for grouping in requested_groupings:
        missing = skipped_groupings.get(grouping.name)
        if missing:
            notes.append(
                {
                    "note_type": "skipped_grouping",
                    "field": ",".join(missing),
                    "grouping_name": grouping.name,
                    "row_count": None,
                    "message": (
                        "Grouping skipped because one or more configured columns are missing."
                    ),
                }
            )
    for column in ("domain", "category"):
        if column in available_columns:
            unknown_count = int(
                con.execute(
                    f"""
                    SELECT count(*)
                    FROM scored_panel
                    WHERE {_ident(column)} IS NULL OR {_ident(column)} = 'unknown'
                    """
                ).fetchone()[0]
            )
            if unknown_count:
                notes.append(
                    {
                        "note_type": "unknown_group_field",
                        "field": column,
                        "grouping_name": column,
                        "row_count": unknown_count,
                        "message": (
                            f"{column} is missing or unknown for these rows; grouped results "
                            "are taxonomy placeholders, not domain-level findings."
                        ),
                    }
                )
    for bucket in config.buckets:
        if bucket.column not in available_columns:
            notes.append(
                {
                    "note_type": "missing_bucket_source",
                    "field": bucket.column,
                    "grouping_name": bucket.output_column,
                    "row_count": None,
                    "message": "Configured bucket source column is unavailable.",
                }
            )
    return notes


def _usable_groupings(
    requested: tuple[GroupingConfig, ...],
    available_columns: set[str],
) -> tuple[list[GroupingConfig], dict[str, list[str]]]:
    usable: list[GroupingConfig] = []
    skipped: dict[str, list[str]] = {}
    for grouping in requested:
        missing = [column for column in grouping.columns if column not in available_columns]
        if missing:
            skipped[grouping.name] = missing
        else:
            usable.append(grouping)
    return usable, skipped


def _group_columns_sql(grouping: GroupingConfig, table_alias: str | None = None) -> str:
    values = []
    prefix = f"{table_alias}." if table_alias else ""
    for column in CANONICAL_GROUP_COLUMNS:
        if column in grouping.columns:
            values.append(f"CAST({prefix}{_ident(column)} AS VARCHAR) AS {column}")
        else:
            values.append(f"CAST(NULL AS VARCHAR) AS {column}")
    return ",\n        ".join(values)


def _group_key_expr(grouping: GroupingConfig) -> str:
    if not grouping.columns:
        return "'overall'"
    parts = [
        f"COALESCE(CAST({_ident(column)} AS VARCHAR), '<missing>')"
        for column in grouping.columns
    ]
    expression = parts[0]
    for part in parts[1:]:
        expression = f"{expression} || '|' || {part}"
    return expression


def _group_by_sql(grouping: GroupingConfig) -> str:
    columns = _actual_group_columns(grouping)
    if not columns:
        return ""
    return "GROUP BY " + ", ".join(_ident(column) for column in columns)


def _group_by_names(columns: list[str]) -> str:
    if not columns:
        return ""
    return "GROUP BY " + ", ".join(_ident(column) for column in columns)


def _select_actual_group_columns(columns: list[str]) -> str:
    if not columns:
        return ""
    return "".join(f"{_ident(column)},\n            " for column in columns)


def _actual_group_columns(grouping: GroupingConfig) -> list[str]:
    return list(grouping.columns)


def _canonical_group_values(values: dict[str, Any]) -> dict[str, Any]:
    return {column: values.get(column) for column in CANONICAL_GROUP_COLUMNS}


def _bucket_case_sql(bucket: BucketConfig) -> str:
    column = _ident(bucket.column)
    pieces = [f"CASE WHEN {column} IS NULL THEN 'missing'"]
    for edge, label in zip(bucket.edges, bucket.labels, strict=False):
        pieces.append(f"WHEN {column} < {edge} THEN '{_sql_literal(label)}'")
    pieces.append(f"ELSE '{_sql_literal(bucket.labels[-1])}' END")
    return "\n                ".join(pieces)


def _load_bucket_config(name: str, raw: dict[str, Any]) -> BucketConfig:
    edges = tuple(float(value) for value in raw.get("edges", []))
    labels = tuple(str(value) for value in raw.get("labels", []))
    if len(labels) != len(edges) + 1:
        raise ValueError(f"bucket {name} must define exactly len(edges)+1 labels")
    return BucketConfig(
        column=str(_required(raw, "column")),
        output_column=str(raw.get("output_column", f"{name}_bucket")),
        edges=edges,
        labels=labels,
    )


def _write_pylist_table(rows: list[dict[str, Any]], schema: pa.Schema, path: Path) -> None:
    if rows:
        table = pa.Table.from_pylist(rows, schema=schema)
    else:
        table = pa.Table.from_arrays([[] for _ in schema], schema=schema)
    pq.write_table(table, path)


def _calibration_schema() -> pa.Schema:
    return pa.schema(
        [
            ("aggregation_mode", pa.string()),
            ("grouping_name", pa.string()),
            ("group_key", pa.string()),
            ("horizon_name", pa.string()),
            ("domain", pa.string()),
            ("category", pa.string()),
            ("liquidity_bucket", pa.string()),
            ("staleness_bucket", pa.string()),
            ("row_count", pa.int64()),
            ("intercept", pa.float64()),
            ("slope", pa.float64()),
            ("iterations", pa.int64()),
            ("converged", pa.bool_()),
            ("status", pa.string()),
        ]
    )


def _missing_notes_schema() -> pa.Schema:
    return pa.schema(
        [
            ("note_type", pa.string()),
            ("field", pa.string()),
            ("grouping_name", pa.string()),
            ("row_count", pa.int64()),
            ("message", pa.string()),
        ]
    )


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row["status"])
        counts[status] = counts.get(status, 0) + 1
    return counts


def _artifact_paths(artifact_dir: Path) -> dict[str, Path]:
    return {
        "metrics_overall": artifact_dir / "metrics_overall.parquet",
        "metrics_by_group": artifact_dir / "metrics_by_group.parquet",
        "reliability_bins": artifact_dir / "reliability_bins.parquet",
        "calibration_fits": artifact_dir / "calibration_fits.parquet",
        "missing_notes": artifact_dir / "missing_feature_notes.parquet",
        "summary": artifact_dir / "summary.json",
    }


def _effective_config(config: MetricsConfig) -> dict[str, Any]:
    return {
        "inputs": {"panel_path": str(config.panel_path)},
        "outputs": {"artifact_dir": str(config.artifact_dir)},
        "metrics": {
            "probability_column": config.probability_column,
            "outcome_column": config.outcome_column,
            "log_loss_epsilon": config.log_loss_epsilon,
            "limit_rows": config.limit_rows,
        },
        "reliability": {
            "bin_count": config.reliability_bin_count,
            "min_bin_count": config.reliability_min_bin_count,
        },
        "calibration": {
            "min_rows": config.calibration_min_rows,
            "max_iterations": config.calibration_max_iterations,
            "tolerance": config.calibration_tolerance,
        },
        "aggregation": {
            "primary": config.primary_aggregation,
            "secondary": list(config.secondary_aggregations),
            "include_trade_weighted_robustness": config.include_trade_weighted_robustness,
            "trade_weight_column": config.trade_weight_column,
        },
        "grouping": {
            "dimensions": [
                {"name": grouping.name, "columns": list(grouping.columns)}
                for grouping in config.groupings
            ]
        },
        "buckets": {
            bucket.output_column: {
                "column": bucket.column,
                "edges": list(bucket.edges),
                "labels": list(bucket.labels),
            }
            for bucket in config.buckets
        },
        "config_path": str(config.config_path) if config.config_path else None,
        "config_sha256": config.config_sha256,
    }


def _table_columns(con: duckdb.DuckDBPyConnection, table_name: str) -> list[str]:
    rows = con.execute(f"PRAGMA table_info({_sql_string(table_name)})").fetchall()
    return [row[1] for row in rows]


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"metrics config missing mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"metrics config missing required key: {key}")
    return raw[key]


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _ident(value: str) -> str:
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


def _left(column: str) -> str:
    return f"a.{_ident(column)}"


def _right(column: str) -> str:
    return f"g.{_ident(column)}"


def _null_safe_join_condition(column: str) -> str:
    return (
        f"(({_left(column)} = {_right(column)}) "
        f"OR ({_left(column)} IS NULL AND {_right(column)} IS NULL))"
    )


def _sql_string(path_or_value: Path | str) -> str:
    return "'" + str(path_or_value).replace("'", "''") + "'"


def _sql_literal(value: str) -> str:
    return str(value).replace("'", "''")
