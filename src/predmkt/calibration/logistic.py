"""Logistic / Platt recalibration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from predmkt.calibration.base import (
    BaseCalibrator,
    CalibratorConfig,
    fit_failure_status,
    logit,
    sigmoid,
    solve_linear_system,
    validate_training_data,
)


@dataclass
class PlattCalibrator(BaseCalibrator):
    """Fit ``outcome ~ intercept + slope * logit(probability)``."""

    config: CalibratorConfig = field(default_factory=CalibratorConfig)
    name: str = "platt"
    intercept: float | None = None
    slope: float | None = None
    iterations: int = 0

    def fit(
        self,
        probabilities: Sequence[float],
        outcomes: Sequence[int | float],
    ) -> PlattCalibrator:
        p_values, y_values = validate_training_data(probabilities, outcomes)
        self.row_count = len(p_values)
        self.intercept = None
        self.slope = None
        self.iterations = 0
        failure = fit_failure_status(p_values, y_values, self.config)
        if failure is not None:
            self.is_fitted = True
            self.status = failure
            return self

        x_values = [[1.0, logit(self._clip(probability))] for probability in p_values]
        fit = _fit_logistic_regression(
            x_values,
            y_values,
            config=self.config,
            initial_coefficients=[0.0, 1.0],
        )
        self.iterations = fit.iterations
        if fit.coefficients is None:
            self.status = f"fallback_{fit.status}"
        elif fit.coefficients[1] < 0.0:
            self.status = "fallback_negative_slope"
        else:
            self.intercept = fit.coefficients[0]
            self.slope = fit.coefficients[1]
            self.status = fit.status
        self.is_fitted = True
        return self

    def predict_proba(self, probabilities: Sequence[float]) -> list[float]:
        self._require_fitted()
        if self.intercept is None or self.slope is None:
            return self._raw_predictions(probabilities)
        return [
            self._clip(sigmoid(self.intercept + self.slope * logit(self._clip(probability))))
            for probability in probabilities
        ]

    @property
    def parameters(self) -> dict[str, float | list[float] | list[int] | None]:
        return {"intercept": self.intercept, "slope": self.slope}


@dataclass(frozen=True)
class LogisticRegressionFit:
    """Small logistic regression fit result."""

    coefficients: list[float] | None
    iterations: int
    status: str


def _fit_logistic_regression(
    features: list[list[float]],
    outcomes: list[float],
    *,
    config: CalibratorConfig,
    initial_coefficients: list[float],
) -> LogisticRegressionFit:
    coefficients = initial_coefficients.copy()
    size = len(coefficients)
    for iteration in range(1, config.max_iterations + 1):
        gradient = [0.0] * size
        hessian = [[0.0 for _ in range(size)] for _ in range(size)]
        for row, outcome in zip(features, outcomes, strict=True):
            eta = sum(
                coefficient * value
                for coefficient, value in zip(coefficients, row, strict=True)
            )
            mu = sigmoid(eta)
            residual = outcome - mu
            weight = max(mu * (1.0 - mu), config.ridge)
            for i, value_i in enumerate(row):
                gradient[i] += residual * value_i
                for j, value_j in enumerate(row):
                    hessian[i][j] += weight * value_i * value_j
        for i in range(size):
            hessian[i][i] += config.ridge
        delta = solve_linear_system(hessian, gradient)
        if delta is None:
            return LogisticRegressionFit(None, iteration, "singular_hessian")
        for i, value in enumerate(delta):
            coefficients[i] += value
        if max(abs(value) for value in delta) < config.tolerance:
            return LogisticRegressionFit(coefficients, iteration, "converged")
    return LogisticRegressionFit(coefficients, config.max_iterations, "max_iterations")
