"""Experimental empirical-Bayes additive recalibrator."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from predmkt.calibration.base import (
    BaseCalibrator,
    CalibratorConfig,
    fit_failure_status,
    logit,
    sigmoid,
    validate_training_data,
)
from predmkt.calibration.logistic import _fit_logistic_regression

_MISSING_LEVEL = "__missing__"


@dataclass
class HierarchicalEBCalibrator(BaseCalibrator):
    """Global Platt fit plus shrunk horizon/domain additive logit offsets.

    This is an empirical-Bayes approximation for robustness and exploration, not a full
    hierarchical Bayesian model.
    """

    config: CalibratorConfig = field(default_factory=CalibratorConfig)
    name: str = "hierarchical_eb"
    intercept: float | None = None
    slope: float | None = None
    offsets: dict[str, dict[str, float]] = field(default_factory=dict)
    global_rate: float | None = None
    iterations: int = 0

    @property
    def requires_context(self) -> tuple[str, ...]:
        return self.config.hierarchical_group_columns

    @property
    def is_experimental(self) -> bool:
        return True

    def fit(
        self,
        probabilities: Sequence[float],
        outcomes: Sequence[int | float],
    ) -> HierarchicalEBCalibrator:
        del probabilities, outcomes
        raise ValueError(
            "hierarchical_eb requires fit_with_context with configured context columns"
        )

    def fit_with_context(
        self,
        probabilities: Sequence[float],
        outcomes: Sequence[int | float],
        context: Mapping[str, Sequence[object]] | None = None,
    ) -> HierarchicalEBCalibrator:
        p_values, y_values = validate_training_data(probabilities, outcomes)
        context_values = _validate_context(context, self.requires_context, len(p_values))
        self.row_count = len(p_values)
        self.intercept = None
        self.slope = None
        self.offsets = {column: {} for column in self.requires_context}
        self.global_rate = None
        self.iterations = 0

        failure = fit_failure_status(p_values, y_values, self.config)
        if failure is not None:
            self.is_fitted = True
            self.status = f"experimental_{failure}"
            return self

        self.global_rate = sum(y_values) / len(y_values)
        features = [[1.0, logit(self._clip(probability))] for probability in p_values]
        fit = _fit_logistic_regression(
            features,
            y_values,
            config=self.config,
            initial_coefficients=[0.0, 1.0],
        )
        self.iterations = fit.iterations
        if fit.coefficients is None:
            self.is_fitted = True
            self.status = f"experimental_fallback_{fit.status}"
            return self
        if fit.coefficients[1] < 0.0:
            self.is_fitted = True
            self.status = "experimental_fallback_negative_slope"
            return self

        self.intercept = fit.coefficients[0]
        self.slope = fit.coefficients[1]
        base_eta = [
            self.intercept + self.slope * logit(self._clip(probability))
            for probability in p_values
        ]
        self.offsets = _fit_offsets(
            base_eta=base_eta,
            outcomes=y_values,
            context_values=context_values,
            global_rate=self._clip(self.global_rate),
            config=self.config,
        )
        self.is_fitted = True
        self.status = (
            "experimental_fitted"
            if fit.status == "converged"
            else f"experimental_{fit.status}"
        )
        return self

    def predict_proba(self, probabilities: Sequence[float]) -> list[float]:
        del probabilities
        raise ValueError(
            "hierarchical_eb requires predict_proba_with_context with configured context columns"
        )

    def predict_proba_with_context(
        self,
        probabilities: Sequence[float],
        context: Mapping[str, Sequence[object]] | None = None,
    ) -> list[float]:
        self._require_fitted()
        if self.intercept is None or self.slope is None:
            return self._raw_predictions(probabilities)
        context_values = _validate_context(context, self.requires_context, len(probabilities))
        predictions: list[float] = []
        for row_index, probability in enumerate(probabilities):
            eta = self.intercept + self.slope * logit(self._clip(probability))
            for column in self.requires_context:
                level = context_values[column][row_index]
                eta += self.offsets.get(column, {}).get(level, 0.0)
            predictions.append(self._clip(sigmoid(eta)))
        return predictions

    @property
    def parameters(self) -> dict[str, object]:
        return {
            "intercept": self.intercept,
            "slope": self.slope,
            "global_rate": self.global_rate,
            "group_columns": list(self.requires_context),
            "offsets": self.offsets,
            "min_group_rows": self.config.hierarchical_min_group_rows,
            "prior_strength": self.config.hierarchical_prior_strength,
            "backfit_iterations": self.config.hierarchical_backfit_iterations,
            "experimental": True,
        }


def _validate_context(
    context: Mapping[str, Sequence[object]] | None,
    required_columns: Sequence[str],
    expected_length: int,
) -> dict[str, list[str]]:
    if context is None:
        raise ValueError(f"context columns are required: {list(required_columns)}")
    values: dict[str, list[str]] = {}
    missing = [column for column in required_columns if column not in context]
    if missing:
        raise ValueError(f"context missing required columns: {missing}")
    for column in required_columns:
        raw_values = list(context[column])
        if len(raw_values) != expected_length:
            raise ValueError(
                f"context column {column!r} has length {len(raw_values)}; "
                f"expected {expected_length}"
            )
        values[column] = [
            _MISSING_LEVEL if value is None else str(value)
            for value in raw_values
        ]
    return values


def _fit_offsets(
    *,
    base_eta: list[float],
    outcomes: list[float],
    context_values: dict[str, list[str]],
    global_rate: float,
    config: CalibratorConfig,
) -> dict[str, dict[str, float]]:
    offsets: dict[str, dict[str, float]] = {column: {} for column in context_values}
    for _ in range(config.hierarchical_backfit_iterations):
        for column in context_values:
            grouped_indices: defaultdict[str, list[int]] = defaultdict(list)
            for row_index, level in enumerate(context_values[column]):
                grouped_indices[level].append(row_index)
            next_offsets: dict[str, float] = {}
            for level, indices in grouped_indices.items():
                count = len(indices)
                if count < config.hierarchical_min_group_rows:
                    continue
                mean_eta_without_column = _mean_eta_excluding_column(
                    indices=indices,
                    column=column,
                    base_eta=base_eta,
                    context_values=context_values,
                    offsets=offsets,
                )
                outcome_total = sum(outcomes[index] for index in indices)
                smoothed_rate = _smoothed_rate(
                    outcome_total=outcome_total,
                    count=count,
                    global_rate=global_rate,
                    prior_strength=config.hierarchical_prior_strength,
                )
                raw_offset = logit(smoothed_rate) - mean_eta_without_column
                shrinkage = count / (count + config.hierarchical_prior_strength)
                next_offsets[level] = _finite_or_zero(raw_offset * shrinkage)
            offsets[column] = next_offsets
    return offsets


def _mean_eta_excluding_column(
    *,
    indices: list[int],
    column: str,
    base_eta: list[float],
    context_values: dict[str, list[str]],
    offsets: dict[str, dict[str, float]],
) -> float:
    total = 0.0
    for index in indices:
        eta = base_eta[index]
        for other_column, level_values in context_values.items():
            if other_column == column:
                continue
            eta += offsets.get(other_column, {}).get(level_values[index], 0.0)
        total += eta
    return total / len(indices)


def _smoothed_rate(
    *,
    outcome_total: float,
    count: int,
    global_rate: float,
    prior_strength: float,
) -> float:
    denominator = count + prior_strength
    if denominator == 0.0:
        return min(max(global_rate, 1e-12), 1.0 - 1e-12)
    rate = (outcome_total + prior_strength * global_rate) / denominator
    return min(max(rate, 1e-12), 1.0 - 1e-12)


def _finite_or_zero(value: float) -> float:
    return value if math.isfinite(value) else 0.0
