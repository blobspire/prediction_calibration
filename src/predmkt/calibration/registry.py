"""Calibrator registry and model config loading."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from predmkt.calibration.base import BaseCalibrator, CalibratorConfig
from predmkt.calibration.beta import BetaCalibrator
from predmkt.calibration.isotonic import IsotonicCalibrator
from predmkt.calibration.logistic import PlattCalibrator
from predmkt.calibration.raw import RawCalibrator


@dataclass(frozen=True)
class ModelsConfig:
    """Configuration for simple recalibrator construction."""

    panel_path: Path
    splits_path: Path
    probability_column: str
    outcome_column: str
    enabled_calibrators: tuple[str, ...]
    calibrator_config: CalibratorConfig
    config_path: Path | None = None
    config_sha256: str | None = None


CalibratorFactory = Callable[[CalibratorConfig], BaseCalibrator]

_REGISTRY: dict[str, CalibratorFactory] = {
    "raw": RawCalibrator,
    "platt": PlattCalibrator,
    "logistic": PlattCalibrator,
    "beta": BetaCalibrator,
    "isotonic": IsotonicCalibrator,
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
    columns = _mapping(raw, "columns")
    calibrators = _mapping(raw, "calibrators")
    prediction = _mapping(raw, "prediction")
    fit = _mapping(raw, "fit")

    enabled = tuple(str(name) for name in _required(calibrators, "enabled"))
    if not enabled:
        raise ValueError("models config must enable at least one calibrator")

    return ModelsConfig(
        panel_path=Path(_required(inputs, "panel_path")),
        splits_path=Path(_required(inputs, "splits_path")),
        probability_column=str(_required(columns, "probability_column")),
        outcome_column=str(_required(columns, "outcome_column")),
        enabled_calibrators=enabled,
        calibrator_config=CalibratorConfig(
            epsilon=float(_required(prediction, "epsilon")),
            min_rows=int(_required(fit, "min_rows")),
            max_iterations=int(_required(fit, "max_iterations")),
            tolerance=float(_required(fit, "tolerance")),
            ridge=float(_required(fit, "ridge")),
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
