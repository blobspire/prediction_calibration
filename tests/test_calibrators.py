import math
from pathlib import Path

import pytest

from predmkt.calibration import (
    BetaCalibrator,
    CalibratorConfig,
    IsotonicCalibrator,
    PlattCalibrator,
    RawCalibrator,
    available_calibrators,
    load_models_config,
    make_calibrator,
    make_configured_calibrators,
)


def test_all_calibrators_fit_predict_shapes_and_bounds() -> None:
    probabilities, outcomes = _synthetic_data()
    config = CalibratorConfig(epsilon=0.01, min_rows=4)

    for name in ("raw", "platt", "beta", "isotonic"):
        calibrator = make_calibrator(name, config).fit(probabilities, outcomes)
        predictions = calibrator.predict_proba([0.0, 0.2, 0.5, 0.8, 1.0])

        assert calibrator.is_fitted is True
        assert calibrator.row_count == len(probabilities)
        assert len(predictions) == 5
        assert all(0.01 <= prediction <= 0.99 for prediction in predictions)


def test_registry_names_aliases_and_unknown_failure() -> None:
    assert {"raw", "platt", "logistic", "beta", "isotonic"} <= set(available_calibrators())
    assert isinstance(make_calibrator("raw"), RawCalibrator)
    assert isinstance(make_calibrator("platt"), PlattCalibrator)
    assert isinstance(make_calibrator("logistic"), PlattCalibrator)
    assert isinstance(make_calibrator("beta"), BetaCalibrator)
    assert isinstance(make_calibrator("isotonic"), IsotonicCalibrator)

    with pytest.raises(ValueError, match="unknown calibrator"):
        make_calibrator("unknown")


def test_raw_calibrator_returns_clipped_probabilities() -> None:
    calibrator = RawCalibrator(CalibratorConfig(epsilon=0.05)).fit([0.2], [1])

    assert calibrator.predict_proba([0.0, 0.2, 1.0]) == pytest.approx([0.05, 0.2, 0.95])
    assert calibrator.status == "fitted"


def test_platt_and_beta_fit_usable_synthetic_data() -> None:
    probabilities, outcomes = _synthetic_data()
    config = CalibratorConfig(epsilon=0.001, min_rows=4, max_iterations=100)

    for calibrator in (PlattCalibrator(config), BetaCalibrator(config)):
        calibrator.fit(probabilities, outcomes)
        predictions = calibrator.predict_proba([0.1, 0.4, 0.9])

        assert calibrator.status in {"converged", "max_iterations"}
        assert all(math.isfinite(prediction) for prediction in predictions)
        assert all(0.001 <= prediction <= 0.999 for prediction in predictions)
        assert any(value is not None for value in calibrator.parameters.values())


def test_degenerate_platt_and_beta_fallback_to_raw_predictions() -> None:
    config = CalibratorConfig(epsilon=0.01, min_rows=4)

    for calibrator in (PlattCalibrator(config), BetaCalibrator(config)):
        calibrator.fit([0.2, 0.3, 0.4, 0.5], [1, 1, 1, 1])

        assert calibrator.status == "fallback_outcome_has_no_variation"
        assert calibrator.predict_proba([0.0, 0.5, 1.0]) == pytest.approx([0.01, 0.5, 0.99])


def test_isotonic_predictions_are_monotone_for_sorted_probabilities() -> None:
    calibrator = IsotonicCalibrator(CalibratorConfig(epsilon=0.001)).fit(
        [0.1, 0.2, 0.3, 0.4, 0.8, 0.9],
        [0, 1, 0, 1, 1, 1],
    )
    predictions = calibrator.predict_proba([0.1, 0.2, 0.3, 0.4, 0.8, 0.9])

    assert predictions == sorted(predictions)
    assert all(0.001 <= prediction <= 0.999 for prediction in predictions)
    assert calibrator.status == "fitted"


def test_invalid_inputs_raise_clear_errors() -> None:
    with pytest.raises(ValueError, match="same length"):
        RawCalibrator().fit([0.1], [0, 1])
    with pytest.raises(ValueError, match="binary"):
        RawCalibrator().fit([0.1], [2])
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        RawCalibrator().fit([1.2], [1])


def test_models_config_loads_and_instantiates_enabled_calibrators(tmp_path: Path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        f"""
inputs:
  panel_path: {tmp_path / "panel.parquet"}
  splits_path: {tmp_path / "splits.parquet"}
columns:
  probability_column: raw_probability
  outcome_column: observed_outcome
calibrators:
  enabled: [raw, platt, beta, isotonic]
prediction:
  epsilon: 0.001
fit:
  min_rows: 4
  max_iterations: 50
  tolerance: 0.00000001
  ridge: 0.000000001
""",
        encoding="utf-8",
    )

    config = load_models_config(config_path)
    calibrators = make_configured_calibrators(config)

    assert config.probability_column == "raw_probability"
    assert config.outcome_column == "observed_outcome"
    assert config.calibrator_config.epsilon == 0.001
    assert [calibrator.name for calibrator in calibrators] == [
        "raw",
        "platt",
        "beta",
        "isotonic",
    ]
    assert config.config_sha256


def _synthetic_data() -> tuple[list[float], list[int]]:
    probabilities = [0.05, 0.1, 0.2, 0.35, 0.45, 0.55, 0.7, 0.8, 0.9, 0.95]
    outcomes = [0, 0, 0, 0, 1, 0, 1, 1, 1, 1]
    return probabilities, outcomes
