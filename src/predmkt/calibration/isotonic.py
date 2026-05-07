"""Dependency-free isotonic recalibration."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass, field

from predmkt.calibration.base import BaseCalibrator, CalibratorConfig, validate_training_data


@dataclass
class IsotonicCalibrator(BaseCalibrator):
    """Monotone nondecreasing recalibration by pool-adjacent-violators."""

    config: CalibratorConfig = field(default_factory=CalibratorConfig)
    name: str = "isotonic"
    thresholds: list[float] = field(default_factory=list)
    values: list[float] = field(default_factory=list)

    def fit(
        self,
        probabilities: Sequence[float],
        outcomes: Sequence[int | float],
    ) -> IsotonicCalibrator:
        p_values, y_values = validate_training_data(probabilities, outcomes)
        self.row_count = len(p_values)
        self.thresholds = []
        self.values = []
        if len(p_values) == 0:
            self.is_fitted = True
            self.status = "fallback_too_few_rows"
            return self

        pairs = sorted(
            (self._clip(probability), outcome)
            for probability, outcome in zip(p_values, y_values, strict=True)
        )
        blocks: list[_IsotonicBlock] = []
        for probability, outcome in pairs:
            blocks.append(_IsotonicBlock(end_probability=probability, total=outcome, weight=1))
            while len(blocks) >= 2 and blocks[-2].mean > blocks[-1].mean:
                right = blocks.pop()
                left = blocks.pop()
                blocks.append(
                    _IsotonicBlock(
                        end_probability=right.end_probability,
                        total=left.total + right.total,
                        weight=left.weight + right.weight,
                    )
                )

        self.thresholds = [block.end_probability for block in blocks]
        self.values = [self._clip(block.mean) for block in blocks]
        self.is_fitted = True
        self.status = "fitted"
        return self

    def predict_proba(self, probabilities: Sequence[float]) -> list[float]:
        self._require_fitted()
        if not self.thresholds or not self.values:
            return self._raw_predictions(probabilities)
        predictions: list[float] = []
        for probability in probabilities:
            clipped = self._clip(probability)
            index = bisect_left(self.thresholds, clipped)
            if index >= len(self.values):
                index = len(self.values) - 1
            predictions.append(self._clip(self.values[index]))
        return predictions

    @property
    def parameters(self) -> dict[str, float | list[float] | list[int] | None]:
        return {"thresholds": self.thresholds, "values": self.values}


@dataclass
class _IsotonicBlock:
    end_probability: float
    total: float
    weight: int

    @property
    def mean(self) -> float:
        return self.total / self.weight
