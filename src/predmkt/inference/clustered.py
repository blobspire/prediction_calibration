"""Cluster bootstrap inference from saved walk-forward prediction artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]

from predmkt.metrics.calibration import fit_calibration_intercept_slope
from predmkt.metrics.reliability import expected_calibration_error, reliability_bins
from predmkt.metrics.scoring import brier_score, clip_probability, log_loss


@dataclass(frozen=True)
class InferenceConfig:
    """Config for clustered uncertainty inference."""

    predictions_path: Path
    panel_path: Path
    aggregate_metrics_path: Path
    fold_metrics_path: Path
    artifact_dir: Path
    row_id_column: str
    contract_column: str
    horizon_column: str
    cluster_column: str
    outcome_column: str
    raw_probability_column: str
    predicted_probability_column: str
    baseline_model: str
    comparison_models: tuple[str, ...]
    bootstrap_unit: str
    bootstrap_iterations: int
    confidence_level: float
    random_seed: int
    min_rows: int
    min_clusters: int
    fdr_alpha: float
    log_loss_epsilon: float
    reliability_bin_count: int
    reliability_min_bin_count: int
    calibration_min_rows: int
    calibration_max_iterations: int
    calibration_tolerance: float
    groupings: tuple[dict[str, Any], ...]
    calibration_groupings: tuple[dict[str, Any], ...]
    bucket_specs: dict[str, dict[str, Any]]
    config_path: Path | None = None
    config_sha256: str | None = None


@dataclass(frozen=True)
class InferenceSummary:
    """Summary of clustered inference artifacts."""

    artifact_dir: str
    predictions_path: str
    panel_path: str
    input_prediction_row_count: int
    joined_prediction_row_count: int
    model_names: list[str]
    cluster_column: str
    cluster_count: int
    bootstrap_unit: str
    bootstrap_iterations: int
    confidence_level: float
    fdr_alpha: float
    artifact_paths: dict[str, str]
    config_sha256: str | None
    git_commit: str | None
    git_dirty: bool | None
    effective_config: dict[str, Any]
    limitations: list[str]


class InferenceError(ValueError):
    """Raised when inference inputs violate confirmatory invariants."""


def load_inference_config(path: Path) -> InferenceConfig:
    """Load clustered inference settings from YAML."""

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"inference config must be a mapping: {path}")
    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    columns = _mapping(raw, "columns")
    inference = _mapping(raw, "inference")
    return InferenceConfig(
        predictions_path=Path(_required(inputs, "predictions_path")),
        panel_path=Path(_required(inputs, "panel_path")),
        aggregate_metrics_path=Path(_required(inputs, "aggregate_metrics_path")),
        fold_metrics_path=Path(_required(inputs, "fold_metrics_path")),
        artifact_dir=Path(_required(outputs, "artifact_dir")),
        row_id_column=str(_required(columns, "row_id_column")),
        contract_column=str(_required(columns, "contract_column")),
        horizon_column=str(_required(columns, "horizon_column")),
        cluster_column=str(_required(columns, "cluster_column")),
        outcome_column=str(_required(columns, "outcome_column")),
        raw_probability_column=str(_required(columns, "raw_probability_column")),
        predicted_probability_column=str(_required(columns, "predicted_probability_column")),
        baseline_model=str(_required(inference, "baseline_model")),
        comparison_models=tuple(str(item) for item in _required(inference, "comparison_models")),
        bootstrap_unit=str(_required(inference, "bootstrap_unit")),
        bootstrap_iterations=int(_required(inference, "bootstrap_iterations")),
        confidence_level=float(_required(inference, "confidence_level")),
        random_seed=int(_required(inference, "random_seed")),
        min_rows=int(_required(inference, "min_rows")),
        min_clusters=int(_required(inference, "min_clusters")),
        fdr_alpha=float(_required(inference, "fdr_alpha")),
        log_loss_epsilon=float(_required(inference, "log_loss_epsilon")),
        reliability_bin_count=int(_required(inference, "reliability_bin_count")),
        reliability_min_bin_count=int(_required(inference, "reliability_min_bin_count")),
        calibration_min_rows=int(_required(inference, "calibration_min_rows")),
        calibration_max_iterations=int(_required(inference, "calibration_max_iterations")),
        calibration_tolerance=float(_required(inference, "calibration_tolerance")),
        groupings=tuple(_grouping(item) for item in _required(inference, "groupings")),
        calibration_groupings=tuple(
            _grouping(item) for item in _required(inference, "calibration_groupings")
        ),
        bucket_specs=dict(inference.get("buckets", {})),
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def run_inference(config: InferenceConfig) -> InferenceSummary:
    """Run clustered inference on saved walk-forward predictions."""

    _validate_config(config)
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    paths = _artifact_paths(config.artifact_dir)
    predictions = _load_joined_predictions(config)
    model_names = sorted(predictions["model_name"].astype(str).unique().tolist())
    clusters = int(predictions[config.cluster_column].nunique())
    rng = np.random.default_rng(config.random_seed)

    score_rows, score_replicates = _score_intervals(predictions, config, rng)
    paired_rows, paired_replicates = _paired_score_differences(predictions, config, rng)
    calibration_rows, calibration_replicates = _calibration_intervals(predictions, config, rng)
    adjustments = _multiple_comparison_adjustments(paired_rows, config)
    paired_rows = paired_rows.merge(
        adjustments[
            [
                "model_name",
                "metric_name",
                "grouping_name",
                "group_key",
                "q_value",
                "reject_fdr",
            ]
        ],
        on=["model_name", "metric_name", "grouping_name", "group_key"],
        how="left",
        validate="one_to_one",
    )
    diagnostics = _paired_loss_diagnostics(predictions, config)
    replicates = pd.concat(
        [score_replicates, paired_replicates, calibration_replicates],
        ignore_index=True,
    )

    score_rows.to_parquet(paths["score_intervals"], index=False)
    paired_rows.to_parquet(paths["paired_score_differences"], index=False)
    calibration_rows.to_parquet(paths["calibration_intervals"], index=False)
    adjustments.to_parquet(paths["multiple_comparison_adjustments"], index=False)
    diagnostics.to_parquet(paths["paired_loss_diagnostics"], index=False)
    replicates.to_parquet(paths["bootstrap_replicates"], index=False)

    git_commit, git_dirty = _git_state()
    summary = InferenceSummary(
        artifact_dir=str(config.artifact_dir),
        predictions_path=str(config.predictions_path),
        panel_path=str(config.panel_path),
        input_prediction_row_count=int(len(pd.read_parquet(config.predictions_path))),
        joined_prediction_row_count=int(len(predictions)),
        model_names=model_names,
        cluster_column=config.cluster_column,
        cluster_count=clusters,
        bootstrap_unit=config.bootstrap_unit,
        bootstrap_iterations=config.bootstrap_iterations,
        confidence_level=config.confidence_level,
        fdr_alpha=config.fdr_alpha,
        artifact_paths={key: str(path) for key, path in paths.items()},
        config_sha256=config.config_sha256,
        git_commit=git_commit,
        git_dirty=git_dirty,
        effective_config=effective_inference_config(config),
        limitations=[
            "Inference consumes saved walk-forward prediction artifacts and does not refit "
            "calibrators or rebuild data.",
            "Confirmatory intervals resample audited event-family clusters, not iid rows "
            "or trades.",
            "Point estimates remain equal-contract over contract-horizon prediction rows.",
            "Domain/category inference remains conditional on taxonomy confidence, ambiguity, "
            "and unknown-rate audits.",
        ],
    )
    paths["summary"].write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return summary


def benjamini_hochberg(p_values: list[float], *, alpha: float) -> tuple[list[float], list[bool]]:
    """Return Benjamini-Hochberg q-values and rejection flags."""

    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    if not p_values:
        return [], []
    indexed = sorted(enumerate(float(value) for value in p_values), key=lambda item: item[1])
    count = len(indexed)
    adjusted_sorted = [1.0] * count
    running = 1.0
    for reverse_rank, (original_index, p_value) in enumerate(reversed(indexed), start=1):
        rank = count - reverse_rank + 1
        adjusted = min(running, p_value * count / rank)
        running = adjusted
        adjusted_sorted[rank - 1] = adjusted
        del original_index
    q_values = [1.0] * count
    reject = [False] * count
    for sorted_index, (original_index, _) in enumerate(indexed):
        q_values[original_index] = min(max(adjusted_sorted[sorted_index], 0.0), 1.0)
        reject[original_index] = q_values[original_index] <= alpha
    return q_values, reject


def effective_cluster_count(cluster_sizes: Sequence[int | float]) -> float:
    """Return Kish effective cluster count from cluster row counts."""

    if not cluster_sizes:
        return 0.0
    sizes = [float(value) for value in cluster_sizes]
    total = sum(sizes)
    denominator = sum(value * value for value in sizes)
    if denominator <= 0.0:
        return 0.0
    return total * total / denominator


def effective_inference_config(config: InferenceConfig) -> dict[str, Any]:
    """Return JSON-serializable effective config values."""

    return {
        "inputs": {
            "predictions_path": str(config.predictions_path),
            "panel_path": str(config.panel_path),
            "aggregate_metrics_path": str(config.aggregate_metrics_path),
            "fold_metrics_path": str(config.fold_metrics_path),
        },
        "outputs": {"artifact_dir": str(config.artifact_dir)},
        "columns": {
            "row_id_column": config.row_id_column,
            "contract_column": config.contract_column,
            "horizon_column": config.horizon_column,
            "cluster_column": config.cluster_column,
            "outcome_column": config.outcome_column,
            "raw_probability_column": config.raw_probability_column,
            "predicted_probability_column": config.predicted_probability_column,
        },
        "inference": {
            "baseline_model": config.baseline_model,
            "comparison_models": list(config.comparison_models),
            "bootstrap_unit": config.bootstrap_unit,
            "bootstrap_iterations": config.bootstrap_iterations,
            "confidence_level": config.confidence_level,
            "random_seed": config.random_seed,
            "min_rows": config.min_rows,
            "min_clusters": config.min_clusters,
            "fdr_alpha": config.fdr_alpha,
            "log_loss_epsilon": config.log_loss_epsilon,
            "reliability_bin_count": config.reliability_bin_count,
            "reliability_min_bin_count": config.reliability_min_bin_count,
            "calibration_min_rows": config.calibration_min_rows,
            "calibration_max_iterations": config.calibration_max_iterations,
            "calibration_tolerance": config.calibration_tolerance,
            "groupings": list(config.groupings),
            "calibration_groupings": list(config.calibration_groupings),
            "buckets": config.bucket_specs,
        },
        "config_path": str(config.config_path) if config.config_path else None,
        "config_sha256": config.config_sha256,
    }


def _load_joined_predictions(config: InferenceConfig) -> pd.DataFrame:
    predictions = pd.read_parquet(config.predictions_path)
    _require_columns(
        predictions,
        [
            "model_name",
            config.row_id_column,
            config.contract_column,
            config.cluster_column,
            config.horizon_column,
            "forecast_ts",
            "resolution_ts",
            config.outcome_column,
            config.raw_probability_column,
            config.predicted_probability_column,
        ],
        "predictions",
    )
    panel_columns = [
        config.contract_column,
        config.cluster_column,
        config.horizon_column,
        "forecast_ts",
        "resolution_ts",
        "domain",
        "category",
        "taxonomy_confidence",
        "taxonomy_ambiguous",
        "is_sports",
        "public_liquidity_proxy",
        "price_staleness_seconds",
    ]
    panel = pd.read_parquet(config.panel_path, columns=panel_columns).reset_index(
        names=config.row_id_column
    )
    joined = predictions.merge(
        panel,
        on=config.row_id_column,
        how="left",
        suffixes=("", "_panel"),
        validate="many_to_one",
    )
    if joined[f"{config.contract_column}_panel"].isna().any():
        raise InferenceError("predictions reference row_ids missing from modeling panel")
    _validate_prediction_panel_keys(joined, config)
    joined = _coalesce_panel_columns(joined, config)
    joined["forecast_ts"] = pd.to_datetime(joined["forecast_ts"], utc=True, errors="raise")
    joined["resolution_ts"] = pd.to_datetime(joined["resolution_ts"], utc=True, errors="raise")
    joined[config.outcome_column] = pd.to_numeric(joined[config.outcome_column], errors="raise")
    joined[config.predicted_probability_column] = pd.to_numeric(
        joined[config.predicted_probability_column],
        errors="raise",
    )
    if not joined[config.predicted_probability_column].between(0.0, 1.0).all():
        raise InferenceError("predicted probabilities must be in [0, 1]")
    if not joined[config.outcome_column].isin([0, 1]).all():
        raise InferenceError("observed outcomes must be binary 0/1")
    for bucket_name, spec in config.bucket_specs.items():
        joined[bucket_name] = _bucket_series(joined, spec)
    _validate_identical_test_rows(joined, config)
    return joined


def _score_intervals(
    predictions: pd.DataFrame,
    config: InferenceConfig,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    replicate_rows: list[pd.DataFrame] = []
    for grouping in config.groupings:
        for key, frame in _iter_groups(predictions, grouping):
            for model_name, model_frame in frame.groupby("model_name", observed=True):
                metrics = _metric_point_estimates(model_frame, config)
                cluster_stats = _cluster_metric_stats(model_frame, config)
                status = _bootstrap_status(model_frame, config)
                for metric_name, estimate in metrics.items():
                    replicates = (
                        _bootstrap_metric_replicates(cluster_stats, metric_name, config, rng)
                        if status == "ok"
                        else []
                    )
                    lower, upper = _confidence_interval(replicates, config)
                    p_value = _two_sided_bootstrap_p_value(replicates, 0.0, estimate)
                    rows.append(
                        {
                            "model_name": str(model_name),
                            "metric_name": metric_name,
                            "grouping_name": str(grouping["name"]),
                            "group_key": key,
                            "estimate": estimate,
                            "ci_lower": lower,
                            "ci_upper": upper,
                            "p_value": p_value,
                            "row_count": int(len(model_frame)),
                            "cluster_count": int(model_frame[config.cluster_column].nunique()),
                            "effective_cluster_count": effective_cluster_count(
                                _cluster_sizes(model_frame, config)
                            ),
                            "bootstrap_iterations": len(replicates),
                            "bootstrap_status": status,
                            "bootstrap_unit": config.bootstrap_unit,
                            "ci_method": "event_family_cluster_bootstrap",
                            "aggregation_mode": "equal_contract",
                        }
                    )
                    replicate_rows.append(
                        _replicate_frame(
                            replicates,
                            artifact_kind="score_interval",
                            model_name=str(model_name),
                            metric_name=metric_name,
                            grouping_name=str(grouping["name"]),
                            group_key=key,
                        )
                    )
    return pd.DataFrame(rows), _concat_replicates(replicate_rows)


def _paired_score_differences(
    predictions: pd.DataFrame,
    config: InferenceConfig,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    replicate_rows: list[pd.DataFrame] = []
    for grouping in config.groupings:
        for key, frame in _iter_groups(predictions, grouping):
            raw = frame[frame["model_name"] == config.baseline_model]
            if raw.empty:
                continue
            for model_name in config.comparison_models:
                other = frame[frame["model_name"] == model_name]
                if other.empty:
                    continue
                paired = _paired_model_frame(raw, other, config)
                status = _bootstrap_status(paired, config)
                stats = _cluster_paired_stats(paired, config)
                estimates = {
                    "brier_score": float(paired["brier_diff"].mean()),
                    "log_loss": float(paired["log_loss_diff"].mean()),
                    "expected_calibration_error": _ece_difference(paired, config),
                }
                for metric_name, estimate in estimates.items():
                    replicates = (
                        _bootstrap_metric_replicates(stats, metric_name, config, rng)
                        if status == "ok"
                        else []
                    )
                    lower, upper = _confidence_interval(replicates, config)
                    rows.append(
                        {
                            "baseline_model": config.baseline_model,
                            "model_name": model_name,
                            "metric_name": metric_name,
                            "grouping_name": str(grouping["name"]),
                            "group_key": key,
                            "estimate_delta": estimate,
                            "ci_lower": lower,
                            "ci_upper": upper,
                            "p_value": _two_sided_bootstrap_p_value(replicates, 0.0, estimate),
                            "row_count": int(len(paired)),
                            "cluster_count": int(paired[config.cluster_column].nunique()),
                            "effective_cluster_count": effective_cluster_count(
                                _cluster_sizes(paired, config)
                            ),
                            "bootstrap_iterations": len(replicates),
                            "bootstrap_status": status,
                            "bootstrap_unit": config.bootstrap_unit,
                            "ci_method": "event_family_cluster_bootstrap",
                            "aggregation_mode": "equal_contract",
                        }
                    )
                    replicate_rows.append(
                        _replicate_frame(
                            replicates,
                            artifact_kind="paired_score_difference",
                            model_name=model_name,
                            metric_name=metric_name,
                            grouping_name=str(grouping["name"]),
                            group_key=key,
                            baseline_model=config.baseline_model,
                        )
                    )
    return pd.DataFrame(rows), _concat_replicates(replicate_rows)


def _calibration_intervals(
    predictions: pd.DataFrame,
    config: InferenceConfig,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    replicate_rows: list[pd.DataFrame] = []
    for grouping in config.calibration_groupings:
        for key, frame in _iter_groups(predictions, grouping):
            for model_name, model_frame in frame.groupby("model_name", observed=True):
                probabilities = model_frame[config.predicted_probability_column].astype(float)
                outcomes = model_frame[config.outcome_column].astype(float)
                fit = fit_calibration_intercept_slope(
                    probabilities.tolist(),
                    outcomes.tolist(),
                    epsilon=config.log_loss_epsilon,
                    min_rows=config.calibration_min_rows,
                    max_iterations=config.calibration_max_iterations,
                    tolerance=config.calibration_tolerance,
                )
                status = _bootstrap_status(model_frame, config)
                if fit.status != "converged":
                    status = fit.status
                reps = (
                    _calibration_influence_replicates(model_frame, config, rng)
                    if status == "ok"
                    else {"calibration_intercept": [], "calibration_slope": []}
                )
                for parameter, estimate, null_value in (
                    ("calibration_intercept", fit.intercept, 0.0),
                    ("calibration_slope", fit.slope, 1.0),
                ):
                    values = reps[parameter]
                    lower, upper = _confidence_interval(values, config)
                    rows.append(
                        {
                            "model_name": str(model_name),
                            "parameter": parameter,
                            "grouping_name": str(grouping["name"]),
                            "group_key": key,
                            "estimate": estimate,
                            "null_value": null_value,
                            "ci_lower": lower,
                            "ci_upper": upper,
                            "p_value": _two_sided_bootstrap_p_value(values, null_value, estimate),
                            "row_count": int(len(model_frame)),
                            "cluster_count": int(model_frame[config.cluster_column].nunique()),
                            "effective_cluster_count": effective_cluster_count(
                                _cluster_sizes(model_frame, config)
                            ),
                            "bootstrap_iterations": len(values),
                            "bootstrap_status": status,
                            "calibration_status": fit.status,
                            "bootstrap_unit": config.bootstrap_unit,
                            "ci_method": "event_family_cluster_influence_bootstrap",
                            "aggregation_mode": "equal_contract",
                        }
                    )
                    replicate_rows.append(
                        _replicate_frame(
                            values,
                            artifact_kind="calibration_interval",
                            model_name=str(model_name),
                            metric_name=parameter,
                            grouping_name=str(grouping["name"]),
                            group_key=key,
                        )
                    )
    return pd.DataFrame(rows), _concat_replicates(replicate_rows)


def _multiple_comparison_adjustments(
    paired: pd.DataFrame,
    config: InferenceConfig,
) -> pd.DataFrame:
    if paired.empty:
        return pd.DataFrame(
            columns=[
                "baseline_model",
                "model_name",
                "metric_name",
                "grouping_name",
                "group_key",
                "p_value",
                "q_value",
                "reject_fdr",
                "fdr_method",
                "fdr_alpha",
            ]
        )
    rows = paired.copy()
    q_values, rejected = benjamini_hochberg(
        rows["p_value"].fillna(1.0).tolist(),
        alpha=config.fdr_alpha,
    )
    rows["q_value"] = q_values
    rows["reject_fdr"] = rejected
    rows["fdr_method"] = "benjamini_hochberg"
    rows["fdr_alpha"] = config.fdr_alpha
    return rows[
        [
            "baseline_model",
            "model_name",
            "metric_name",
            "grouping_name",
            "group_key",
            "p_value",
            "q_value",
            "reject_fdr",
            "fdr_method",
            "fdr_alpha",
        ]
    ].copy()


def _paired_loss_diagnostics(predictions: pd.DataFrame, config: InferenceConfig) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for grouping in config.groupings:
        for key, frame in _iter_groups(predictions, grouping):
            raw = frame[frame["model_name"] == config.baseline_model]
            for model_name in config.comparison_models:
                other = frame[frame["model_name"] == model_name]
                if raw.empty or other.empty:
                    continue
                paired = _paired_model_frame(raw, other, config)
                for metric_name, column in (
                    ("brier_score", "brier_diff"),
                    ("log_loss", "log_loss_diff"),
                ):
                    cluster_values = (
                        paired.groupby(config.cluster_column, observed=True)[column].mean()
                    )
                    cluster_count = int(len(cluster_values))
                    mean_value = float(cluster_values.mean()) if cluster_count else math.nan
                    std = float(cluster_values.std(ddof=1)) if cluster_count > 1 else math.nan
                    se = std / math.sqrt(cluster_count) if cluster_count > 1 else math.nan
                    rows.append(
                        {
                            "baseline_model": config.baseline_model,
                            "model_name": model_name,
                            "metric_name": metric_name,
                            "grouping_name": str(grouping["name"]),
                            "group_key": key,
                            "cluster_count": cluster_count,
                            "mean_cluster_loss_diff": mean_value,
                            "cluster_standard_error": se,
                            "z_stat": mean_value / se if se and math.isfinite(se) else None,
                            "diagnostic_status": "ok" if cluster_count >= 2 else "too_few_clusters",
                        }
                    )
    return pd.DataFrame(rows)


def _metric_point_estimates(frame: pd.DataFrame, config: InferenceConfig) -> dict[str, float]:
    probabilities = frame[config.predicted_probability_column].astype(float).tolist()
    outcomes = frame[config.outcome_column].astype(float).tolist()
    bins = reliability_bins(
        probabilities,
        outcomes,
        bin_count=config.reliability_bin_count,
        min_bin_count=config.reliability_min_bin_count,
    )
    return {
        "brier_score": brier_score(probabilities, outcomes),
        "log_loss": log_loss(probabilities, outcomes, epsilon=config.log_loss_epsilon),
        "expected_calibration_error": expected_calibration_error(bins),
    }


def _cluster_metric_stats(frame: pd.DataFrame, config: InferenceConfig) -> dict[str, Any]:
    rows = frame.copy()
    p = rows[config.predicted_probability_column].astype(float)
    y = rows[config.outcome_column].astype(float)
    rows["brier_loss"] = (p - y) ** 2
    clipped = p.map(lambda value: clip_probability(float(value), config.log_loss_epsilon))
    rows["log_loss_value"] = -(y * np.log(clipped) + (1.0 - y) * np.log(1.0 - clipped))
    rows["probability_bin"] = np.minimum(
        (p * config.reliability_bin_count).astype(int),
        config.reliability_bin_count - 1,
    )
    grouped = rows.groupby(config.cluster_column, observed=True)
    stats = grouped.agg(
        row_count=(config.outcome_column, "size"),
        brier_sum=("brier_loss", "sum"),
        log_loss_sum=("log_loss_value", "sum"),
    ).reset_index()
    bin_stats = (
        rows.groupby([config.cluster_column, "probability_bin"], observed=True)
        .agg(
            bin_count=(config.outcome_column, "size"),
            probability_sum=(config.predicted_probability_column, "sum"),
            outcome_sum=(config.outcome_column, "sum"),
        )
        .reset_index()
    )
    return {
        "cluster_stats": stats,
        "bin_stats": bin_stats,
        "paired": False,
    }


def _cluster_paired_stats(paired: pd.DataFrame, config: InferenceConfig) -> dict[str, Any]:
    stats = (
        paired.groupby(config.cluster_column, observed=True)
        .agg(
            row_count=("brier_diff", "size"),
            brier_sum=("brier_diff", "sum"),
            log_loss_sum=("log_loss_diff", "sum"),
        )
        .reset_index()
    )
    bin_stats = _paired_ece_cluster_bin_stats(paired, config)
    return {
        "cluster_stats": stats,
        "bin_stats": bin_stats,
        "paired": True,
    }


def _bootstrap_metric_replicates(
    stats: dict[str, Any],
    metric_name: str,
    config: InferenceConfig,
    rng: np.random.Generator,
) -> list[float]:
    cluster_stats = stats["cluster_stats"]
    cluster_count = len(cluster_stats)
    if cluster_count < config.min_clusters:
        return []
    if metric_name == "brier_score":
        return _bootstrap_sum_ratio(
            cluster_stats["brier_sum"].to_numpy(float),
            cluster_stats["row_count"].to_numpy(float),
            config,
            rng,
        )
    if metric_name == "log_loss":
        return _bootstrap_sum_ratio(
            cluster_stats["log_loss_sum"].to_numpy(float),
            cluster_stats["row_count"].to_numpy(float),
            config,
            rng,
        )
    if metric_name == "expected_calibration_error":
        return _bootstrap_ece_replicates(stats["bin_stats"], config, rng, paired=stats["paired"])
    raise InferenceError(f"unknown metric for bootstrap: {metric_name}")


def _bootstrap_sum_ratio(
    numerators: np.ndarray,
    denominators: np.ndarray,
    config: InferenceConfig,
    rng: np.random.Generator,
) -> list[float]:
    cluster_count = len(numerators)
    values: list[float] = []
    for _ in range(config.bootstrap_iterations):
        counts = rng.multinomial(cluster_count, np.full(cluster_count, 1.0 / cluster_count))
        denominator = float(np.dot(counts, denominators))
        values.append(float(np.dot(counts, numerators) / denominator))
    return values


def _bootstrap_ece_replicates(
    bin_stats: pd.DataFrame,
    config: InferenceConfig,
    rng: np.random.Generator,
    *,
    paired: bool,
) -> list[float]:
    clusters = sorted(bin_stats[config.cluster_column].astype(str).unique().tolist())
    cluster_index = {cluster: index for index, cluster in enumerate(clusters)}
    cluster_count = len(clusters)
    if cluster_count < config.min_clusters:
        return []
    arrays = _ece_arrays(bin_stats, config, cluster_index, paired=paired)
    values: list[float] = []
    for _ in range(config.bootstrap_iterations):
        counts = rng.multinomial(cluster_count, np.full(cluster_count, 1.0 / cluster_count))
        values.append(_ece_from_weighted_arrays(arrays, counts, paired=paired))
    return values


def _calibration_influence_replicates(
    frame: pd.DataFrame,
    config: InferenceConfig,
    rng: np.random.Generator,
) -> dict[str, list[float]]:
    probabilities = frame[config.predicted_probability_column].astype(float).tolist()
    outcomes = frame[config.outcome_column].astype(float).tolist()
    fit = fit_calibration_intercept_slope(
        probabilities,
        outcomes,
        epsilon=config.log_loss_epsilon,
        min_rows=config.calibration_min_rows,
        max_iterations=config.calibration_max_iterations,
        tolerance=config.calibration_tolerance,
    )
    if fit.intercept is None or fit.slope is None:
        return {"calibration_intercept": [], "calibration_slope": []}
    x = np.array([
        math.log(
            clip_probability(float(probability), config.log_loss_epsilon)
            / (1.0 - clip_probability(float(probability), config.log_loss_epsilon))
        )
        for probability in probabilities
    ])
    y = np.array(outcomes, dtype=float)
    eta = fit.intercept + fit.slope * x
    mu = 1.0 / (1.0 + np.exp(-eta))
    residual = y - mu
    weight = np.maximum(mu * (1.0 - mu), 1e-12)
    h00 = float(weight.sum())
    h01 = float((weight * x).sum())
    h11 = float((weight * x * x).sum())
    determinant = h00 * h11 - h01 * h01
    if abs(determinant) <= 1e-12:
        return {"calibration_intercept": [], "calibration_slope": []}
    inv_hessian = np.array([[h11, -h01], [-h01, h00]], dtype=float) / determinant
    scores = pd.DataFrame(
        {
            config.cluster_column: frame[config.cluster_column].astype(str).to_numpy(),
            "score_intercept": residual,
            "score_slope": residual * x,
        }
    )
    cluster_scores = (
        scores.groupby(config.cluster_column, observed=True)[["score_intercept", "score_slope"]]
        .sum()
        .to_numpy(float)
    )
    cluster_count = len(cluster_scores)
    values: dict[str, list[float]] = {
        "calibration_intercept": [],
        "calibration_slope": [],
    }
    for _ in range(config.bootstrap_iterations):
        counts = rng.multinomial(cluster_count, np.full(cluster_count, 1.0 / cluster_count))
        score_delta = (counts - 1.0) @ cluster_scores
        beta_delta = inv_hessian @ score_delta
        values["calibration_intercept"].append(float(fit.intercept + beta_delta[0]))
        values["calibration_slope"].append(float(fit.slope + beta_delta[1]))
    return values


def _paired_model_frame(
    raw: pd.DataFrame,
    other: pd.DataFrame,
    config: InferenceConfig,
) -> pd.DataFrame:
    keep = [
        config.row_id_column,
        config.cluster_column,
        config.outcome_column,
        config.horizon_column,
        "domain",
        "category",
        "liquidity_bucket",
        "staleness_bucket",
    ]
    keep = [column for column in keep if column in raw.columns]
    raw_small = raw[keep + [config.predicted_probability_column]].rename(
        columns={config.predicted_probability_column: "baseline_probability"}
    )
    other_small = other[[config.row_id_column, config.predicted_probability_column]].rename(
        columns={config.predicted_probability_column: "model_probability"}
    )
    paired = raw_small.merge(
        other_small,
        on=config.row_id_column,
        how="inner",
        validate="one_to_one",
    )
    if len(paired) != len(raw_small) or len(paired) != len(other_small):
        raise InferenceError("raw and recalibrated models do not have identical paired row IDs")
    y = paired[config.outcome_column].astype(float)
    baseline = paired["baseline_probability"].astype(float)
    model = paired["model_probability"].astype(float)
    paired["brier_diff"] = (model - y) ** 2 - (baseline - y) ** 2
    base_clip = baseline.map(lambda value: clip_probability(float(value), config.log_loss_epsilon))
    model_clip = model.map(lambda value: clip_probability(float(value), config.log_loss_epsilon))
    paired["log_loss_diff"] = (
        -(y * np.log(model_clip) + (1.0 - y) * np.log(1.0 - model_clip))
        + (y * np.log(base_clip) + (1.0 - y) * np.log(1.0 - base_clip))
    )
    return paired


def _ece_difference(paired: pd.DataFrame, config: InferenceConfig) -> float:
    outcomes = paired[config.outcome_column].astype(float).tolist()
    model_bins = reliability_bins(
        paired["model_probability"].astype(float).tolist(),
        outcomes,
        bin_count=config.reliability_bin_count,
        min_bin_count=config.reliability_min_bin_count,
    )
    raw_bins = reliability_bins(
        paired["baseline_probability"].astype(float).tolist(),
        outcomes,
        bin_count=config.reliability_bin_count,
        min_bin_count=config.reliability_min_bin_count,
    )
    return expected_calibration_error(model_bins) - expected_calibration_error(raw_bins)


def _paired_ece_cluster_bin_stats(paired: pd.DataFrame, config: InferenceConfig) -> pd.DataFrame:
    rows = []
    for side, column in (("model", "model_probability"), ("baseline", "baseline_probability")):
        frame = paired[[config.cluster_column, column, config.outcome_column]].copy()
        p = frame[column].astype(float)
        frame["probability_bin"] = np.minimum(
            (p * config.reliability_bin_count).astype(int),
            config.reliability_bin_count - 1,
        )
        grouped = (
            frame.groupby([config.cluster_column, "probability_bin"], observed=True)
            .agg(
                bin_count=(config.outcome_column, "size"),
                probability_sum=(column, "sum"),
                outcome_sum=(config.outcome_column, "sum"),
            )
            .reset_index()
        )
        grouped["side"] = side
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True)


def _ece_arrays(
    bin_stats: pd.DataFrame,
    config: InferenceConfig,
    cluster_index: dict[str, int],
    *,
    paired: bool,
) -> dict[str, np.ndarray]:
    sides = ["model", "baseline"] if paired else ["model"]
    arrays: dict[str, np.ndarray] = {}
    for side in sides:
        source = bin_stats if not paired else bin_stats[bin_stats["side"] == side]
        count = np.zeros((len(cluster_index), config.reliability_bin_count))
        probability = np.zeros_like(count)
        outcome = np.zeros_like(count)
        for row in source.itertuples(index=False):
            cluster = str(getattr(row, config.cluster_column))
            idx = cluster_index[cluster]
            bin_idx = int(row.probability_bin)
            count[idx, bin_idx] += float(row.bin_count)
            probability[idx, bin_idx] += float(row.probability_sum)
            outcome[idx, bin_idx] += float(row.outcome_sum)
        arrays[f"{side}_count"] = count
        arrays[f"{side}_probability"] = probability
        arrays[f"{side}_outcome"] = outcome
    return arrays


def _ece_from_weighted_arrays(
    arrays: dict[str, np.ndarray],
    counts: np.ndarray,
    *,
    paired: bool,
) -> float:
    model_ece = _single_ece_from_arrays(
        counts @ arrays["model_count"],
        counts @ arrays["model_probability"],
        counts @ arrays["model_outcome"],
    )
    if not paired:
        return model_ece
    baseline_ece = _single_ece_from_arrays(
        counts @ arrays["baseline_count"],
        counts @ arrays["baseline_probability"],
        counts @ arrays["baseline_outcome"],
    )
    return model_ece - baseline_ece


def _single_ece_from_arrays(
    bin_counts: np.ndarray,
    probability_sums: np.ndarray,
    outcome_sums: np.ndarray,
) -> float:
    total = float(bin_counts.sum())
    if total <= 0.0:
        return math.nan
    ece = 0.0
    for count, probability_sum, outcome_sum in zip(
        bin_counts,
        probability_sums,
        outcome_sums,
        strict=True,
    ):
        if count <= 0.0:
            continue
        ece += (count / total) * abs(probability_sum / count - outcome_sum / count)
    return float(ece)


def _bootstrap_status(frame: pd.DataFrame, config: InferenceConfig) -> str:
    if len(frame) < config.min_rows:
        return "too_few_rows"
    if frame[config.cluster_column].nunique() < config.min_clusters:
        return "too_few_clusters"
    return "ok"


def _confidence_interval(
    values: list[float],
    config: InferenceConfig,
) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    alpha = 1.0 - config.confidence_level
    lower = float(np.quantile(values, alpha / 2.0))
    upper = float(np.quantile(values, 1.0 - alpha / 2.0))
    return lower, upper


def _two_sided_bootstrap_p_value(
    values: list[float],
    null_value: float,
    estimate: float | None,
) -> float | None:
    if not values or estimate is None or not math.isfinite(float(estimate)):
        return None
    centered = [value - null_value for value in values]
    estimate_centered = float(estimate) - null_value
    if estimate_centered == 0.0:
        return 1.0
    if estimate_centered > 0.0:
        tail = sum(value <= 0.0 for value in centered) / len(centered)
    else:
        tail = sum(value >= 0.0 for value in centered) / len(centered)
    return min(1.0, max(0.0, 2.0 * tail))


def _replicate_frame(
    values: list[float],
    *,
    artifact_kind: str,
    model_name: str,
    metric_name: str,
    grouping_name: str,
    group_key: str,
    baseline_model: str | None = None,
) -> pd.DataFrame:
    if not values:
        return pd.DataFrame(
            columns=[
                "artifact_kind",
                "baseline_model",
                "model_name",
                "metric_name",
                "grouping_name",
                "group_key",
                "replicate_id",
                "replicate_value",
            ]
        )
    return pd.DataFrame(
        {
            "artifact_kind": artifact_kind,
            "baseline_model": baseline_model,
            "model_name": model_name,
            "metric_name": metric_name,
            "grouping_name": grouping_name,
            "group_key": group_key,
            "replicate_id": range(len(values)),
            "replicate_value": values,
        }
    )


def _concat_replicates(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    nonempty = [frame for frame in frames if not frame.empty]
    return pd.concat(nonempty, ignore_index=True) if nonempty else frames[0]


def _iter_groups(
    predictions: pd.DataFrame,
    grouping: dict[str, Any],
) -> list[tuple[str, pd.DataFrame]]:
    columns = list(grouping["columns"])
    if not columns:
        return [("overall", predictions)]
    groups: list[tuple[str, pd.DataFrame]] = []
    for key, frame in predictions.groupby(columns, dropna=False, observed=True):
        if not isinstance(key, tuple):
            key = (key,)
        groups.append(("|".join(str(value) for value in key), frame.copy()))
    return groups


def _cluster_sizes(frame: pd.DataFrame, config: InferenceConfig) -> list[int]:
    return [
        int(value)
        for value in frame.groupby(config.cluster_column, observed=True).size().tolist()
    ]


def _validate_prediction_panel_keys(joined: pd.DataFrame, config: InferenceConfig) -> None:
    checks = {
        config.contract_column: joined[config.contract_column].astype(str)
        == joined[f"{config.contract_column}_panel"].astype(str),
        config.cluster_column: joined[config.cluster_column].astype(str)
        == joined[f"{config.cluster_column}_panel"].astype(str),
        config.horizon_column: joined[config.horizon_column].astype(str)
        == joined[f"{config.horizon_column}_panel"].astype(str),
        "forecast_ts": pd.to_datetime(joined["forecast_ts"], utc=True)
        == pd.to_datetime(joined["forecast_ts_panel"], utc=True),
        "resolution_ts": pd.to_datetime(joined["resolution_ts"], utc=True)
        == pd.to_datetime(joined["resolution_ts_panel"], utc=True),
    }
    failed = [name for name, mask in checks.items() if not bool(mask.all())]
    if failed:
        raise InferenceError(f"prediction/panel key mismatch for fields: {failed}")


def _coalesce_panel_columns(joined: pd.DataFrame, config: InferenceConfig) -> pd.DataFrame:
    rows = joined.copy()
    for column in (
        config.contract_column,
        config.cluster_column,
        config.horizon_column,
        "forecast_ts",
        "resolution_ts",
    ):
        panel_column = f"{column}_panel"
        if panel_column in rows.columns:
            rows = rows.drop(columns=[panel_column])
    return rows


def _validate_identical_test_rows(predictions: pd.DataFrame, config: InferenceConfig) -> None:
    expected_models = {config.baseline_model, *config.comparison_models}
    observed = set(predictions["model_name"].astype(str).unique())
    missing = sorted(expected_models - observed)
    if missing:
        raise InferenceError(f"predictions missing configured models: {missing}")
    counts = predictions[predictions["model_name"].isin(expected_models)].groupby(
        ["fold_id", config.row_id_column],
        observed=True,
    )["model_name"].nunique()
    bad = int((counts != len(expected_models)).sum())
    if bad:
        raise InferenceError("configured models do not share identical test row IDs")


def _bucket_series(frame: pd.DataFrame, spec: dict[str, Any]) -> pd.Series:
    column = str(_required(spec, "column"))
    edges = [float(value) for value in _required(spec, "edges")]
    labels = [str(value) for value in _required(spec, "labels")]
    if len(labels) != len(edges) + 1:
        raise InferenceError(f"bucket labels must have len(edges) + 1 for {column}")
    values = pd.to_numeric(frame[column], errors="coerce")
    bins = [-math.inf, *edges, math.inf]
    return pd.cut(values, bins=bins, labels=labels, include_lowest=True).astype("string")


def _validate_config(config: InferenceConfig) -> None:
    for path in (
        config.predictions_path,
        config.panel_path,
        config.aggregate_metrics_path,
        config.fold_metrics_path,
    ):
        if not path.exists():
            raise InferenceError(f"missing inference input artifact: {path}")
    if config.bootstrap_unit != config.cluster_column:
        raise InferenceError(
            "confirmatory inference must bootstrap by the configured cluster column"
        )
    if config.bootstrap_unit.lower() in {"row", "row_id", "iid", "trade", "trade_id"}:
        raise InferenceError("iid row/trade bootstrap is not allowed for confirmatory inference")
    if config.bootstrap_iterations <= 0:
        raise InferenceError("bootstrap_iterations must be positive")
    if not 0.0 < config.confidence_level < 1.0:
        raise InferenceError("confidence_level must be in (0, 1)")
    if config.min_rows <= 0 or config.min_clusters <= 0:
        raise InferenceError("min_rows and min_clusters must be positive")
    if not 0.0 < config.fdr_alpha < 1.0:
        raise InferenceError("fdr_alpha must be in (0, 1)")
    if not 0.0 < config.log_loss_epsilon < 0.5:
        raise InferenceError("log_loss_epsilon must be in (0, 0.5)")


def _require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise InferenceError(f"{label} missing columns: {missing}")


def _artifact_paths(artifact_dir: Path) -> dict[str, Path]:
    return {
        "score_intervals": artifact_dir / "score_intervals.parquet",
        "paired_score_differences": artifact_dir / "paired_score_differences.parquet",
        "calibration_intervals": artifact_dir / "calibration_intervals.parquet",
        "multiple_comparison_adjustments": artifact_dir
        / "multiple_comparison_adjustments.parquet",
        "paired_loss_diagnostics": artifact_dir / "paired_loss_diagnostics.parquet",
        "bootstrap_replicates": artifact_dir / "bootstrap_replicates.parquet",
        "summary": artifact_dir / "summary.json",
    }


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"inference config missing mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"inference config missing required key: {key}")
    return raw[key]


def _grouping(raw: dict[str, Any]) -> dict[str, Any]:
    return {"name": str(_required(raw, "name")), "columns": list(_required(raw, "columns"))}


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
