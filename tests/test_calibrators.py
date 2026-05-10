import math
from pathlib import Path

import pytest

from predmkt.calibration import (
    BetaCalibrator,
    BinnedReliabilityCalibrator,
    CalibratorConfig,
    HierarchicalEBCalibrator,
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

    context = _synthetic_context(len(probabilities))

    for name in ("raw", "platt", "beta", "isotonic", "binned_reliability"):
        calibrator = make_calibrator(name, config).fit_with_context(
            probabilities,
            outcomes,
            context,
        )
        predictions = calibrator.predict_proba_with_context(
            [0.0, 0.2, 0.5, 0.8, 1.0],
            _synthetic_context(5),
        )

        assert calibrator.is_fitted is True
        assert calibrator.row_count == len(probabilities)
        assert len(predictions) == 5
        assert all(0.01 <= prediction <= 0.99 for prediction in predictions)

    hierarchical = make_calibrator(
        "hierarchical_eb",
        CalibratorConfig(
            epsilon=0.01,
            min_rows=4,
            hierarchical_min_group_rows=2,
            hierarchical_prior_strength=2.0,
        ),
    ).fit_with_context(probabilities, outcomes, context)
    hierarchical_predictions = hierarchical.predict_proba_with_context(
        [0.2, 0.5, 0.8],
        _synthetic_context(3),
    )
    assert hierarchical.is_fitted is True
    assert hierarchical.is_experimental is True
    assert len(hierarchical_predictions) == 3
    assert all(0.01 <= prediction <= 0.99 for prediction in hierarchical_predictions)


def test_registry_names_aliases_and_unknown_failure() -> None:
    assert {
        "raw",
        "platt",
        "logistic",
        "beta",
        "isotonic",
        "binned_reliability",
        "hierarchical_eb",
    } <= set(available_calibrators())
    assert isinstance(make_calibrator("raw"), RawCalibrator)
    assert isinstance(make_calibrator("platt"), PlattCalibrator)
    assert isinstance(make_calibrator("logistic"), PlattCalibrator)
    assert isinstance(make_calibrator("beta"), BetaCalibrator)
    assert isinstance(make_calibrator("isotonic"), IsotonicCalibrator)
    assert isinstance(make_calibrator("binned_reliability"), BinnedReliabilityCalibrator)
    assert isinstance(make_calibrator("hierarchical_eb"), HierarchicalEBCalibrator)

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


def test_binned_reliability_smoothing_and_monotonicity() -> None:
    calibrator = BinnedReliabilityCalibrator(
        CalibratorConfig(
            epsilon=0.001,
            min_rows=4,
            reliability_bin_count=4,
            reliability_min_bin_count=2,
            reliability_prior_strength=1.0,
            reliability_monotone=True,
        )
    ).fit(
        [0.05, 0.15, 0.35, 0.45, 0.75, 0.85, 0.95, 0.99],
        [0, 0, 1, 0, 1, 1, 1, 1],
    )

    predictions = calibrator.predict_proba([0.1, 0.4, 0.8, 0.99])

    assert predictions == sorted(predictions)
    assert calibrator.parameters["bin_count"] == 4
    assert all(0.001 <= prediction <= 0.999 for prediction in predictions)


def test_hierarchical_eb_uses_context_and_falls_back_for_unseen_levels() -> None:
    probabilities, outcomes = _synthetic_data()
    config = CalibratorConfig(
        epsilon=0.001,
        min_rows=4,
        hierarchical_min_group_rows=2,
        hierarchical_prior_strength=2.0,
        hierarchical_backfit_iterations=2,
    )
    calibrator = HierarchicalEBCalibrator(config).fit_with_context(
        probabilities,
        outcomes,
        _synthetic_context(len(probabilities)),
    )

    seen = calibrator.predict_proba_with_context(
        [0.7],
        {"horizon_name": ["near"], "domain": ["macro"]},
    )
    unseen = calibrator.predict_proba_with_context(
        [0.7],
        {"horizon_name": ["new"], "domain": ["unknown"]},
    )

    assert calibrator.is_experimental is True
    assert calibrator.parameters["experimental"] is True
    assert len(seen) == len(unseen) == 1
    assert all(0.001 <= value <= 0.999 for value in [*seen, *unseen])


def test_hierarchical_eb_requires_context() -> None:
    probabilities, outcomes = _synthetic_data()

    with pytest.raises(ValueError, match="requires fit_with_context"):
        HierarchicalEBCalibrator().fit(probabilities, outcomes)

    with pytest.raises(ValueError, match="context columns are required"):
        HierarchicalEBCalibrator().fit_with_context(probabilities, outcomes, None)


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
outputs:
  artifact_dir: {tmp_path / "artifacts"}
columns:
  probability_column: raw_probability
  outcome_column: observed_outcome
  resolution_column: resolution_ts
  horizon_column: horizon_name
  event_family_column: event_family_id
calibrators:
  enabled: [raw, platt, beta, isotonic, binned_reliability, hierarchical_eb]
prediction:
  epsilon: 0.001
fit:
  min_rows: 4
  max_iterations: 50
  tolerance: 0.00000001
  ridge: 0.000000001
  reliability_bin_count: 4
  reliability_min_bin_count: 2
  reliability_prior_strength: 1.5
  reliability_monotone: true
  hierarchical_group_columns: [horizon_name, domain]
  hierarchical_min_group_rows: 2
  hierarchical_prior_strength: 3.0
  hierarchical_backfit_iterations: 2
evaluation:
  fit_splits: [train, validation]
  fit_label_policy: resolved_by_test_start
  event_family_policy: report_only
  limit_folds:
  limit_rows:
metrics:
  log_loss_epsilon: 0.001
  reliability_bin_count: 5
  reliability_min_bin_count: 2
  calibration_min_rows: 4
  calibration_max_iterations: 50
  calibration_tolerance: 0.00000001
  groupings:
    - name: overall
      columns: []
    - name: horizon
      columns: [horizon_name]
""",
        encoding="utf-8",
    )

    config = load_models_config(config_path)
    calibrators = make_configured_calibrators(config)

    assert config.probability_column == "raw_probability"
    assert config.outcome_column == "observed_outcome"
    assert config.artifact_dir == tmp_path / "artifacts"
    assert config.resolution_column == "resolution_ts"
    assert config.calibrator_config.epsilon == 0.001
    assert config.fit_label_policy == "resolved_by_test_start"
    assert config.calibrator_config.reliability_bin_count == 4
    assert config.calibrator_config.hierarchical_group_columns == ("horizon_name", "domain")
    assert config.metric_groupings[0]["name"] == "overall"
    assert [calibrator.name for calibrator in calibrators] == [
        "raw",
        "platt",
        "beta",
        "isotonic",
        "binned_reliability",
        "hierarchical_eb",
    ]
    assert config.config_sha256


def _synthetic_data() -> tuple[list[float], list[int]]:
    probabilities = [0.05, 0.1, 0.2, 0.35, 0.45, 0.55, 0.7, 0.8, 0.9, 0.95]
    outcomes = [0, 0, 0, 0, 1, 0, 1, 1, 1, 1]
    return probabilities, outcomes


def _synthetic_context(row_count: int) -> dict[str, list[str]]:
    return {
        "horizon_name": ["near" if index % 2 == 0 else "far" for index in range(row_count)],
        "domain": ["macro" if index < row_count / 2 else "sports" for index in range(row_count)],
    }
