"""Fixed-width reliability-bin recalibration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from predmkt.calibration.base import (
    BaseCalibrator,
    CalibratorConfig,
    validate_training_data,
)


@dataclass
class BinnedReliabilityCalibrator(BaseCalibrator):
    """Map probabilities to smoothed empirical outcome rates by probability bin."""

    config: CalibratorConfig = field(default_factory=CalibratorConfig)
    name: str = "binned_reliability"
    global_rate: float | None = None
    bin_values: list[float] = field(default_factory=list)
    bin_counts: list[int] = field(default_factory=list)
    sparse_bin_count: int = 0
    empty_bin_count: int = 0

    def fit(
        self,
        probabilities: Sequence[float],
        outcomes: Sequence[int | float],
    ) -> BinnedReliabilityCalibrator:
        p_values, y_values = validate_training_data(probabilities, outcomes)
        self.row_count = len(p_values)
        self.global_rate = None
        self.bin_values = []
        self.bin_counts = []
        self.sparse_bin_count = 0
        self.empty_bin_count = 0
        if len(p_values) == 0 or len(p_values) < self.config.min_rows:
            self.is_fitted = True
            self.status = "fallback_too_few_rows"
            return self

        bin_count = self.config.reliability_bin_count
        totals = [0.0] * bin_count
        counts = [0] * bin_count
        for probability, outcome in zip(p_values, y_values, strict=True):
            index = _bin_index(probability, bin_count)
            totals[index] += outcome
            counts[index] += 1

        self.global_rate = sum(y_values) / len(y_values)
        values: list[float] = []
        for total, count in zip(totals, counts, strict=True):
            denominator = count + self.config.reliability_prior_strength
            if denominator == 0.0:
                smoothed = self.global_rate
            else:
                smoothed = (
                    total + self.config.reliability_prior_strength * self.global_rate
                ) / denominator
            values.append(self._clip(smoothed))

        if self.config.reliability_monotone:
            weights = [
                max(1e-12, count + self.config.reliability_prior_strength)
                for count in counts
            ]
            values = [_value for _value in _pav(values, weights)]

        self.bin_values = [self._clip(value) for value in values]
        self.bin_counts = counts
        self.empty_bin_count = sum(1 for count in counts if count == 0)
        self.sparse_bin_count = sum(
            1 for count in counts if 0 < count < self.config.reliability_min_bin_count
        )
        self.is_fitted = True
        self.status = "fitted_with_sparse_bins" if self.sparse_bin_count else "fitted"
        return self

    def predict_proba(self, probabilities: Sequence[float]) -> list[float]:
        self._require_fitted()
        if not self.bin_values:
            return self._raw_predictions(probabilities)
        bin_count = len(self.bin_values)
        return [
            self._clip(self.bin_values[_bin_index(probability, bin_count)])
            for probability in probabilities
        ]

    @property
    def parameters(self) -> dict[str, object]:
        return {
            "global_rate": self.global_rate,
            "bin_count": len(self.bin_values),
            "bin_values": self.bin_values,
            "bin_counts": self.bin_counts,
            "empty_bin_count": self.empty_bin_count,
            "sparse_bin_count": self.sparse_bin_count,
            "prior_strength": self.config.reliability_prior_strength,
            "monotone": self.config.reliability_monotone,
        }


def _bin_index(probability: float, bin_count: int) -> int:
    clipped = min(max(float(probability), 0.0), 1.0)
    return min(int(clipped * bin_count), bin_count - 1)


@dataclass
class _Block:
    start: int
    end: int
    total: float
    weight: float

    @property
    def mean(self) -> float:
        return self.total / self.weight


def _pav(values: list[float], weights: list[float]) -> list[float]:
    blocks: list[_Block] = []
    for index, (value, weight) in enumerate(zip(values, weights, strict=True)):
        blocks.append(_Block(start=index, end=index, total=value * weight, weight=weight))
        while len(blocks) >= 2 and blocks[-2].mean > blocks[-1].mean:
            right = blocks.pop()
            left = blocks.pop()
            blocks.append(
                _Block(
                    start=left.start,
                    end=right.end,
                    total=left.total + right.total,
                    weight=left.weight + right.weight,
                )
            )
    smoothed = [0.0] * len(values)
    for block in blocks:
        for index in range(block.start, block.end + 1):
            smoothed[index] = block.mean
    return smoothed
