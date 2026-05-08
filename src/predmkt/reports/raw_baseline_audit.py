"""Diagnostic audit for raw baseline calibration patterns."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from predmkt.metrics.calibration import fit_calibration_intercept_slope
from predmkt.metrics.scoring import clip_probability

SECONDS_PER_MINUTE = 60
DEFAULT_HORIZONS = ("30d", "14d", "7d", "3d", "1d", "6h", "1h", "close")
METRIC_COLUMNS = ("brier_score", "log_loss", "expected_calibration_error")


@dataclass(frozen=True)
class RawBaselineAuditConfig:
    """Configuration for raw baseline diagnostics."""

    modeling_panel_path: Path
    price_observations_path: Path
    contracts_path: Path
    raw_baseline_artifact_dir: Path
    audit_dir: Path
    horizons: tuple[str, ...]
    close_and_near_horizons: tuple[str, ...]
    staleness_thresholds_seconds: tuple[int, ...]
    strict_vwap_windows_seconds: tuple[int, ...]
    strict_max_staleness_seconds: tuple[int, ...]
    log_loss_epsilon: float
    reliability_bin_count: int
    calibration_min_rows: int
    calibration_max_iterations: int
    calibration_tolerance: float
    figure_formats: tuple[str, ...]
    figure_dpi: int
    close_stale_flag_threshold_seconds: int
    config_path: Path | None = None
    config_sha256: str | None = None


@dataclass(frozen=True)
class RawBaselineAuditSummary:
    """Summary of generated raw baseline audit artifacts."""

    audit_dir: str
    input_row_count: int
    balanced_contract_count: int
    balanced_row_count: int
    staleness_artifact: str
    snapshot_method_artifact: str
    strict_variant_artifact: str
    balanced_artifact: str
    orientation_artifact: str
    close_semantics_artifact: str
    close_stale_flags_artifact: str
    figure_paths: dict[str, list[str]]
    findings: dict[str, Any]
    limitations: list[str]
    effective_config: dict[str, Any]


class RawBaselineAuditError(ValueError):
    """Raised when raw baseline audit inputs are invalid."""


def load_raw_baseline_audit_config(path: Path) -> RawBaselineAuditConfig:
    """Load audit configuration from YAML."""

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"audit config must be a mapping: {path}")
    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    audit = _mapping(raw, "audit")
    epsilon = float(_required(audit, "log_loss_epsilon"))
    if not 0.0 < epsilon < 0.5:
        raise ValueError("audit.log_loss_epsilon must be in (0, 0.5)")
    return RawBaselineAuditConfig(
        modeling_panel_path=Path(_required(inputs, "modeling_panel_path")),
        price_observations_path=Path(_required(inputs, "price_observations_path")),
        contracts_path=Path(_required(inputs, "contracts_path")),
        raw_baseline_artifact_dir=Path(_required(inputs, "raw_baseline_artifact_dir")),
        audit_dir=Path(_required(outputs, "audit_dir")),
        horizons=tuple(str(value) for value in audit.get("horizons", DEFAULT_HORIZONS)),
        close_and_near_horizons=tuple(
            str(value) for value in audit.get("close_and_near_horizons", ("1h", "close"))
        ),
        staleness_thresholds_seconds=tuple(
            int(value) for value in _required(audit, "staleness_thresholds_seconds")
        ),
        strict_vwap_windows_seconds=tuple(
            int(value) for value in _required(audit, "strict_vwap_windows_seconds")
        ),
        strict_max_staleness_seconds=tuple(
            int(value) for value in _required(audit, "strict_max_staleness_seconds")
        ),
        log_loss_epsilon=epsilon,
        reliability_bin_count=int(_required(audit, "reliability_bin_count")),
        calibration_min_rows=int(_required(audit, "calibration_min_rows")),
        calibration_max_iterations=int(_required(audit, "calibration_max_iterations")),
        calibration_tolerance=float(_required(audit, "calibration_tolerance")),
        figure_formats=tuple(str(value) for value in audit.get("figure_formats", ("png", "svg"))),
        figure_dpi=int(audit.get("figure_dpi", 180)),
        close_stale_flag_threshold_seconds=int(
            _required(audit, "close_stale_flag_threshold_seconds")
        ),
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def build_raw_baseline_audit(config: RawBaselineAuditConfig) -> RawBaselineAuditSummary:
    """Build all raw baseline diagnostic audit artifacts."""

    _validate_config(config)
    config.audit_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = config.audit_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    _set_plot_style()

    panel = _load_panel(config)
    staleness = staleness_diagnostics(panel, config)
    method_counts = snapshot_method_counts(panel, config)
    method_metrics = snapshot_method_metrics(panel, config)
    strict_variants = strict_snapshot_variant_metrics(config)
    balanced = balanced_horizon_metrics(panel, config)
    orientation = orientation_diagnostics(panel)
    close_semantics = close_timestamp_semantics(panel, config)
    close_stale = close_stale_flags(panel, config)

    artifacts = _artifact_paths(config.audit_dir)
    staleness.to_parquet(artifacts["staleness"], index=False)
    method_counts.to_parquet(artifacts["snapshot_method_counts"], index=False)
    method_metrics.to_parquet(artifacts["snapshot_method_metrics"], index=False)
    strict_variants.to_parquet(artifacts["strict_variants"], index=False)
    balanced.to_parquet(artifacts["balanced_metrics"], index=False)
    orientation.to_parquet(artifacts["orientation"], index=False)
    close_semantics.to_parquet(artifacts["close_semantics"], index=False)
    close_stale.to_parquet(artifacts["close_stale_flags"], index=False)

    figure_paths = {
        "staleness_percentiles": _save_figure(
            _plot_staleness_percentiles(staleness, config),
            figures_dir,
            config,
            "staleness_percentiles_by_horizon",
        ),
        "snapshot_method_mix": _save_figure(
            _plot_method_mix(method_counts, config),
            figures_dir,
            config,
            "snapshot_method_mix_by_horizon",
        ),
        "snapshot_method_metrics": _save_figure(
            _plot_method_metrics(method_metrics, config),
            figures_dir,
            config,
            "snapshot_method_metrics_by_horizon",
        ),
        "strict_variants": _save_figure(
            _plot_strict_variants(strict_variants),
            figures_dir,
            config,
            "strict_close_1h_variant_metrics",
        ),
        "balanced_comparison": _save_figure(
            _plot_balanced_comparison(balanced, config),
            figures_dir,
            config,
            "balanced_vs_unbalanced_horizon_metrics",
        ),
        "close_semantics": _save_figure(
            _plot_close_semantics(close_semantics),
            figures_dir,
            config,
            "close_timestamp_semantics",
        ),
    }

    balanced_contract_count = int(
        balanced.loc[balanced["panel_type"] == "balanced", "contract_count"].max()
        if not balanced.empty
        else 0
    )
    summary = RawBaselineAuditSummary(
        audit_dir=str(config.audit_dir),
        input_row_count=len(panel),
        balanced_contract_count=balanced_contract_count,
        balanced_row_count=balanced_contract_count * len(config.horizons),
        staleness_artifact=str(artifacts["staleness"]),
        snapshot_method_artifact=str(artifacts["snapshot_method_metrics"]),
        strict_variant_artifact=str(artifacts["strict_variants"]),
        balanced_artifact=str(artifacts["balanced_metrics"]),
        orientation_artifact=str(artifacts["orientation"]),
        close_semantics_artifact=str(artifacts["close_semantics"]),
        close_stale_flags_artifact=str(artifacts["close_stale_flags"]),
        figure_paths={key: [str(path) for path in paths] for key, paths in figure_paths.items()},
        findings=_findings(
            panel,
            staleness,
            strict_variants,
            balanced,
            orientation,
            close_semantics,
        ),
        limitations=[
            "Diagnostics do not change the confirmatory methodology or baseline artifacts.",
            "Strict close/1h variants are sensitivity diagnostics, not a new selected model.",
            "Resolution timestamp is the cleaned contract resolution_ts, which currently "
            "comes from Becker/Kalshi close_time; no separate raw close_time is retained "
            "in the cleaned contracts table or modeling panel.",
            "Snapshot prices are transaction-derived YES-side probabilities; historical "
            "quote midpoint or executable quote data are unavailable.",
        ],
        effective_config=_effective_config(config),
    )
    (config.audit_dir / "audit_summary.json").write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def staleness_diagnostics(
    panel: pd.DataFrame,
    config: RawBaselineAuditConfig,
) -> pd.DataFrame:
    """Summarize staleness by horizon and snapshot method."""

    rows: list[dict[str, Any]] = []
    for split_name, columns in (
        ("all", ["horizon_name"]),
        ("snapshot_method", ["horizon_name", "snapshot_method"]),
    ):
        for keys, group in panel.groupby(columns, dropna=False):
            key_tuple = keys if isinstance(keys, tuple) else (keys,)
            row = {
                "split": split_name,
                "horizon_name": key_tuple[0],
                "snapshot_method": key_tuple[1] if len(key_tuple) > 1 else "all",
                "row_count": len(group),
                "median_staleness_seconds": group["staleness_seconds"].median(),
                "p75_staleness_seconds": group["staleness_seconds"].quantile(0.75),
                "p90_staleness_seconds": group["staleness_seconds"].quantile(0.90),
                "p95_staleness_seconds": group["staleness_seconds"].quantile(0.95),
                "p99_staleness_seconds": group["staleness_seconds"].quantile(0.99),
            }
            for threshold in config.staleness_thresholds_seconds:
                row[f"share_staleness_gt_{threshold}s"] = (
                    group["staleness_seconds"].gt(threshold).mean()
                )
            rows.append(row)
    return _order_horizon_frame(pd.DataFrame(rows), config)


def snapshot_method_counts(
    panel: pd.DataFrame,
    config: RawBaselineAuditConfig,
) -> pd.DataFrame:
    """Count rows by horizon and snapshot method."""

    counts = (
        panel.groupby(["horizon_name", "snapshot_method"], dropna=False)
        .size()
        .reset_index(name="row_count")
    )
    totals = counts.groupby("horizon_name", dropna=False)["row_count"].transform("sum")
    counts["share_of_horizon"] = counts["row_count"] / totals
    return _order_horizon_frame(counts, config)


def snapshot_method_metrics(
    panel: pd.DataFrame,
    config: RawBaselineAuditConfig,
) -> pd.DataFrame:
    """Compute metrics by horizon and snapshot method."""

    return metric_table(
        panel,
        ["horizon_name", "snapshot_method"],
        probability_column="raw_probability",
        outcome_column="observed_outcome",
        config=config,
    )


def balanced_horizon_metrics(
    panel: pd.DataFrame,
    config: RawBaselineAuditConfig,
) -> pd.DataFrame:
    """Compare unbalanced horizon metrics with complete-horizon contract subset."""

    contract_horizon_counts = panel.groupby("contract_id")["horizon_name"].nunique()
    balanced_ids = contract_horizon_counts[contract_horizon_counts == len(config.horizons)].index
    balanced_panel = panel[panel["contract_id"].isin(balanced_ids)].copy()
    unbalanced = metric_table(
        panel,
        ["horizon_name"],
        probability_column="raw_probability",
        outcome_column="observed_outcome",
        config=config,
    )
    unbalanced["panel_type"] = "unbalanced"
    balanced = metric_table(
        balanced_panel,
        ["horizon_name"],
        probability_column="raw_probability",
        outcome_column="observed_outcome",
        config=config,
    )
    balanced["panel_type"] = "balanced"
    return _order_horizon_frame(pd.concat([unbalanced, balanced], ignore_index=True), config)


def orientation_diagnostics(panel: pd.DataFrame) -> pd.DataFrame:
    """Validate YES-side price and outcome orientation by result label."""

    rows: list[dict[str, Any]] = []
    for outcome, group in panel.groupby("outcome", dropna=False):
        expected = 1 if outcome == "yes" else 0 if outcome == "no" else None
        bad_outcome_count = len(group) if expected is None else int(
            (group["observed_outcome"] != expected).sum()
        )
        rows.append(
            {
                "outcome": outcome,
                "row_count": len(group),
                "expected_observed_outcome": expected,
                "observed_outcome_min": group["observed_outcome"].min(),
                "observed_outcome_max": group["observed_outcome"].max(),
                "observed_outcome_mean": group["observed_outcome"].mean(),
                "bad_outcome_mapping_count": bad_outcome_count,
                "snapshot_price_min": group["snapshot_price"].min(),
                "snapshot_price_max": group["snapshot_price"].max(),
                "snapshot_price_mean": group["snapshot_price"].mean(),
                "invalid_snapshot_price_count": int(
                    (~group["snapshot_price"].between(0.0, 1.0)).sum()
                ),
                "construction_note": (
                    "snapshot_price is constructed from cleaned yes_price/vwap yes_price "
                    "fields, so it is a YES-side probability proxy."
                ),
            }
        )
    return pd.DataFrame(rows)


def close_timestamp_semantics(
    panel: pd.DataFrame,
    config: RawBaselineAuditConfig,
) -> pd.DataFrame:
    """Audit close horizon timestamp spacing and stale close snapshots."""

    close = panel[panel["horizon_name"] == "close"].copy()
    if close.empty:
        return pd.DataFrame()
    contract_times = _load_contract_timestamp_columns(config)
    if not contract_times.empty:
        close = close.merge(contract_times, on="contract_id", how="left")
    close["resolution_minus_forecast_seconds"] = (
        close["resolution_ts"] - close["forecast_ts"]
    ).dt.total_seconds()
    close["resolution_minus_price_timestamp_seconds"] = (
        close["resolution_ts"] - close["price_timestamp"]
    ).dt.total_seconds()
    close["resolution_minus_last_trade_seconds"] = (
        close["resolution_ts"] - close["last_trade_ts"]
    ).dt.total_seconds()
    rows: list[dict[str, Any]] = []
    for method, group in close.groupby("snapshot_method", dropna=False):
        has_contract_resolution = (
            "contract_resolution_ts" in group.columns
            and group["contract_resolution_ts"].notna().any()
        )
        has_close_time = "close_time" in group.columns and group["close_time"].notna().any()
        row = {
            "snapshot_method": method,
            "row_count": len(group),
            "contract_resolution_ts_available": bool(has_contract_resolution),
            "close_time_available": bool(has_close_time),
            "median_resolution_minus_forecast_seconds": group[
                "resolution_minus_forecast_seconds"
            ].median(),
            "median_resolution_minus_price_timestamp_seconds": group[
                "resolution_minus_price_timestamp_seconds"
            ].median(),
            "p90_resolution_minus_price_timestamp_seconds": group[
                "resolution_minus_price_timestamp_seconds"
            ].quantile(0.90),
            "p95_resolution_minus_price_timestamp_seconds": group[
                "resolution_minus_price_timestamp_seconds"
            ].quantile(0.95),
            "p99_resolution_minus_price_timestamp_seconds": group[
                "resolution_minus_price_timestamp_seconds"
            ].quantile(0.99),
            "median_resolution_minus_last_trade_seconds": group[
                "resolution_minus_last_trade_seconds"
            ].median(),
            "share_price_timestamp_before_forecast": group["price_timestamp"]
            .lt(group["forecast_ts"])
            .mean(),
            "share_price_timestamp_at_forecast": group["price_timestamp"]
            .eq(group["forecast_ts"])
            .mean(),
            "share_staleness_gt_flag_threshold": group["staleness_seconds"]
            .gt(config.close_stale_flag_threshold_seconds)
            .mean(),
            "close_time_note": (
                "close_time is compared only if retained in the cleaned contracts table; "
                "otherwise resolution_ts is the available cleaned resolution proxy."
            ),
        }
        if has_contract_resolution:
            row["share_panel_resolution_matches_contract_resolution"] = group[
                "resolution_ts"
            ].eq(group["contract_resolution_ts"]).mean()
            row["median_contract_resolution_minus_price_timestamp_seconds"] = (
                group["contract_resolution_ts"] - group["price_timestamp"]
            ).dt.total_seconds().median()
        else:
            row["share_panel_resolution_matches_contract_resolution"] = None
            row["median_contract_resolution_minus_price_timestamp_seconds"] = None
        if has_close_time:
            row["median_resolution_minus_close_time_seconds"] = (
                group["resolution_ts"] - group["close_time"]
            ).dt.total_seconds().median()
            row["median_close_time_minus_price_timestamp_seconds"] = (
                group["close_time"] - group["price_timestamp"]
            ).dt.total_seconds().median()
        else:
            row["median_resolution_minus_close_time_seconds"] = None
            row["median_close_time_minus_price_timestamp_seconds"] = None
        for threshold in config.staleness_thresholds_seconds:
            row[f"share_staleness_gt_{threshold}s"] = (
                group["staleness_seconds"].gt(threshold).mean()
            )
        rows.append(row)
    return pd.DataFrame(rows)


def close_stale_flags(
    panel: pd.DataFrame,
    config: RawBaselineAuditConfig,
) -> pd.DataFrame:
    """Return close rows whose selected price is stale beyond the configured flag threshold."""

    columns = [
        "contract_id",
        "event_id",
        "outcome",
        "observed_outcome",
        "snapshot_method",
        "forecast_ts",
        "resolution_ts",
        "last_trade_ts",
        "price_timestamp",
        "staleness_seconds",
        "last_trade_staleness_seconds",
        "snapshot_price",
        "last_trade_price",
        "vwap_price",
        "vwap_trade_count",
        "vwap_volume",
    ]
    close = panel[
        (panel["horizon_name"] == "close")
        & (panel["staleness_seconds"] > config.close_stale_flag_threshold_seconds)
    ].copy()
    close["resolution_minus_price_timestamp_seconds"] = (
        close["resolution_ts"] - close["price_timestamp"]
    ).dt.total_seconds()
    return close[[*columns, "resolution_minus_price_timestamp_seconds"]].sort_values(
        "staleness_seconds",
        ascending=False,
    )


def strict_snapshot_variant_metrics(config: RawBaselineAuditConfig) -> pd.DataFrame:
    """Recompute close/1h snapshot sensitivities under stricter settings."""

    base = _load_close_near_base(config)
    rows: list[pd.DataFrame] = []
    for max_staleness in config.strict_max_staleness_seconds:
        rows.append(_last_trade_variant_metrics(base, max_staleness, config))
    for vwap_window in config.strict_vwap_windows_seconds:
        vwap = _vwap_for_window(config, vwap_window)
        merged = base.merge(vwap, on=["contract_id", "horizon_name"], how="left")
        for max_staleness in config.strict_max_staleness_seconds:
            rows.append(_vwap_variant_metrics(merged, vwap_window, max_staleness, config))
    return pd.concat(rows, ignore_index=True)


def metric_table(
    frame: pd.DataFrame,
    group_columns: list[str],
    *,
    probability_column: str,
    outcome_column: str,
    config: RawBaselineAuditConfig,
) -> pd.DataFrame:
    """Compute Brier, log loss, ECE, and calibration fit for groups."""

    if frame.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    grouped = frame.groupby(group_columns, dropna=False) if group_columns else [((), frame)]
    for keys, group in grouped:
        key_tuple = keys if isinstance(keys, tuple) else (keys,)
        probabilities = group[probability_column].astype(float)
        outcomes = group[outcome_column].astype(float)
        clipped = probabilities.map(
            lambda value: clip_probability(float(value), config.log_loss_epsilon)
        )
        brier = ((probabilities - outcomes) ** 2).mean()
        log_loss = -(
            outcomes * clipped.map(math.log)
            + (1.0 - outcomes) * (1.0 - clipped).map(math.log)
        ).mean()
        fit = fit_calibration_intercept_slope(
            probabilities.tolist(),
            outcomes.tolist(),
            epsilon=config.log_loss_epsilon,
            min_rows=config.calibration_min_rows,
            max_iterations=config.calibration_max_iterations,
            tolerance=config.calibration_tolerance,
        )
        row: dict[str, Any] = {
            column: key_tuple[index] for index, column in enumerate(group_columns)
        }
        row.update(
            {
                "row_count": len(group),
                "contract_count": group["contract_id"].nunique()
                if "contract_id" in group.columns
                else None,
                "event_family_count": group["event_family_id"].nunique()
                if "event_family_id" in group.columns
                else None,
                "brier_score": brier,
                "log_loss": log_loss,
                "expected_calibration_error": _ece(
                    probabilities,
                    outcomes,
                    bin_count=config.reliability_bin_count,
                ),
                "calibration_intercept": fit.intercept,
                "calibration_slope": fit.slope,
                "calibration_status": fit.status,
                "calibration_converged": fit.converged,
            }
        )
        rows.append(row)
    return _order_horizon_frame(pd.DataFrame(rows), config)


def _load_panel(config: RawBaselineAuditConfig) -> pd.DataFrame:
    columns = [
        "contract_id",
        "event_id",
        "event_family_id",
        "outcome",
        "observed_outcome",
        "horizon_name",
        "forecast_ts",
        "resolution_ts",
        "snapshot_method",
        "snapshot_price",
        "raw_probability",
        "last_trade_price",
        "last_trade_ts",
        "last_trade_staleness_seconds",
        "price_timestamp",
        "staleness_seconds",
        "vwap_price",
        "vwap_trade_count",
        "vwap_volume",
    ]
    panel = pd.read_parquet(config.modeling_panel_path, columns=columns)
    missing = [column for column in columns if column not in panel.columns]
    if missing:
        raise RawBaselineAuditError(f"modeling panel missing audit columns: {missing}")
    return panel


def _load_close_near_base(config: RawBaselineAuditConfig) -> pd.DataFrame:
    horizon_sql = ", ".join(_sql_string(value) for value in config.close_and_near_horizons)
    return duckdb.sql(
        f"""
        SELECT
            contract_id,
            event_id,
            event_family_id,
            outcome,
            observed_outcome,
            horizon_name,
            forecast_ts,
            resolution_ts,
            last_trade_price,
            last_trade_ts,
            last_trade_staleness_seconds
        FROM read_parquet({_sql_string(config.modeling_panel_path)})
        WHERE horizon_name IN ({horizon_sql})
        """
    ).df()


def _load_contract_timestamp_columns(config: RawBaselineAuditConfig) -> pd.DataFrame:
    """Load optional contract timestamp columns for close semantics diagnostics."""

    if not config.contracts_path.exists():
        return pd.DataFrame()
    contracts = pd.read_parquet(config.contracts_path)
    if "contract_id" not in contracts.columns:
        return pd.DataFrame()
    columns = ["contract_id"]
    if "resolution_ts" in contracts.columns:
        columns.append("resolution_ts")
    if "close_time" in contracts.columns:
        columns.append("close_time")
    result = contracts[columns].copy()
    if "resolution_ts" in result.columns:
        result = result.rename(columns={"resolution_ts": "contract_resolution_ts"})
        result["contract_resolution_ts"] = pd.to_datetime(
            result["contract_resolution_ts"],
            utc=True,
        )
    if "close_time" in result.columns:
        result["close_time"] = pd.to_datetime(result["close_time"], utc=True)
    return result


def _vwap_for_window(config: RawBaselineAuditConfig, vwap_window_seconds: int) -> pd.DataFrame:
    horizon_sql = ", ".join(_sql_string(value) for value in config.close_and_near_horizons)
    return duckdb.sql(
        f"""
        WITH base AS (
            SELECT contract_id, horizon_name, forecast_ts
            FROM read_parquet({_sql_string(config.modeling_panel_path)})
            WHERE horizon_name IN ({horizon_sql})
        )
        SELECT
            b.contract_id,
            b.horizon_name,
            sum(p.yes_price * p.volume) / nullif(sum(p.volume), 0) AS variant_vwap_price,
            count(*) AS variant_vwap_trade_count,
            sum(p.volume) AS variant_vwap_volume,
            max(p.source_ts) AS variant_vwap_price_timestamp
        FROM base AS b
        JOIN read_parquet({_sql_string(config.price_observations_path)}) AS p
          ON p.contract_id = b.contract_id
         AND p.source_ts <= b.forecast_ts
         AND p.source_ts >= b.forecast_ts - INTERVAL {vwap_window_seconds} SECOND
        GROUP BY b.contract_id, b.horizon_name
        """
    ).df()


def _last_trade_variant_metrics(
    base: pd.DataFrame,
    max_staleness_seconds: int,
    config: RawBaselineAuditConfig,
) -> pd.DataFrame:
    selected = base[base["last_trade_staleness_seconds"] <= max_staleness_seconds].copy()
    selected["variant_probability"] = selected["last_trade_price"]
    selected["variant_staleness_seconds"] = selected["last_trade_staleness_seconds"]
    metrics = metric_table(
        selected,
        ["horizon_name"],
        probability_column="variant_probability",
        outcome_column="observed_outcome",
        config=config,
    )
    metrics["variant_family"] = "last_trade_only"
    metrics["vwap_window_seconds"] = None
    metrics["max_staleness_seconds"] = max_staleness_seconds
    metrics["selected_snapshot_method"] = "last_trade"
    return metrics


def _vwap_variant_metrics(
    merged: pd.DataFrame,
    vwap_window_seconds: int,
    max_staleness_seconds: int,
    config: RawBaselineAuditConfig,
) -> pd.DataFrame:
    selected = merged.copy()
    has_vwap = selected["variant_vwap_trade_count"].notna()
    selected["variant_probability"] = selected["last_trade_price"]
    selected.loc[has_vwap, "variant_probability"] = selected.loc[has_vwap, "variant_vwap_price"]
    selected["variant_price_timestamp"] = selected["last_trade_ts"]
    selected.loc[has_vwap, "variant_price_timestamp"] = selected.loc[
        has_vwap, "variant_vwap_price_timestamp"
    ]
    selected["variant_staleness_seconds"] = (
        selected["forecast_ts"] - selected["variant_price_timestamp"]
    ).dt.total_seconds()
    selected["variant_snapshot_method"] = "last_trade"
    selected.loc[has_vwap, "variant_snapshot_method"] = "vwap"
    selected = selected[selected["variant_staleness_seconds"] <= max_staleness_seconds]
    overall = metric_table(
        selected,
        ["horizon_name"],
        probability_column="variant_probability",
        outcome_column="observed_outcome",
        config=config,
    )
    overall["selected_snapshot_method"] = "all"
    split = metric_table(
        selected,
        ["horizon_name", "variant_snapshot_method"],
        probability_column="variant_probability",
        outcome_column="observed_outcome",
        config=config,
    )
    split["selected_snapshot_method"] = split["variant_snapshot_method"]
    metrics = pd.concat([overall, split], ignore_index=True)
    metrics["variant_family"] = "vwap_preferred"
    metrics["vwap_window_seconds"] = vwap_window_seconds
    metrics["max_staleness_seconds"] = max_staleness_seconds
    return metrics


def _ece(probabilities: pd.Series, outcomes: pd.Series, *, bin_count: int) -> float:
    bins = (probabilities * bin_count).astype(int).clip(lower=0, upper=bin_count - 1)
    total = len(probabilities)
    ece = 0.0
    for _, index in bins.groupby(bins).groups.items():
        bin_probabilities = probabilities.loc[index]
        bin_outcomes = outcomes.loc[index]
        ece += (len(bin_probabilities) / total) * abs(
            bin_probabilities.mean() - bin_outcomes.mean()
        )
    return float(ece)


def _plot_staleness_percentiles(
    staleness: pd.DataFrame,
    config: RawBaselineAuditConfig,
) -> Figure:
    rows = staleness[staleness["snapshot_method"] == "all"].copy()
    rows = _order_horizon_frame(rows, config)
    fig, ax = plt.subplots(figsize=(9.5, 5.2), constrained_layout=True)
    for column, label in (
        ("median_staleness_seconds", "median"),
        ("p90_staleness_seconds", "p90"),
        ("p95_staleness_seconds", "p95"),
        ("p99_staleness_seconds", "p99"),
    ):
        ax.plot(
            rows["horizon_name"],
            rows[column] / SECONDS_PER_MINUTE,
            marker="o",
            linewidth=1.8,
            label=label,
        )
    ax.set_title("Snapshot Staleness by Horizon")
    ax.set_ylabel("Staleness minutes")
    ax.set_xlabel("Horizon")
    ax.grid(axis="y", color="#d1d5db", linewidth=0.8, alpha=0.8)
    ax.legend(frameon=False)
    return fig


def _plot_method_mix(counts: pd.DataFrame, config: RawBaselineAuditConfig) -> Figure:
    pivot = counts.pivot(index="horizon_name", columns="snapshot_method", values="share_of_horizon")
    pivot = pivot.reindex(config.horizons).fillna(0.0)
    fig, ax = plt.subplots(figsize=(9.5, 5.2), constrained_layout=True)
    bottom = pd.Series(0.0, index=pivot.index)
    for method in pivot.columns:
        ax.bar(pivot.index, pivot[method], bottom=bottom, label=method, alpha=0.86)
        bottom += pivot[method]
    ax.set_title("Snapshot Method Mix by Horizon")
    ax.set_ylabel("Share of horizon rows")
    ax.set_xlabel("Horizon")
    ax.set_ylim(0, 1.0)
    ax.legend(frameon=False)
    return fig


def _plot_method_metrics(metrics: pd.DataFrame, config: RawBaselineAuditConfig) -> Figure:
    fig, axes = plt.subplots(3, 1, figsize=(10.0, 8.5), sharex=True, constrained_layout=True)
    for ax, column in zip(axes, METRIC_COLUMNS, strict=True):
        pivot = metrics.pivot(index="horizon_name", columns="snapshot_method", values=column)
        pivot = pivot.reindex(config.horizons)
        pivot.plot(kind="bar", ax=ax, alpha=0.86)
        ax.set_title(column.replace("_", " ").title(), loc="left")
        ax.set_ylabel("Score")
        ax.grid(axis="y", color="#d1d5db", linewidth=0.8, alpha=0.8)
        ax.legend(frameon=False)
    axes[-1].set_xlabel("Horizon")
    fig.suptitle("Raw Baseline Metrics by Snapshot Method", fontweight="bold")
    return fig


def _plot_strict_variants(metrics: pd.DataFrame) -> Figure:
    rows = metrics[
        (metrics["variant_family"] == "vwap_preferred")
        & (metrics["selected_snapshot_method"] == "all")
    ].copy()
    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.8), constrained_layout=True)
    for ax, horizon in zip(axes, ("1h", "close"), strict=True):
        horizon_rows = rows[rows["horizon_name"] == horizon]
        pivot = horizon_rows.pivot_table(
            index="max_staleness_seconds",
            columns="vwap_window_seconds",
            values="expected_calibration_error",
            aggfunc="mean",
        )
        _heatmap(ax, pivot, title=f"{horizon}: ECE by VWAP window and max stale")
    return fig


def _plot_balanced_comparison(
    metrics: pd.DataFrame,
    config: RawBaselineAuditConfig,
) -> Figure:
    fig, axes = plt.subplots(3, 1, figsize=(9.8, 8.2), sharex=True, constrained_layout=True)
    for ax, column in zip(axes, METRIC_COLUMNS, strict=True):
        pivot = metrics.pivot(index="horizon_name", columns="panel_type", values=column)
        pivot = pivot.reindex(config.horizons)
        pivot.plot(kind="bar", ax=ax, alpha=0.86)
        ax.set_title(column.replace("_", " ").title(), loc="left")
        ax.set_ylabel("Score")
        ax.grid(axis="y", color="#d1d5db", linewidth=0.8, alpha=0.8)
        ax.legend(frameon=False)
    axes[-1].set_xlabel("Horizon")
    fig.suptitle("Unbalanced vs Complete-Horizon Contract Subset", fontweight="bold")
    return fig


def _plot_close_semantics(close_semantics: pd.DataFrame) -> Figure:
    fig, ax = plt.subplots(figsize=(8.4, 4.8), constrained_layout=True)
    if not close_semantics.empty:
        values = close_semantics.set_index("snapshot_method")[
            [
                "median_resolution_minus_price_timestamp_seconds",
                "p95_resolution_minus_price_timestamp_seconds",
                "p99_resolution_minus_price_timestamp_seconds",
            ]
        ] / SECONDS_PER_MINUTE
        values.plot(kind="bar", ax=ax, alpha=0.86)
    ax.set_title("Close Horizon Timestamp Gap")
    ax.set_ylabel("Minutes from selected price timestamp to resolution_ts")
    ax.set_xlabel("Snapshot method")
    ax.grid(axis="y", color="#d1d5db", linewidth=0.8, alpha=0.8)
    ax.legend(frameon=False)
    return fig


def _heatmap(ax: Axes, pivot: pd.DataFrame, *, title: str) -> None:
    if pivot.empty:
        ax.set_title(title)
        ax.text(0.5, 0.5, "No rows", transform=ax.transAxes, ha="center", va="center")
        return
    image = ax.imshow(pivot.to_numpy(), cmap="viridis", aspect="auto")
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("VWAP window seconds")
    ax.set_ylabel("Max staleness seconds")
    ax.set_xticks(range(len(pivot.columns)), [str(int(value)) for value in pivot.columns])
    ax.set_yticks(range(len(pivot.index)), [str(int(value)) for value in pivot.index])
    for row_index, index_value in enumerate(pivot.index):
        for col_index, column_value in enumerate(pivot.columns):
            value = pivot.loc[index_value, column_value]
            if pd.notna(value):
                ax.text(col_index, row_index, f"{value:.3f}", ha="center", va="center", fontsize=8)
    plt.colorbar(image, ax=ax, fraction=0.046, pad=0.04)


def _findings(
    panel: pd.DataFrame,
    staleness: pd.DataFrame,
    strict_variants: pd.DataFrame,
    balanced: pd.DataFrame,
    orientation: pd.DataFrame,
    close_semantics: pd.DataFrame,
) -> dict[str, Any]:
    close_all = staleness[
        (staleness["horizon_name"] == "close") & (staleness["snapshot_method"] == "all")
    ]
    one_hour_all = staleness[
        (staleness["horizon_name"] == "1h") & (staleness["snapshot_method"] == "all")
    ]
    return {
        "close_row_count": int((panel["horizon_name"] == "close").sum()),
        "one_hour_row_count": int((panel["horizon_name"] == "1h").sum()),
        "close_median_staleness_seconds": _first_or_none(close_all, "median_staleness_seconds"),
        "one_hour_median_staleness_seconds": _first_or_none(
            one_hour_all,
            "median_staleness_seconds",
        ),
        "orientation_bad_outcome_mapping_count": int(
            orientation["bad_outcome_mapping_count"].sum()
        ),
        "orientation_invalid_snapshot_price_count": int(
            orientation["invalid_snapshot_price_count"].sum()
        ),
        "strict_variant_row_count": int(strict_variants["row_count"].sum())
        if not strict_variants.empty
        else 0,
        "balanced_panel_types": sorted(balanced["panel_type"].dropna().unique().tolist())
        if not balanced.empty
        else [],
        "close_timestamp_semantics_rows": close_semantics.to_dict(orient="records"),
        "interpretation_note": (
            "Diagnostics distinguish near-close calibration patterns from staleness, "
            "snapshot-method, and balanced-panel composition effects. They do not by "
            "themselves select a revised methodology."
        ),
    }


def _artifact_paths(audit_dir: Path) -> dict[str, Path]:
    return {
        "staleness": audit_dir / "staleness_by_horizon_method.parquet",
        "snapshot_method_counts": audit_dir / "snapshot_method_counts.parquet",
        "snapshot_method_metrics": audit_dir / "snapshot_method_metrics.parquet",
        "strict_variants": audit_dir / "strict_close_1h_variant_metrics.parquet",
        "balanced_metrics": audit_dir / "balanced_horizon_metrics.parquet",
        "orientation": audit_dir / "orientation_sanity_by_outcome.parquet",
        "close_semantics": audit_dir / "close_timestamp_semantics.parquet",
        "close_stale_flags": audit_dir / "close_stale_flags.parquet",
    }


def _save_figure(
    fig: Figure,
    figures_dir: Path,
    config: RawBaselineAuditConfig,
    stem: str,
) -> list[Path]:
    paths: list[Path] = []
    for figure_format in config.figure_formats:
        path = figures_dir / f"{stem}.{figure_format}"
        fig.savefig(path, dpi=config.figure_dpi, bbox_inches="tight", facecolor="white")
        paths.append(path)
    plt.close(fig)
    return paths


def _set_plot_style() -> None:
    plt.rcParams.update(
        {
            "axes.facecolor": "white",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "savefig.facecolor": "white",
        }
    )


def _order_horizon_frame(frame: pd.DataFrame, config: RawBaselineAuditConfig) -> pd.DataFrame:
    if frame.empty or "horizon_name" not in frame.columns:
        return frame
    result = frame.copy()
    result["horizon_name"] = pd.Categorical(
        result["horizon_name"],
        categories=list(config.horizons),
        ordered=True,
    )
    sort_columns = ["horizon_name"]
    for column in ("snapshot_method", "variant_family", "max_staleness_seconds"):
        if column in result.columns:
            sort_columns.append(column)
    return result.sort_values(sort_columns).reset_index(drop=True)


def _validate_config(config: RawBaselineAuditConfig) -> None:
    if not config.modeling_panel_path.exists():
        raise RawBaselineAuditError(f"missing modeling panel: {config.modeling_panel_path}")
    if not config.price_observations_path.exists():
        raise RawBaselineAuditError(
            f"missing price observations: {config.price_observations_path}"
        )
    if config.reliability_bin_count <= 0:
        raise RawBaselineAuditError("reliability_bin_count must be positive")
    unsupported_formats = sorted(set(config.figure_formats) - {"png", "svg", "pdf"})
    if unsupported_formats:
        raise RawBaselineAuditError(f"unsupported figure formats: {unsupported_formats}")


def _effective_config(config: RawBaselineAuditConfig) -> dict[str, Any]:
    return {
        "inputs": {
            "modeling_panel_path": str(config.modeling_panel_path),
            "price_observations_path": str(config.price_observations_path),
            "contracts_path": str(config.contracts_path),
            "raw_baseline_artifact_dir": str(config.raw_baseline_artifact_dir),
        },
        "outputs": {"audit_dir": str(config.audit_dir)},
        "audit": {
            "horizons": list(config.horizons),
            "close_and_near_horizons": list(config.close_and_near_horizons),
            "staleness_thresholds_seconds": list(config.staleness_thresholds_seconds),
            "strict_vwap_windows_seconds": list(config.strict_vwap_windows_seconds),
            "strict_max_staleness_seconds": list(config.strict_max_staleness_seconds),
            "log_loss_epsilon": config.log_loss_epsilon,
            "reliability_bin_count": config.reliability_bin_count,
            "calibration_min_rows": config.calibration_min_rows,
            "figure_formats": list(config.figure_formats),
            "figure_dpi": config.figure_dpi,
            "close_stale_flag_threshold_seconds": config.close_stale_flag_threshold_seconds,
        },
        "config_path": str(config.config_path) if config.config_path else None,
        "config_sha256": config.config_sha256,
    }


def _first_or_none(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty:
        return None
    value = frame.iloc[0][column]
    return None if pd.isna(value) else float(value)


def _sql_string(path_or_value: Path | str) -> str:
    return "'" + str(path_or_value).replace("'", "''") + "'"


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"audit config missing mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"audit config missing required key: {key}")
    return raw[key]
