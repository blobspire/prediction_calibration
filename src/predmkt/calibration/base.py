"""Common recalibrator interface and validation helpers."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from predmkt.metrics.scoring import clip_probability


@dataclass(frozen=True)
class CalibratorConfig:
    """Shared fit/prediction controls for simple recalibrators."""

    epsilon: float = 1e-6
    min_rows: int = 20
    max_iterations: int = 100
    tolerance: float = 1e-8
    ridge: float = 1e-9

    def __post_init__(self) -> None:
        if not math.isfinite(self.epsilon) or not 0.0 < self.epsilon < 0.5:
            raise ValueError("calibrator epsilon must be finite and in (0, 0.5)")
        if self.min_rows < 0:
            raise ValueError("calibrator min_rows cannot be negative")
        if self.max_iterations <= 0:
            raise ValueError("calibrator max_iterations must be positive")
        if self.tolerance <= 0.0 or not math.isfinite(self.tolerance):
            raise ValueError("calibrator tolerance must be finite and positive")
        if self.ridge < 0.0 or not math.isfinite(self.ridge):
            raise ValueError("calibrator ridge must be finite and nonnegative")


@dataclass
class BaseCalibrator:
    """Base class for simple probability recalibrators."""

    config: CalibratorConfig = field(default_factory=CalibratorConfig)
    name: str = "base"
    is_fitted: bool = False
    status: str = "not_fitted"
    row_count: int = 0

    def fit(
        self,
        probabilities: Sequence[float],
        outcomes: Sequence[int | float],
    ) -> BaseCalibrator:
        """Fit the calibrator and return ``self``."""

        raise NotImplementedError

    def predict_proba(self, probabilities: Sequence[float]) -> list[float]:
        """Return calibrated probabilities."""

        raise NotImplementedError

    @property
    def parameters(self) -> dict[str, float | list[float] | list[int] | None]:
        """Return learned parameters in a serializable shape."""

        return {}

    def _clip(self, probability: float) -> float:
        return clip_probability(float(probability), self.config.epsilon)

    def _raw_predictions(self, probabilities: Sequence[float]) -> list[float]:
        _validate_probabilities(probabilities)
        return [self._clip(float(probability)) for probability in probabilities]

    def _require_fitted(self) -> None:
        if not self.is_fitted:
            raise RuntimeError(f"{self.name} calibrator has not been fit")


def validate_training_data(
    probabilities: Sequence[float],
    outcomes: Sequence[int | float],
) -> tuple[list[float], list[float]]:
    """Validate and return finite probability/outcome lists."""

    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have the same length")
    _validate_probabilities(probabilities)
    y_values = [float(outcome) for outcome in outcomes]
    invalid = [value for value in y_values if value not in (0.0, 1.0)]
    if invalid:
        raise ValueError("outcomes must be binary 0/1")
    return [float(probability) for probability in probabilities], y_values


def fit_failure_status(
    probabilities: Sequence[float],
    outcomes: Sequence[float],
    config: CalibratorConfig,
) -> str | None:
    """Return a non-fatal fit status for degenerate calibration folds."""

    row_count = len(probabilities)
    if row_count == 0:
        return "fallback_too_few_rows"
    if row_count < config.min_rows:
        return "fallback_too_few_rows"
    if min(outcomes) == max(outcomes):
        return "fallback_outcome_has_no_variation"
    clipped = [
        clip_probability(float(probability), config.epsilon)
        for probability in probabilities
    ]
    if max(clipped) - min(clipped) <= config.tolerance:
        return "fallback_probability_has_no_variation"
    return None


def sigmoid(value: float) -> float:
    """Numerically stable logistic sigmoid."""

    if value >= 0.0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def logit(probability: float) -> float:
    """Return logit for a probability that is already clipped away from 0/1."""

    return math.log(probability / (1.0 - probability))


def solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """Solve a small dense linear system by Gaussian elimination."""

    size = len(vector)
    augmented = [row.copy() + [value] for row, value in zip(matrix, vector, strict=True)]
    for pivot_index in range(size):
        best_row = max(
            range(pivot_index, size),
            key=lambda row_index: abs(augmented[row_index][pivot_index]),
        )
        if abs(augmented[best_row][pivot_index]) <= 1e-15:
            return None
        if best_row != pivot_index:
            augmented[pivot_index], augmented[best_row] = (
                augmented[best_row],
                augmented[pivot_index],
            )
        pivot = augmented[pivot_index][pivot_index]
        for column_index in range(pivot_index, size + 1):
            augmented[pivot_index][column_index] /= pivot
        for row_index in range(size):
            if row_index == pivot_index:
                continue
            factor = augmented[row_index][pivot_index]
            if factor == 0.0:
                continue
            for column_index in range(pivot_index, size + 1):
                augmented[row_index][column_index] -= factor * augmented[pivot_index][column_index]
    return [augmented[row_index][size] for row_index in range(size)]


def _validate_probabilities(probabilities: Sequence[float]) -> None:
    for probability in probabilities:
        value = float(probability)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"probability must be finite and in [0, 1]: {probability}")
