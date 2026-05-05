"""Reliability bins and expected calibration error."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence


@dataclass(frozen=True)
class ReliabilityBin:
    """One fixed-width reliability bin."""

    bin_index: int
    bin_lower: float
    bin_upper: float
    row_count: int
    mean_predicted_probability: float | None
    observed_frequency: float | None
    absolute_calibration_gap: float | None
    is_empty: bool
    is_sparse: bool


def reliability_bins(
    probabilities: Sequence[float],
    outcomes: Sequence[int | float],
    *,
    bin_count: int,
    min_bin_count: int,
) -> list[ReliabilityBin]:
    """Return fixed-width reliability bins, retaining empty and sparse bins."""

    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have the same length")
    if bin_count <= 0:
        raise ValueError("bin_count must be positive")
    if min_bin_count < 0:
        raise ValueError("min_bin_count cannot be negative")

    rows: list[list[tuple[float, float]]] = [[] for _ in range(bin_count)]
    for probability, outcome in zip(probabilities, outcomes, strict=True):
        if not 0.0 <= float(probability) <= 1.0:
            raise ValueError(f"probability must be in [0, 1]: {probability}")
        if float(outcome) not in (0.0, 1.0):
            raise ValueError(f"outcome must be binary 0/1: {outcome}")
        index = min(int(float(probability) * bin_count), bin_count - 1)
        rows[index].append((float(probability), float(outcome)))

    bins: list[ReliabilityBin] = []
    for index, values in enumerate(rows):
        lower = index / bin_count
        upper = (index + 1) / bin_count
        row_count = len(values)
        if row_count:
            mean_probability = sum(value[0] for value in values) / row_count
            observed_frequency = sum(value[1] for value in values) / row_count
            absolute_gap = abs(mean_probability - observed_frequency)
        else:
            mean_probability = None
            observed_frequency = None
            absolute_gap = None
        bins.append(
            ReliabilityBin(
                bin_index=index,
                bin_lower=lower,
                bin_upper=upper,
                row_count=row_count,
                mean_predicted_probability=mean_probability,
                observed_frequency=observed_frequency,
                absolute_calibration_gap=absolute_gap,
                is_empty=row_count == 0,
                is_sparse=0 < row_count < min_bin_count,
            )
        )
    return bins


def expected_calibration_error(bins: Sequence[ReliabilityBin]) -> float:
    """Return ECE from reliability bins using row-count bin weights."""

    total = sum(item.row_count for item in bins)
    if total == 0:
        raise ValueError("expected_calibration_error requires at least one observation")
    return sum(
        (item.row_count / total) * (item.absolute_calibration_gap or 0.0)
        for item in bins
        if item.row_count
    )
