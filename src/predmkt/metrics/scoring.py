"""Point forecast scoring rules for binary probabilities."""

from __future__ import annotations

import math
from collections.abc import Sequence


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int | float]) -> float:
    """Return the mean Brier score for binary outcomes."""

    _check_same_length(probabilities, outcomes)
    if not probabilities:
        raise ValueError("brier_score requires at least one observation")
    total = 0.0
    for probability, outcome in zip(probabilities, outcomes, strict=True):
        _check_probability(probability)
        _check_outcome(outcome)
        total += (float(probability) - float(outcome)) ** 2
    return total / len(probabilities)


def log_loss(
    probabilities: Sequence[float],
    outcomes: Sequence[int | float],
    *,
    epsilon: float,
) -> float:
    """Return clipped binary log loss."""

    _check_same_length(probabilities, outcomes)
    _check_epsilon(epsilon)
    if not probabilities:
        raise ValueError("log_loss requires at least one observation")
    total = 0.0
    for probability, outcome in zip(probabilities, outcomes, strict=True):
        _check_probability(probability)
        _check_outcome(outcome)
        clipped = clip_probability(float(probability), epsilon)
        total += -(
            float(outcome) * math.log(clipped)
            + (1.0 - float(outcome)) * math.log(1.0 - clipped)
        )
    return total / len(probabilities)


def clip_probability(probability: float, epsilon: float) -> float:
    """Clip a probability into ``[epsilon, 1 - epsilon]``."""

    _check_probability(probability)
    _check_epsilon(epsilon)
    return min(max(probability, epsilon), 1.0 - epsilon)


def _check_same_length(
    probabilities: Sequence[float],
    outcomes: Sequence[int | float],
) -> None:
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have the same length")


def _check_probability(probability: float) -> None:
    if not math.isfinite(float(probability)) or not 0.0 <= float(probability) <= 1.0:
        raise ValueError(f"probability must be finite and in [0, 1]: {probability}")


def _check_outcome(outcome: int | float) -> None:
    if float(outcome) not in (0.0, 1.0):
        raise ValueError(f"outcome must be binary 0/1: {outcome}")


def _check_epsilon(epsilon: float) -> None:
    if not math.isfinite(epsilon) or not 0.0 < epsilon < 0.5:
        raise ValueError("epsilon must be finite and in (0, 0.5)")
