"""Walk-forward raw versus recalibrated model evaluation."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from predmkt.calibration import ModelsConfig, make_calibrator
from predmkt.metrics.calibration import fit_calibration_intercept_slope
from predmkt.metrics.reliability import expected_calibration_error, reliability_bins
from predmkt.metrics.scoring import brier_score, log_loss


@dataclass(frozen=True)
class WalkForwardEvaluationSummary:
    """Summary of a walk-forward model evaluation run."""

    panel_path: str
    splits_path: str
    artifact_dir: str
    panel_row_count: int
    split_row_count: int
    fold_count: int
    model_names: list[str]
    prediction_row_count: int
    fit_row_count: int
    test_row_count: int
    event_family_overlap_count: int
    config_sha256: str | None
    git_commit: str | None
    git_dirty: bool | None
    artifact_paths: dict[str, str]
    effective_config: dict[str, Any]
    limitations: list[str]


class WalkForwardEvaluationError(ValueError):
    """Raised when walk-forward evaluation inputs violate invariants."""


def evaluate_walkforward(config: ModelsConfig) -> WalkForwardEvaluationSummary:
    """Fit configured calibrators on past folds and evaluate future test folds."""

    _validate_config(config)
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths = _artifact_paths(config.artifact_dir)

    panel = _load_panel(config)
    splits = _load_splits(config, panel)
    _validate_split_panel_keys(panel, splits, config)

    fold_ids = sorted(splits["fold_id"].unique())
    if config.limit_folds is not None:
        if config.limit_folds <= 0:
            raise WalkForwardEvaluationError("limit_folds must be positive when provided")
        fold_ids = fold_ids[: config.limit_folds]
        splits = splits[splits["fold_id"].isin(fold_ids)].copy()
    if not fold_ids:
        raise WalkForwardEvaluationError("no folds available for walk-forward evaluation")

    prediction_rows: list[dict[str, Any]] = []
    fit_rows: list[dict[str, Any]] = []
    leakage_rows: list[dict[str, Any]] = []

    for fold_id in fold_ids:
        fold_splits = splits[splits["fold_id"] == fold_id]
        test_start_ts = _test_start_from_fold_id(fold_id)
        fit_frame, excluded_future_label_count = _fit_frame_for_fold(
            fold_splits,
            config=config,
            test_start_ts=test_start_ts,
        )
        test_frame = fold_splits[fold_splits["split"] == "test"].copy()
        if test_frame.empty:
            raise WalkForwardEvaluationError(f"fold has no test rows: {fold_id}")
        if fit_frame.empty:
            raise WalkForwardEvaluationError(
                f"fold has no label-available fit rows before test start: {fold_id}"
            )

        _validate_no_future_fit_rows(fit_frame, test_start_ts, config)
        leakage = _event_family_overlap(fold_id, fit_frame, test_frame, config)
        leakage_rows.extend(leakage)

        for model_name in config.enabled_calibrators:
            calibrator = make_calibrator(model_name, config.calibrator_config)
            calibrator.fit(
                fit_frame[config.probability_column].tolist(),
                fit_frame[config.outcome_column].tolist(),
            )
            predictions = calibrator.predict_proba(test_frame[config.probability_column].tolist())
            fit_rows.append(
                {
                    "fold_id": fold_id,
                    "model_name": calibrator.name,
                    "fit_row_count": int(len(fit_frame)),
                    "excluded_future_label_count": int(excluded_future_label_count),
                    "test_row_count": int(len(test_frame)),
                    "label_cutoff_ts": test_start_ts,
                    "fit_status": calibrator.status,
                    "calibrator_row_count": calibrator.row_count,
                    "parameters_json": json.dumps(calibrator.parameters, sort_keys=True),
                }
            )
            for row, prediction in zip(
                test_frame.to_dict(orient="records"),
                predictions,
                strict=True,
            ):
                prediction_rows.append(
                    {
                        "fold_id": fold_id,
                        "model_name": calibrator.name,
                        "row_id": int(row["row_id"]),
                        "contract_id": row["contract_id"],
                        "event_family_id": row[config.event_family_column],
                        "horizon_name": row[config.horizon_column],
                        "forecast_ts": row["forecast_ts"],
                        "resolution_ts": row[config.resolution_column],
                        "observed_outcome": int(row[config.outcome_column]),
                        "raw_probability": float(row[config.probability_column]),
                        "predicted_probability": float(prediction),
                        "fit_status": calibrator.status,
                        "fit_row_count": int(len(fit_frame)),
                    }
                )

    predictions = pd.DataFrame(prediction_rows)
    if predictions.empty:
        raise WalkForwardEvaluationError("walk-forward evaluation produced no predictions")
    _validate_identical_test_rows(predictions)

    fold_metrics = _metric_rows(predictions, config, by_fold=True)
    aggregate_metrics = _aggregate_metric_rows(predictions, fold_metrics, config)
    calibrator_fits = pd.DataFrame(fit_rows)
    event_family_leakage = pd.DataFrame(
        leakage_rows,
        columns=["fold_id", "event_family_id", "fit_row_count", "test_row_count"],
    )

    predictions.to_parquet(artifact_paths["predictions"], index=False)
    fold_metrics.to_parquet(artifact_paths["fold_metrics"], index=False)
    aggregate_metrics.to_parquet(artifact_paths["aggregate_metrics"], index=False)
    calibrator_fits.to_parquet(artifact_paths["calibrator_fits"], index=False)
    event_family_leakage.to_parquet(artifact_paths["event_family_leakage"], index=False)

    git_commit, git_dirty = _git_state()
    summary = WalkForwardEvaluationSummary(
        panel_path=str(config.panel_path),
        splits_path=str(config.splits_path),
        artifact_dir=str(config.artifact_dir),
        panel_row_count=int(len(panel)),
        split_row_count=int(len(splits)),
        fold_count=len(fold_ids),
        model_names=sorted(predictions["model_name"].unique().tolist()),
        prediction_row_count=int(len(predictions)),
        fit_row_count=int(calibrator_fits["fit_row_count"].sum()),
        test_row_count=int(predictions[["fold_id", "row_id"]].drop_duplicates().shape[0]),
        event_family_overlap_count=int(len(event_family_leakage)),
        config_sha256=config.config_sha256,
        git_commit=git_commit,
        git_dirty=git_dirty,
        artifact_paths={key: str(value) for key, value in artifact_paths.items()},
        effective_config=_effective_config(config),
        limitations=[
            "Phase 7 evaluates simple raw/Platt/beta/isotonic calibrators only; no "
            "hierarchical models are implemented.",
            "Fit data uses train+validation rows with labels resolved by each test "
            "fold start; rows with later resolutions are excluded from fitting.",
            "Event-family overlaps are reported but not filtered because current "
            "event_family_id values remain conservative proxies.",
            "Metrics are equal-contract over contract-horizon test rows; no trade "
            "weighting or edge simulation is implemented here.",
        ],
    )
    artifact_paths["summary"].write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return summary


def _load_panel(config: ModelsConfig) -> pd.DataFrame:
    panel = pd.read_parquet(config.panel_path)
    if config.limit_rows is not None:
        if config.limit_rows <= 0:
            raise WalkForwardEvaluationError("limit_rows must be positive when provided")
        panel = panel.head(config.limit_rows).copy()
    panel = panel.copy()
    panel.insert(0, "row_id", range(len(panel)))
    required = {
        "row_id",
        "contract_id",
        "forecast_ts",
        config.event_family_column,
        config.horizon_column,
        config.resolution_column,
        config.probability_column,
        config.outcome_column,
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise WalkForwardEvaluationError(f"modeling panel missing columns: {missing}")
    panel["forecast_ts"] = pd.to_datetime(panel["forecast_ts"], utc=True, errors="raise")
    panel[config.resolution_column] = pd.to_datetime(
        panel[config.resolution_column],
        utc=True,
        errors="raise",
    )
    return panel


def _load_splits(config: ModelsConfig, panel: pd.DataFrame) -> pd.DataFrame:
    splits = pd.read_parquet(config.splits_path)
    required = {"fold_id", "split", "row_id", "contract_id", "horizon", "forecast_ts"}
    missing = sorted(required - set(splits.columns))
    if missing:
        raise WalkForwardEvaluationError(f"split artifact missing columns: {missing}")
    if config.limit_rows is not None:
        splits = splits[splits["row_id"] < len(panel)].copy()
    if splits.empty:
        raise WalkForwardEvaluationError("split artifact has no rows after filtering")
    splits = splits.copy()
    splits["forecast_ts"] = pd.to_datetime(splits["forecast_ts"], utc=True, errors="raise")
    joined = splits.merge(
        panel,
        on="row_id",
        suffixes=("_split", ""),
        how="left",
        validate="many_to_one",
    )
    if joined["contract_id"].isna().any():
        raise WalkForwardEvaluationError("split artifact references row_ids missing from panel")
    return joined


def _validate_split_panel_keys(
    joined: pd.DataFrame,
    splits: pd.DataFrame,
    config: ModelsConfig,
) -> None:
    del joined
    checks = {
        "contract_id": splits["contract_id_split"].astype(str) == splits["contract_id"].astype(str),
        "horizon": splits["horizon"].astype(str) == splits[config.horizon_column].astype(str),
        "forecast_ts": splits["forecast_ts_split"] == splits["forecast_ts"],
    }
    if "event_family_id_split" in splits.columns:
        checks["event_family_id"] = splits["event_family_id_split"].astype(str) == splits[
            config.event_family_column
        ].astype(str)
    failed = [name for name, mask in checks.items() if not bool(mask.all())]
    if failed:
        raise WalkForwardEvaluationError(f"split/panel key mismatch for fields: {failed}")


def _fit_frame_for_fold(
    fold_splits: pd.DataFrame,
    *,
    config: ModelsConfig,
    test_start_ts: pd.Timestamp,
) -> tuple[pd.DataFrame, int]:
    if config.fit_label_policy != "resolved_by_test_start":
        raise WalkForwardEvaluationError(
            f"unsupported fit_label_policy: {config.fit_label_policy}"
        )
    fit_frame = fold_splits[fold_splits["split"].isin(config.fit_splits)].copy()
    future_label_mask = fit_frame[config.resolution_column] > test_start_ts
    future_label_count = int(future_label_mask.sum())
    fit_frame = fit_frame[~future_label_mask].copy()
    return fit_frame, future_label_count


def _validate_no_future_fit_rows(
    fit_frame: pd.DataFrame,
    test_start_ts: pd.Timestamp,
    config: ModelsConfig,
) -> None:
    if (fit_frame["forecast_ts"] >= test_start_ts).any():
        raise WalkForwardEvaluationError("fit data contains forecast_ts at or after test start")
    if (fit_frame[config.resolution_column] > test_start_ts).any():
        raise WalkForwardEvaluationError("fit data contains labels unavailable at test start")


def _event_family_overlap(
    fold_id: str,
    fit_frame: pd.DataFrame,
    test_frame: pd.DataFrame,
    config: ModelsConfig,
) -> list[dict[str, Any]]:
    if config.event_family_policy != "report_only":
        raise WalkForwardEvaluationError(
            f"unsupported event_family_policy: {config.event_family_policy}"
        )
    fit_counts = fit_frame.groupby(config.event_family_column, observed=True).size()
    test_counts = test_frame.groupby(config.event_family_column, observed=True).size()
    overlap = sorted(set(fit_counts.index).intersection(set(test_counts.index)))
    return [
        {
            "fold_id": fold_id,
            "event_family_id": str(event_family_id),
            "fit_row_count": int(fit_counts.loc[event_family_id]),
            "test_row_count": int(test_counts.loc[event_family_id]),
        }
        for event_family_id in overlap
    ]


def _metric_rows(predictions: pd.DataFrame, config: ModelsConfig, *, by_fold: bool) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    base_columns = ["model_name"]
    if by_fold:
        base_columns.insert(0, "fold_id")
    for grouping in config.metric_groupings:
        grouping_name = str(grouping["name"])
        group_columns = list(grouping["columns"])
        columns = [*base_columns, *group_columns]
        grouped = predictions.groupby(columns, dropna=False, observed=True) if columns else []
        if columns:
            iterator = grouped
        else:
            iterator = [((), predictions)]
        for key, frame in iterator:
            key_values = _key_values(key, columns)
            probabilities = frame["predicted_probability"].astype(float).tolist()
            outcomes = frame["observed_outcome"].astype(float).tolist()
            bins = reliability_bins(
                probabilities,
                outcomes,
                bin_count=config.reliability_bin_count,
                min_bin_count=config.reliability_min_bin_count,
            )
            calibration = fit_calibration_intercept_slope(
                probabilities,
                outcomes,
                epsilon=config.log_loss_epsilon,
                min_rows=config.calibration_min_rows,
                max_iterations=config.calibration_max_iterations,
                tolerance=config.calibration_tolerance,
            )
            rows.append(
                {
                    "fold_id": key_values.get("fold_id"),
                    "model_name": key_values.get("model_name"),
                    "metric_scope": "fold" if by_fold else "pooled_equal_contract",
                    "grouping_name": grouping_name,
                    "group_key": _group_key(frame, group_columns),
                    "row_count": int(len(frame)),
                    "brier_score": brier_score(probabilities, outcomes),
                    "log_loss": log_loss(
                        probabilities,
                        outcomes,
                        epsilon=config.log_loss_epsilon,
                    ),
                    "expected_calibration_error": expected_calibration_error(bins),
                    "calibration_intercept": calibration.intercept,
                    "calibration_slope": calibration.slope,
                    "calibration_status": calibration.status,
                }
            )
    return pd.DataFrame(rows)


def _aggregate_metric_rows(
    predictions: pd.DataFrame,
    fold_metrics: pd.DataFrame,
    config: ModelsConfig,
) -> pd.DataFrame:
    pooled = _metric_rows(predictions, config, by_fold=False)
    macro = (
        fold_metrics.groupby(["model_name", "grouping_name", "group_key"], dropna=False)
        .agg(
            row_count=("row_count", "sum"),
            fold_count=("fold_id", "nunique"),
            brier_score=("brier_score", "mean"),
            log_loss=("log_loss", "mean"),
            expected_calibration_error=("expected_calibration_error", "mean"),
            calibration_intercept=("calibration_intercept", "mean"),
            calibration_slope=("calibration_slope", "mean"),
        )
        .reset_index()
    )
    macro.insert(0, "metric_scope", "fold_macro")
    macro["fold_id"] = None
    macro["calibration_status"] = "fold_macro_mean"
    pooled["fold_count"] = None
    return pd.concat([pooled, macro[pooled.columns]], ignore_index=True)


def _validate_identical_test_rows(predictions: pd.DataFrame) -> None:
    expected_models = set(predictions["model_name"].unique())
    for fold_id, frame in predictions.groupby("fold_id", observed=True):
        row_sets = {
            model_name: set(model_frame["row_id"].tolist())
            for model_name, model_frame in frame.groupby("model_name", observed=True)
        }
        if set(row_sets) != expected_models:
            raise WalkForwardEvaluationError(f"fold missing model predictions: {fold_id}")
        if len({frozenset(rows) for rows in row_sets.values()}) != 1:
            raise WalkForwardEvaluationError(
                f"models do not share identical test rows in fold: {fold_id}"
            )


def _test_start_from_fold_id(fold_id: str) -> pd.Timestamp:
    try:
        _, year, month = fold_id.split("_")
        return pd.Timestamp(f"{year}-{month}-01", tz="UTC")
    except ValueError as exc:
        raise WalkForwardEvaluationError(
            f"fold_id must have format fold_YYYY_MM for label cutoffs: {fold_id}"
        ) from exc


def _key_values(key: Any, columns: list[str]) -> dict[str, Any]:
    if not columns:
        return {}
    if len(columns) == 1 and not isinstance(key, tuple):
        key = (key,)
    return dict(zip(columns, key, strict=True))


def _group_key(frame: pd.DataFrame, group_columns: list[str]) -> str:
    if not group_columns:
        return "overall"
    values = []
    first = frame.iloc[0]
    for column in group_columns:
        values.append(str(first[column]))
    return "|".join(values)


def _artifact_paths(artifact_dir: Path) -> dict[str, Path]:
    return {
        "predictions": artifact_dir / "predictions.parquet",
        "fold_metrics": artifact_dir / "fold_metrics.parquet",
        "aggregate_metrics": artifact_dir / "aggregate_metrics.parquet",
        "calibrator_fits": artifact_dir / "calibrator_fits.parquet",
        "event_family_leakage": artifact_dir / "event_family_leakage.parquet",
        "summary": artifact_dir / "summary.json",
    }


def _effective_config(config: ModelsConfig) -> dict[str, Any]:
    return {
        "inputs": {
            "panel_path": str(config.panel_path),
            "splits_path": str(config.splits_path),
        },
        "outputs": {"artifact_dir": str(config.artifact_dir)},
        "columns": {
            "probability_column": config.probability_column,
            "outcome_column": config.outcome_column,
            "resolution_column": config.resolution_column,
            "horizon_column": config.horizon_column,
            "event_family_column": config.event_family_column,
        },
        "calibrators": {"enabled": list(config.enabled_calibrators)},
        "prediction": {"epsilon": config.calibrator_config.epsilon},
        "fit": {
            "min_rows": config.calibrator_config.min_rows,
            "max_iterations": config.calibrator_config.max_iterations,
            "tolerance": config.calibrator_config.tolerance,
            "ridge": config.calibrator_config.ridge,
        },
        "evaluation": {
            "fit_splits": list(config.fit_splits),
            "fit_label_policy": config.fit_label_policy,
            "event_family_policy": config.event_family_policy,
            "limit_folds": config.limit_folds,
            "limit_rows": config.limit_rows,
        },
        "metrics": {
            "log_loss_epsilon": config.log_loss_epsilon,
            "reliability_bin_count": config.reliability_bin_count,
            "reliability_min_bin_count": config.reliability_min_bin_count,
            "calibration_min_rows": config.calibration_min_rows,
            "calibration_max_iterations": config.calibration_max_iterations,
            "calibration_tolerance": config.calibration_tolerance,
            "groupings": [
                {"name": item["name"], "columns": list(item["columns"])}
                for item in config.metric_groupings
            ],
        },
        "config_path": str(config.config_path) if config.config_path else None,
        "config_sha256": config.config_sha256,
    }


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


def _validate_config(config: ModelsConfig) -> None:
    if config.fit_label_policy != "resolved_by_test_start":
        raise WalkForwardEvaluationError(
            f"unsupported fit_label_policy: {config.fit_label_policy}"
        )
    if config.event_family_policy != "report_only":
        raise WalkForwardEvaluationError(
            f"unsupported event_family_policy: {config.event_family_policy}"
        )
    if set(config.fit_splits) - {"train", "validation"}:
        raise WalkForwardEvaluationError("fit_splits may only include train and validation")
    if config.reliability_bin_count <= 0:
        raise WalkForwardEvaluationError("reliability_bin_count must be positive")
    if config.reliability_min_bin_count < 0:
        raise WalkForwardEvaluationError("reliability_min_bin_count cannot be negative")
