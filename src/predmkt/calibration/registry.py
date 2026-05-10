"""Calibrator registry and model config loading."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from predmkt.calibration.base import BaseCalibrator, CalibratorConfig
from predmkt.calibration.beta import BetaCalibrator
from predmkt.calibration.binned import BinnedReliabilityCalibrator
from predmkt.calibration.hierarchical import HierarchicalEBCalibrator
from predmkt.calibration.isotonic import IsotonicCalibrator
from predmkt.calibration.logistic import PlattCalibrator
from predmkt.calibration.raw import RawCalibrator


@dataclass(frozen=True)
class ModelsConfig:
    """Configuration for simple recalibrator construction."""

    panel_path: Path
    splits_path: Path
    artifact_dir: Path
    probability_column: str
    outcome_column: str
    resolution_column: str
    horizon_column: str
    event_family_column: str
    enabled_calibrators: tuple[str, ...]
    calibrator_config: CalibratorConfig
    fit_splits: tuple[str, ...]
    fit_label_policy: str
    event_family_policy: str
    limit_folds: int | None
    limit_rows: int | None
    log_loss_epsilon: float
    reliability_bin_count: int
    reliability_min_bin_count: int
    calibration_min_rows: int
    calibration_max_iterations: int
    calibration_tolerance: float
    metric_groupings: tuple[dict[str, Any], ...]
    config_path: Path | None = None
    config_sha256: str | None = None


CalibratorFactory = Callable[[CalibratorConfig], BaseCalibrator]

_REGISTRY: dict[str, CalibratorFactory] = {
    "raw": RawCalibrator,
    "platt": PlattCalibrator,
    "logistic": PlattCalibrator,
    "beta": BetaCalibrator,
    "isotonic": IsotonicCalibrator,
    "binned_reliability": BinnedReliabilityCalibrator,
    "reliability_bin": BinnedReliabilityCalibrator,
    "hierarchical_eb": HierarchicalEBCalibrator,
    "hierarchical": HierarchicalEBCalibrator,
}


def available_calibrators() -> tuple[str, ...]:
    """Return calibrator names accepted by the registry."""

    return tuple(sorted(_REGISTRY))


def make_calibrator(name: str, config: CalibratorConfig | None = None) -> BaseCalibrator:
    """Instantiate a calibrator by registry name or alias."""

    normalized = name.strip().lower()
    factory = _REGISTRY.get(normalized)
    if factory is None:
        raise ValueError(
            f"unknown calibrator {name!r}; available calibrators: {list(available_calibrators())}"
        )
    return factory(config or CalibratorConfig())


def make_configured_calibrators(config: ModelsConfig) -> list[BaseCalibrator]:
    """Instantiate all calibrators enabled in a model config."""

    return [
        make_calibrator(name, config.calibrator_config)
        for name in config.enabled_calibrators
    ]


def load_models_config(path: Path) -> ModelsConfig:
    """Load recalibrator registry settings from YAML."""

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"models config must be a mapping: {path}")

    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    columns = _mapping(raw, "columns")
    calibrators = _mapping(raw, "calibrators")
    prediction = _mapping(raw, "prediction")
    fit = _mapping(raw, "fit")
    evaluation = _mapping(raw, "evaluation")
    metrics = _mapping(raw, "metrics")

    enabled = tuple(str(name) for name in _required(calibrators, "enabled"))
    if not enabled:
        raise ValueError("models config must enable at least one calibrator")
    fit_splits = tuple(str(value) for value in _required(evaluation, "fit_splits"))
    if not fit_splits:
        raise ValueError("models config evaluation.fit_splits cannot be empty")

    return ModelsConfig(
        panel_path=Path(_required(inputs, "panel_path")),
        splits_path=Path(_required(inputs, "splits_path")),
        artifact_dir=Path(_required(outputs, "artifact_dir")),
        probability_column=str(_required(columns, "probability_column")),
        outcome_column=str(_required(columns, "outcome_column")),
        resolution_column=str(_required(columns, "resolution_column")),
        horizon_column=str(_required(columns, "horizon_column")),
        event_family_column=str(_required(columns, "event_family_column")),
        enabled_calibrators=enabled,
        calibrator_config=CalibratorConfig(
            epsilon=float(_required(prediction, "epsilon")),
            min_rows=int(_required(fit, "min_rows")),
            max_iterations=int(_required(fit, "max_iterations")),
            tolerance=float(_required(fit, "tolerance")),
            ridge=float(_required(fit, "ridge")),
            reliability_bin_count=int(fit.get("reliability_bin_count", 10)),
            reliability_min_bin_count=int(fit.get("reliability_min_bin_count", 30)),
            reliability_prior_strength=float(fit.get("reliability_prior_strength", 20.0)),
            reliability_monotone=bool(fit.get("reliability_monotone", True)),
            hierarchical_group_columns=tuple(
                str(column)
                for column in fit.get("hierarchical_group_columns", ["horizon_name", "domain"])
            ),
            hierarchical_min_group_rows=int(fit.get("hierarchical_min_group_rows", 50)),
            hierarchical_prior_strength=float(fit.get("hierarchical_prior_strength", 100.0)),
            hierarchical_backfit_iterations=int(fit.get("hierarchical_backfit_iterations", 3)),
        ),
        fit_splits=fit_splits,
        fit_label_policy=str(_required(evaluation, "fit_label_policy")),
        event_family_policy=str(_required(evaluation, "event_family_policy")),
        limit_folds=_optional_int(evaluation.get("limit_folds")),
        limit_rows=_optional_int(evaluation.get("limit_rows")),
        log_loss_epsilon=float(_required(metrics, "log_loss_epsilon")),
        reliability_bin_count=int(_required(metrics, "reliability_bin_count")),
        reliability_min_bin_count=int(_required(metrics, "reliability_min_bin_count")),
        calibration_min_rows=int(_required(metrics, "calibration_min_rows")),
        calibration_max_iterations=int(_required(metrics, "calibration_max_iterations")),
        calibration_tolerance=float(_required(metrics, "calibration_tolerance")),
        metric_groupings=tuple(
            {
                "name": str(_required(grouping, "name")),
                "columns": tuple(str(column) for column in grouping.get("columns", [])),
            }
            for grouping in _required(metrics, "groupings")
        ),
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"models config missing mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"models config missing required key: {key}")
    return raw[key]


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return int(str(value))
