"""Raw probability baseline calibrator."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from predmkt.calibration.base import BaseCalibrator, CalibratorConfig, validate_training_data


@dataclass
class RawCalibrator(BaseCalibrator):
    """No-op baseline that returns clipped input probabilities."""

    config: CalibratorConfig = field(default_factory=CalibratorConfig)
    name: str = "raw"

    def fit(
        self,
        probabilities: Sequence[float],
        outcomes: Sequence[int | float],
    ) -> RawCalibrator:
        validate_training_data(probabilities, outcomes)
        self.row_count = len(probabilities)
        self.is_fitted = True
        self.status = "fitted"
        return self

    def predict_proba(self, probabilities: Sequence[float]) -> list[float]:
        self._require_fitted()
        return self._raw_predictions(probabilities)
