"""Calibration intercept/slope fitting for binary probabilities."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from predmkt.metrics.scoring import clip_probability


@dataclass(frozen=True)
class CalibrationFit:
    """Logistic calibration fit summary."""

    intercept: float | None
    slope: float | None
    row_count: int
    iterations: int
    converged: bool
    status: str


def fit_calibration_intercept_slope(
    probabilities: Sequence[float],
    outcomes: Sequence[int | float],
    *,
    epsilon: float,
    min_rows: int = 50,
    max_iterations: int = 50,
    tolerance: float = 1e-8,
) -> CalibrationFit:
    """Fit ``outcome ~ intercept + slope * logit(probability)`` by Newton IRLS."""

    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have the same length")
    row_count = len(probabilities)
    if row_count < min_rows:
        return CalibrationFit(None, None, row_count, 0, False, "too_few_rows")

    y_values = [float(value) for value in outcomes]
    if any(value not in (0.0, 1.0) for value in y_values):
        raise ValueError("outcomes must be binary 0/1")
    if min(y_values) == max(y_values):
        return CalibrationFit(None, None, row_count, 0, False, "outcome_has_no_variation")

    x_values = [_logit(clip_probability(float(value), epsilon)) for value in probabilities]
    if max(x_values) - min(x_values) <= tolerance:
        return CalibrationFit(None, None, row_count, 0, False, "probability_has_no_variation")

    intercept = 0.0
    slope = 1.0
    ridge = 1e-9
    for iteration in range(1, max_iterations + 1):
        g0 = 0.0
        g1 = 0.0
        h00 = ridge
        h01 = 0.0
        h11 = ridge
        for x_value, y_value in zip(x_values, y_values, strict=True):
            eta = intercept + slope * x_value
            mu = _sigmoid(eta)
            residual = y_value - mu
            weight = max(mu * (1.0 - mu), ridge)
            g0 += residual
            g1 += residual * x_value
            h00 += weight
            h01 += weight * x_value
            h11 += weight * x_value * x_value

        determinant = h00 * h11 - h01 * h01
        if abs(determinant) <= ridge:
            return CalibrationFit(None, None, row_count, iteration, False, "singular_hessian")

        delta_intercept = (h11 * g0 - h01 * g1) / determinant
        delta_slope = (-h01 * g0 + h00 * g1) / determinant
        intercept += delta_intercept
        slope += delta_slope
        if max(abs(delta_intercept), abs(delta_slope)) < tolerance:
            return CalibrationFit(intercept, slope, row_count, iteration, True, "converged")

    return CalibrationFit(intercept, slope, row_count, max_iterations, False, "max_iterations")


def _logit(probability: float) -> float:
    return math.log(probability / (1.0 - probability))


def _sigmoid(value: float) -> float:
    if value >= 0.0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)
