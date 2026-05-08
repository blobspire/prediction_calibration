"""Manuscript-ready tables from saved result artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

import pandas as pd  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]

DEFAULT_HORIZON_ORDER = ("30d", "14d", "7d", "3d", "1d", "6h", "1h", "15m", "close")
DEFAULT_MODEL_ORDER = (
    "raw",
    "platt",
    "beta",
    "isotonic",
    "binned_reliability",
    "hierarchical_eb",
)
DEFAULT_FIGURE_FORMATS = ("png", "svg", "pdf")
DEFAULT_TABLE_FORMATS = ("csv", "markdown", "latex")


@dataclass(frozen=True)
class ReportingConfig:
    """Shared configuration for manuscript figures and tables."""

    raw_baseline_artifact_dir: Path
    walkforward_artifact_dir: Path
    edge_artifact_dir: Path
    inference_artifact_dir: Path
    decomposition_artifact_dir: Path
    figure_dir: Path
    table_dir: Path
    artifact_run_label: str
    horizon_order: tuple[str, ...]
    model_order: tuple[str, ...]
    metric_scope: str
    aggregation_mode: str
    reliability_bin_count: int
    reliability_min_bin_count: int
    figure_formats: tuple[str, ...]
    dpi: int
    table_formats: tuple[str, ...]
    config_path: Path | None = None
    config_sha256: str | None = None


@dataclass(frozen=True)
class ManuscriptTableSummary:
    """Summary of generated manuscript tables."""

    table_dir: str
    table_paths: dict[str, list[str]]
    source_artifacts: dict[str, str]
    effective_config: dict[str, Any]
    limitations: list[str]


class ReportingError(ValueError):
    """Raised when manuscript reporting inputs are missing or invalid."""


def load_reporting_config(path: Path) -> ReportingConfig:
    """Load manuscript reporting configuration from YAML."""

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"reporting config must be a mapping: {path}")
    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    reporting = _mapping(raw, "reporting")
    return ReportingConfig(
        raw_baseline_artifact_dir=Path(_required(inputs, "raw_baseline_artifact_dir")),
        walkforward_artifact_dir=Path(_required(inputs, "walkforward_artifact_dir")),
        edge_artifact_dir=Path(_required(inputs, "edge_artifact_dir")),
        inference_artifact_dir=Path(_required(inputs, "inference_artifact_dir")),
        decomposition_artifact_dir=Path(_required(inputs, "decomposition_artifact_dir")),
        figure_dir=Path(_required(outputs, "figure_dir")),
        table_dir=Path(_required(outputs, "table_dir")),
        artifact_run_label=str(_required(reporting, "artifact_run_label")),
        horizon_order=tuple(
            str(item) for item in reporting.get("horizon_order", DEFAULT_HORIZON_ORDER)
        ),
        model_order=tuple(str(item) for item in reporting.get("model_order", DEFAULT_MODEL_ORDER)),
        metric_scope=str(reporting.get("metric_scope", "pooled_equal_contract")),
        aggregation_mode=str(reporting.get("aggregation_mode", "equal_contract")),
        reliability_bin_count=int(reporting.get("reliability_bin_count", 10)),
        reliability_min_bin_count=int(reporting.get("reliability_min_bin_count", 30)),
        figure_formats=tuple(
            str(item) for item in reporting.get("figure_formats", DEFAULT_FIGURE_FORMATS)
        ),
        dpi=int(reporting.get("dpi", 300)),
        table_formats=tuple(
            str(item) for item in reporting.get("table_formats", DEFAULT_TABLE_FORMATS)
        ),
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def make_manuscript_tables(config: ReportingConfig) -> ManuscriptTableSummary:
    """Write manuscript tables from saved walk-forward and edge artifacts."""

    _validate_reporting_config(config, require_figures=False, require_tables=True)
    config.table_dir.mkdir(parents=True, exist_ok=True)
    sources = reporting_source_paths(config)
    aggregate = pd.read_parquet(sources["walkforward_aggregate_metrics"])
    edge_summary = pd.read_parquet(sources["edge_summary_by_model_tier"])
    raw_summary = _read_json(sources["raw_baseline_summary"])
    walkforward_summary = _read_json(sources["walkforward_summary"])
    edge_run_summary = _read_json(sources["edge_summary"])
    inference_summary = _read_json(sources["inference_summary"])
    score_intervals = pd.read_parquet(sources["inference_score_intervals"])
    paired_differences = pd.read_parquet(sources["inference_paired_score_differences"])
    calibration_intervals = pd.read_parquet(sources["inference_calibration_intervals"])
    decomposition = pd.read_parquet(sources["decomposition_murphy_decomposition"])
    decomposition_summary = _read_json(sources["decomposition_summary"])

    tables = {
        "overall_score_comparison": _overall_score_table(
            aggregate,
            score_intervals,
            paired_differences,
            config,
        ),
        "horizon_score_comparison": _horizon_score_table(
            aggregate,
            score_intervals,
            paired_differences,
            config,
        ),
        "calibration_intercept_slope": _calibration_table(
            aggregate,
            calibration_intervals,
            config,
        ),
        "edge_friction_sensitivity": _edge_table(edge_summary, config),
        "murphy_decomposition": _murphy_table(decomposition, config),
        "artifact_source_limitations": _limitations_table(
            raw_summary,
            walkforward_summary,
            edge_run_summary,
            inference_summary,
            decomposition_summary,
            config,
        ),
    }
    table_paths = {
        name: _write_table(frame, config, name)
        for name, frame in tables.items()
    }
    summary = ManuscriptTableSummary(
        table_dir=str(config.table_dir),
        table_paths={key: [str(path) for path in paths] for key, paths in table_paths.items()},
        source_artifacts={key: str(path) for key, path in sources.items()},
        effective_config=effective_reporting_config(config),
        limitations=_common_limitations(config),
    )
    (config.table_dir / "table_manifest.json").write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def reporting_source_paths(config: ReportingConfig) -> dict[str, Path]:
    """Return required saved-artifact paths for manuscript outputs."""

    return {
        "raw_baseline_summary": config.raw_baseline_artifact_dir / "summary.json",
        "raw_baseline_reliability_bins": (
            config.raw_baseline_artifact_dir / "reliability_bins.parquet"
        ),
        "walkforward_summary": config.walkforward_artifact_dir / "summary.json",
        "walkforward_predictions": config.walkforward_artifact_dir / "predictions.parquet",
        "walkforward_aggregate_metrics": (
            config.walkforward_artifact_dir / "aggregate_metrics.parquet"
        ),
        "walkforward_fold_metrics": config.walkforward_artifact_dir / "fold_metrics.parquet",
        "edge_summary": config.edge_artifact_dir / "summary.json",
        "edge_summary_by_tier": config.edge_artifact_dir / "edge_summary_by_tier.parquet",
        "edge_summary_by_model_tier": (
            config.edge_artifact_dir / "edge_summary_by_model_tier.parquet"
        ),
        "inference_summary": config.inference_artifact_dir / "summary.json",
        "inference_score_intervals": config.inference_artifact_dir / "score_intervals.parquet",
        "inference_paired_score_differences": (
            config.inference_artifact_dir / "paired_score_differences.parquet"
        ),
        "inference_calibration_intervals": (
            config.inference_artifact_dir / "calibration_intervals.parquet"
        ),
        "inference_multiple_comparison_adjustments": (
            config.inference_artifact_dir / "multiple_comparison_adjustments.parquet"
        ),
        "decomposition_summary": config.decomposition_artifact_dir / "summary.json",
        "decomposition_murphy_decomposition": (
            config.decomposition_artifact_dir / "murphy_decomposition.parquet"
        ),
        "decomposition_murphy_bins": config.decomposition_artifact_dir / "murphy_bins.parquet",
    }


def effective_reporting_config(config: ReportingConfig) -> dict[str, Any]:
    """Return serializable effective config values."""

    return {
        "inputs": {
            "raw_baseline_artifact_dir": str(config.raw_baseline_artifact_dir),
            "walkforward_artifact_dir": str(config.walkforward_artifact_dir),
            "edge_artifact_dir": str(config.edge_artifact_dir),
            "inference_artifact_dir": str(config.inference_artifact_dir),
            "decomposition_artifact_dir": str(config.decomposition_artifact_dir),
        },
        "outputs": {
            "figure_dir": str(config.figure_dir),
            "table_dir": str(config.table_dir),
        },
        "reporting": {
            "artifact_run_label": config.artifact_run_label,
            "horizon_order": list(config.horizon_order),
            "model_order": list(config.model_order),
            "metric_scope": config.metric_scope,
            "aggregation_mode": config.aggregation_mode,
            "reliability_bin_count": config.reliability_bin_count,
            "reliability_min_bin_count": config.reliability_min_bin_count,
            "figure_formats": list(config.figure_formats),
            "dpi": config.dpi,
            "table_formats": list(config.table_formats),
        },
        "config_path": str(config.config_path) if config.config_path else None,
        "config_sha256": config.config_sha256,
    }


def validate_required_artifacts(config: ReportingConfig) -> dict[str, Path]:
    """Validate full-result artifact paths and return them."""

    sources = reporting_source_paths(config)
    missing = [str(path) for path in sources.values() if not path.exists()]
    if missing:
        raise ReportingError(
            "missing saved result artifacts for manuscript outputs. Run the full Phase 7 "
            "walk-forward evaluation, Phase 8 edge simulation, and Phase 13 inference "
            "first, or explicitly override artifact directories for a smoke/draft run. "
            f"Missing: {missing}"
        )
    if config.artifact_run_label == "full":
        smoke_paths = [
            str(path)
            for path in (
                config.walkforward_artifact_dir,
                config.edge_artifact_dir,
                config.inference_artifact_dir,
                config.decomposition_artifact_dir,
            )
            if "smoke" in str(path)
        ]
        if smoke_paths:
            raise ReportingError(
                "reporting.artifact_run_label is full, but smoke artifact directories were "
                f"provided: {smoke_paths}"
            )
    return sources


def _overall_score_table(
    aggregate: pd.DataFrame,
    score_intervals: pd.DataFrame,
    paired_differences: pd.DataFrame,
    config: ReportingConfig,
) -> pd.DataFrame:
    rows = _metric_rows(aggregate, config, grouping_name="overall")
    rows = _ordered_models(rows, config)
    rows = _add_raw_deltas(rows)
    rows = _add_score_inference_columns(
        rows,
        score_intervals,
        paired_differences,
        grouping_name="overall",
    )
    return rows[
        [
            "model_name",
            "row_count",
            "brier_score",
            "brier_delta_vs_raw",
            "brier_score_ci_lower",
            "brier_score_ci_upper",
            "brier_delta_ci_lower",
            "brier_delta_ci_upper",
            "brier_delta_p_value",
            "brier_delta_q_value",
            "log_loss",
            "log_loss_delta_vs_raw",
            "log_loss_ci_lower",
            "log_loss_ci_upper",
            "log_loss_delta_ci_lower",
            "log_loss_delta_ci_upper",
            "log_loss_delta_p_value",
            "log_loss_delta_q_value",
            "expected_calibration_error",
            "ece_delta_vs_raw",
            "ece_ci_lower",
            "ece_ci_upper",
            "ece_delta_ci_lower",
            "ece_delta_ci_upper",
            "ece_delta_p_value",
            "ece_delta_q_value",
            "effective_cluster_count",
            "cluster_count",
            "calibration_intercept",
            "calibration_slope",
            "calibration_status",
        ]
    ].copy()


def _horizon_score_table(
    aggregate: pd.DataFrame,
    score_intervals: pd.DataFrame,
    paired_differences: pd.DataFrame,
    config: ReportingConfig,
) -> pd.DataFrame:
    rows = _metric_rows(aggregate, config, grouping_name="horizon")
    rows = _ordered_models(_ordered_horizons(rows, config), config)
    rows = _add_raw_deltas(rows, group_columns=("horizon_name",))
    rows = _add_score_inference_columns(
        rows,
        score_intervals,
        paired_differences,
        grouping_name="horizon",
    )
    return rows[
        [
            "horizon_name",
            "model_name",
            "row_count",
            "brier_score",
            "brier_delta_vs_raw",
            "brier_score_ci_lower",
            "brier_score_ci_upper",
            "brier_delta_ci_lower",
            "brier_delta_ci_upper",
            "brier_delta_p_value",
            "brier_delta_q_value",
            "log_loss",
            "log_loss_delta_vs_raw",
            "log_loss_ci_lower",
            "log_loss_ci_upper",
            "log_loss_delta_ci_lower",
            "log_loss_delta_ci_upper",
            "log_loss_delta_p_value",
            "log_loss_delta_q_value",
            "expected_calibration_error",
            "ece_delta_vs_raw",
            "ece_ci_lower",
            "ece_ci_upper",
            "ece_delta_ci_lower",
            "ece_delta_ci_upper",
            "ece_delta_p_value",
            "ece_delta_q_value",
            "effective_cluster_count",
            "cluster_count",
        ]
    ].copy()


def _calibration_table(
    aggregate: pd.DataFrame,
    calibration_intervals: pd.DataFrame,
    config: ReportingConfig,
) -> pd.DataFrame:
    rows = _metric_rows(aggregate, config, grouping_name="horizon")
    rows = _ordered_models(_ordered_horizons(rows, config), config)
    rows = _add_calibration_inference_columns(rows, calibration_intervals)
    return rows[
        [
            "horizon_name",
            "model_name",
            "row_count",
            "calibration_intercept",
            "calibration_intercept_ci_lower",
            "calibration_intercept_ci_upper",
            "calibration_intercept_p_value",
            "calibration_slope",
            "calibration_slope_ci_lower",
            "calibration_slope_ci_upper",
            "calibration_slope_p_value",
            "effective_cluster_count",
            "cluster_count",
            "calibration_status",
        ]
    ].copy()


def _edge_table(edge_summary: pd.DataFrame, config: ReportingConfig) -> pd.DataFrame:
    rows = edge_summary.copy()
    if "model_name" in rows.columns:
        rows = _ordered_models(rows, config)
    tier_order = {"fee_only": 0, "fee_spread": 1, "fee_spread_slippage": 2}
    rows["_tier_order"] = rows["friction_tier"].map(tier_order).fillna(99)
    rows = rows.sort_values(["model_order", "_tier_order", "friction_tier"])
    columns = [
        "model_name",
        "friction_tier",
        "candidate_row_count",
        "selected_row_count",
        "selected_share",
        "mean_net_edge",
        "median_net_edge",
        "selected_mean_net_edge",
        "selected_mean_simulated_realized_net_per_contract",
    ]
    return rows[[column for column in columns if column in rows.columns]].copy()


def _murphy_table(decomposition: pd.DataFrame, config: ReportingConfig) -> pd.DataFrame:
    rows = decomposition[
        (decomposition["grouping_name"] == "overall")
        & (decomposition["model_name"].isin(config.model_order))
    ].copy()
    rows = _ordered_models(rows, config)
    columns = [
        "model_name",
        "row_count",
        "raw_brier",
        "reliability",
        "resolution",
        "uncertainty",
        "decomposed_brier",
        "binning_residual",
        "nonempty_bin_count",
        "empty_bin_count",
        "sparse_bin_count",
        "status",
    ]
    return rows[[column for column in columns if column in rows.columns]].copy()


def _limitations_table(
    raw_summary: dict[str, Any],
    walkforward_summary: dict[str, Any],
    edge_summary: dict[str, Any],
    inference_summary: dict[str, Any],
    decomposition_summary: dict[str, Any],
    config: ReportingConfig,
) -> pd.DataFrame:
    rows: list[dict[str, str]] = [
        {
            "source": "reporting",
            "limitation": (
                "Manuscript outputs are generated from saved artifacts only; no model "
                "fitting is performed by figure/table code."
            ),
        },
        {
            "source": "reporting",
            "limitation": f"Artifact run label: {config.artifact_run_label}.",
        },
    ]
    for source, summary in (
        ("raw_baseline", raw_summary),
        ("walkforward", walkforward_summary),
        ("edge_simulation", edge_summary),
        ("inference", inference_summary),
        ("decomposition", decomposition_summary),
    ):
        for limitation in summary.get("limitations", []):
            rows.append({"source": source, "limitation": str(limitation)})
    return pd.DataFrame(rows)


def _add_score_inference_columns(
    rows: pd.DataFrame,
    score_intervals: pd.DataFrame,
    paired_differences: pd.DataFrame,
    *,
    grouping_name: str,
) -> pd.DataFrame:
    output = rows.copy()
    metric_specs = (
        ("brier_score", "brier_score", "brier_delta"),
        ("log_loss", "log_loss", "log_loss_delta"),
        ("expected_calibration_error", "ece", "ece_delta"),
    )
    score_rows = score_intervals[score_intervals["grouping_name"] == grouping_name].copy()
    paired_rows = paired_differences[
        paired_differences["grouping_name"] == grouping_name
    ].copy()
    for metric_name, score_prefix, delta_prefix in metric_specs:
        score_metric = score_rows[score_rows["metric_name"] == metric_name][
            [
                "model_name",
                "group_key",
                "ci_lower",
                "ci_upper",
                "cluster_count",
                "effective_cluster_count",
                "bootstrap_status",
            ]
        ].rename(
            columns={
                "ci_lower": f"{score_prefix}_ci_lower",
                "ci_upper": f"{score_prefix}_ci_upper",
                "bootstrap_status": f"{score_prefix}_bootstrap_status",
            }
        )
        if not score_metric.empty:
            output = output.merge(
                score_metric,
                on=["model_name", "group_key"],
                how="left",
                validate="one_to_one",
                suffixes=("", f"_{score_prefix}"),
            )
        paired_metric = paired_rows[paired_rows["metric_name"] == metric_name][
            [
                "model_name",
                "group_key",
                "ci_lower",
                "ci_upper",
                "p_value",
                "q_value",
                "reject_fdr",
                "bootstrap_status",
            ]
        ].rename(
            columns={
                "ci_lower": f"{delta_prefix}_ci_lower",
                "ci_upper": f"{delta_prefix}_ci_upper",
                "p_value": f"{delta_prefix}_p_value",
                "q_value": f"{delta_prefix}_q_value",
                "reject_fdr": f"{delta_prefix}_reject_fdr",
                "bootstrap_status": f"{delta_prefix}_bootstrap_status",
            }
        )
        if not paired_metric.empty:
            output = output.merge(
                paired_metric,
                on=["model_name", "group_key"],
                how="left",
                validate="one_to_one",
            )
    if "cluster_count" not in output.columns:
        output["cluster_count"] = pd.NA
    if "effective_cluster_count" not in output.columns:
        output["effective_cluster_count"] = pd.NA
    for column in _score_inference_columns():
        if column not in output.columns:
            output[column] = pd.NA
    return output


def _add_calibration_inference_columns(
    rows: pd.DataFrame,
    calibration_intervals: pd.DataFrame,
) -> pd.DataFrame:
    output = rows.copy()
    source = calibration_intervals[calibration_intervals["grouping_name"] == "horizon"].copy()
    for parameter in ("calibration_intercept", "calibration_slope"):
        metric = source[source["parameter"] == parameter][
            [
                "model_name",
                "group_key",
                "ci_lower",
                "ci_upper",
                "p_value",
                "cluster_count",
                "effective_cluster_count",
                "bootstrap_status",
            ]
        ].rename(
            columns={
                "ci_lower": f"{parameter}_ci_lower",
                "ci_upper": f"{parameter}_ci_upper",
                "p_value": f"{parameter}_p_value",
                "bootstrap_status": f"{parameter}_bootstrap_status",
            }
        )
        if not metric.empty:
            output = output.merge(
                metric,
                on=["model_name", "group_key"],
                how="left",
                validate="one_to_one",
                suffixes=("", f"_{parameter}"),
            )
    if "cluster_count" not in output.columns:
        output["cluster_count"] = pd.NA
    if "effective_cluster_count" not in output.columns:
        output["effective_cluster_count"] = pd.NA
    for column in (
        "calibration_intercept_ci_lower",
        "calibration_intercept_ci_upper",
        "calibration_intercept_p_value",
        "calibration_slope_ci_lower",
        "calibration_slope_ci_upper",
        "calibration_slope_p_value",
    ):
        if column not in output.columns:
            output[column] = pd.NA
    return output


def _score_inference_columns() -> tuple[str, ...]:
    return (
        "brier_score_ci_lower",
        "brier_score_ci_upper",
        "brier_delta_ci_lower",
        "brier_delta_ci_upper",
        "brier_delta_p_value",
        "brier_delta_q_value",
        "log_loss_ci_lower",
        "log_loss_ci_upper",
        "log_loss_delta_ci_lower",
        "log_loss_delta_ci_upper",
        "log_loss_delta_p_value",
        "log_loss_delta_q_value",
        "ece_ci_lower",
        "ece_ci_upper",
        "ece_delta_ci_lower",
        "ece_delta_ci_upper",
        "ece_delta_p_value",
        "ece_delta_q_value",
    )


def _metric_rows(
    aggregate: pd.DataFrame,
    config: ReportingConfig,
    *,
    grouping_name: str,
) -> pd.DataFrame:
    rows = aggregate[
        (aggregate["metric_scope"] == config.metric_scope)
        & (aggregate["grouping_name"] == grouping_name)
    ].copy()
    if rows.empty:
        raise ReportingError(
            f"no aggregate metric rows for scope={config.metric_scope}, "
            f"grouping={grouping_name}"
        )
    if grouping_name == "horizon" and "horizon_name" not in rows.columns:
        rows["horizon_name"] = rows["group_key"]
    return rows


def _add_raw_deltas(
    frame: pd.DataFrame,
    group_columns: tuple[str, ...] = (),
) -> pd.DataFrame:
    rows = frame.copy()
    metrics = (
        ("brier_score", "brier_delta_vs_raw"),
        ("log_loss", "log_loss_delta_vs_raw"),
        ("expected_calibration_error", "ece_delta_vs_raw"),
    )
    if group_columns:
        for _, group in rows.groupby(list(group_columns), dropna=False, observed=True):
            raw = group[group["model_name"] == "raw"]
            if raw.empty:
                continue
            raw_row = raw.iloc[0]
            for metric, output in metrics:
                rows.loc[group.index, output] = group[metric].astype(float) - float(raw_row[metric])
    else:
        raw = rows[rows["model_name"] == "raw"]
        if not raw.empty:
            raw_row = raw.iloc[0]
            for metric, output in metrics:
                rows[output] = rows[metric].astype(float) - float(raw_row[metric])
    for _, output in metrics:
        if output not in rows.columns:
            rows[output] = pd.NA
    return rows


def _ordered_models(frame: pd.DataFrame, config: ReportingConfig) -> pd.DataFrame:
    rows = frame.copy()
    order = {name: index for index, name in enumerate(config.model_order)}
    rows["model_order"] = rows["model_name"].map(order).fillna(len(order))
    return rows.sort_values(["model_order", "model_name"]).copy()


def _ordered_horizons(frame: pd.DataFrame, config: ReportingConfig) -> pd.DataFrame:
    rows = frame.copy()
    rows["horizon_name"] = pd.Categorical(
        rows["horizon_name"].astype(str),
        categories=list(config.horizon_order),
        ordered=True,
    )
    return rows.sort_values(["horizon_name"]).copy()


def _write_table(frame: pd.DataFrame, config: ReportingConfig, stem: str) -> list[Path]:
    paths: list[Path] = []
    for table_format in config.table_formats:
        path = config.table_dir / f"{stem}.{_table_suffix(table_format)}"
        if table_format == "csv":
            frame.to_csv(path, index=False)
        elif table_format == "markdown":
            path.write_text(_to_markdown(frame), encoding="utf-8")
        elif table_format == "latex":
            path.write_text(_to_latex(frame), encoding="utf-8")
        else:
            raise ReportingError(f"unsupported table format: {table_format}")
        paths.append(path)
    return paths


def _to_markdown(frame: pd.DataFrame) -> str:
    columns = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(_format_markdown_value(value) for value in row) + " |")
    return "\n".join(lines) + "\n"


def _to_latex(frame: pd.DataFrame) -> str:
    column_spec = "l" * len(frame.columns)
    lines = [
        f"\\begin{{tabular}}{{{column_spec}}}",
        "\\toprule",
        " & ".join(_escape_latex(str(column)) for column in frame.columns) + r" \\",
        "\\midrule",
    ]
    for row in frame.itertuples(index=False, name=None):
        row_text = " & ".join(_escape_latex(_format_latex_value(value)) for value in row)
        lines.append(row_text + r" \\")
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    return "\n".join(lines)


def _format_markdown_value(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _format_latex_value(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _escape_latex(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in value)


def _table_suffix(table_format: str) -> str:
    return {"csv": "csv", "markdown": "md", "latex": "tex"}[table_format]


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _common_limitations(config: ReportingConfig) -> list[str]:
    return [
        "Manuscript outputs consume saved result artifacts and do not recompute core models.",
        "Domain/category manuscript outputs remain exploratory because taxonomy coverage "
        "includes lower-confidence title rules plus ambiguous and unknown rows.",
        "Edge outputs are simulated expected-value screens, not executable trading profits.",
        "Score intervals and p-values use event-family clustered inference artifacts.",
        "Murphy decomposition uses binned saved predictions and reports the binning residual.",
        f"Artifact run label is {config.artifact_run_label}.",
    ]


def _validate_reporting_config(
    config: ReportingConfig,
    *,
    require_figures: bool,
    require_tables: bool,
) -> None:
    validate_required_artifacts(config)
    if config.reliability_bin_count <= 0:
        raise ReportingError("reliability_bin_count must be positive")
    if config.reliability_min_bin_count < 0:
        raise ReportingError("reliability_min_bin_count cannot be negative")
    if config.dpi <= 0:
        raise ReportingError("dpi must be positive")
    if require_figures:
        _validate_formats(config.figure_formats, {"png", "svg", "pdf"}, "figure")
    if require_tables:
        _validate_formats(config.table_formats, {"csv", "markdown", "latex"}, "table")


def _validate_formats(
    formats: tuple[str, ...],
    allowed: set[str],
    kind: str,
) -> None:
    if not formats:
        raise ReportingError(f"at least one {kind} format is required")
    unsupported = sorted(set(formats) - allowed)
    if unsupported:
        raise ReportingError(f"unsupported {kind} formats: {unsupported}")


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"reporting config missing mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"reporting config missing required key: {key}")
    return raw[key]
