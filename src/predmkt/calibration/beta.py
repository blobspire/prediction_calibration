"""Beta calibration for binary probabilities."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from predmkt.calibration.base import (
    BaseCalibrator,
    CalibratorConfig,
    fit_failure_status,
    sigmoid,
    validate_training_data,
)
from predmkt.calibration.logistic import _fit_logistic_regression


@dataclass
class BetaCalibrator(BaseCalibrator):
    """Fit a logistic model on ``log(p)`` and ``log(1-p)`` features."""

    config: CalibratorConfig = field(default_factory=CalibratorConfig)
    name: str = "beta"
    intercept: float | None = None
    coef_log_p: float | None = None
    coef_log_one_minus_p: float | None = None
    iterations: int = 0

    def fit(
        self,
        probabilities: Sequence[float],
        outcomes: Sequence[int | float],
    ) -> BetaCalibrator:
        p_values, y_values = validate_training_data(probabilities, outcomes)
        self.row_count = len(p_values)
        self.intercept = None
        self.coef_log_p = None
        self.coef_log_one_minus_p = None
        self.iterations = 0
        failure = fit_failure_status(p_values, y_values, self.config)
        if failure is not None:
            self.is_fitted = True
            self.status = failure
            return self

        features = [self._features(probability) for probability in p_values]
        fit = _fit_logistic_regression(
            features,
            y_values,
            config=self.config,
            initial_coefficients=[0.0, 1.0, -1.0],
        )
        self.iterations = fit.iterations
        if fit.coefficients is None:
            self.status = f"fallback_{fit.status}"
        else:
            self.intercept = fit.coefficients[0]
            self.coef_log_p = fit.coefficients[1]
            self.coef_log_one_minus_p = fit.coefficients[2]
            self.status = fit.status
        self.is_fitted = True
        return self

    def predict_proba(self, probabilities: Sequence[float]) -> list[float]:
        self._require_fitted()
        if (
            self.intercept is None
            or self.coef_log_p is None
            or self.coef_log_one_minus_p is None
        ):
            return self._raw_predictions(probabilities)
        predictions: list[float] = []
        for probability in probabilities:
            _, log_p, log_one_minus_p = self._features(probability)
            eta = (
                self.intercept
                + self.coef_log_p * log_p
                + self.coef_log_one_minus_p * log_one_minus_p
            )
            predictions.append(self._clip(sigmoid(eta)))
        return predictions

    @property
    def parameters(self) -> dict[str, float | list[float] | list[int] | None]:
        return {
            "intercept": self.intercept,
            "coef_log_p": self.coef_log_p,
            "coef_log_one_minus_p": self.coef_log_one_minus_p,
        }

    def _features(self, probability: float) -> list[float]:
        clipped = self._clip(probability)
        return [1.0, math.log(clipped), math.log(1.0 - clipped)]
