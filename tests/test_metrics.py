import json
import math
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from predmkt.metrics.calibration import fit_calibration_intercept_slope
from predmkt.metrics.evaluation import (
    MetricsConfig,
    evaluate_raw_panel,
    load_metrics_config,
)
from predmkt.metrics.reliability import expected_calibration_error, reliability_bins
from predmkt.metrics.scoring import brier_score, log_loss


def test_brier_log_loss_and_ece_known_values() -> None:
    probabilities = [0.2, 0.8]
    outcomes = [0, 1]

    assert brier_score(probabilities, outcomes) == pytest.approx(0.04)
    assert log_loss(probabilities, outcomes, epsilon=0.001) == pytest.approx(-math.log(0.8))

    bins = reliability_bins(probabilities, outcomes, bin_count=2, min_bin_count=2)
    assert expected_calibration_error(bins) == pytest.approx(0.2)
    assert [item.row_count for item in bins] == [1, 1]
    assert all(item.is_sparse for item in bins)


def test_log_loss_clips_zero_and_one() -> None:
    assert log_loss([0.0, 1.0], [1, 0], epsilon=0.01) == pytest.approx(-math.log(0.01))


def test_reliability_bins_keep_empty_bins() -> None:
    bins = reliability_bins([0.05, 0.95], [0, 1], bin_count=4, min_bin_count=2)

    assert [item.row_count for item in bins] == [1, 0, 0, 1]
    assert bins[1].is_empty is True
    assert bins[2].is_empty is True
    assert bins[0].is_sparse is True


def test_calibration_fit_returns_finite_coefficients_and_degenerate_status() -> None:
    probabilities = [0.1, 0.2, 0.35, 0.4, 0.6, 0.7, 0.85, 0.9]
    outcomes = [0, 0, 0, 1, 0, 1, 1, 1]

    fit = fit_calibration_intercept_slope(
        probabilities,
        outcomes,
        epsilon=0.001,
        min_rows=4,
        max_iterations=100,
    )

    assert fit.intercept is not None
    assert fit.slope is not None
    assert math.isfinite(fit.intercept)
    assert math.isfinite(fit.slope)
    assert fit.row_count == 8

    degenerate = fit_calibration_intercept_slope(
        [0.2, 0.4, 0.6, 0.8],
        [1, 1, 1, 1],
        epsilon=0.001,
        min_rows=4,
    )
    assert degenerate.status == "outcome_has_no_variation"
    assert degenerate.intercept is None


def test_load_metrics_config(tmp_path: Path) -> None:
    config_path = tmp_path / "metrics.yaml"
    config_path.write_text(_config_text(tmp_path), encoding="utf-8")

    config = load_metrics_config(config_path)

    assert config.panel_path == tmp_path / "panel.parquet"
    assert config.artifact_dir == tmp_path / "artifacts"
    assert config.log_loss_epsilon == 0.001
    assert config.primary_aggregation == "equal_contract"
    assert config.secondary_aggregations == ("equal_event_family",)
    assert config.include_trade_weighted_robustness is False
    assert config.config_sha256


def test_evaluate_raw_writes_artifacts_and_is_not_trade_weighted_by_default(tmp_path: Path) -> None:
    panel_path = tmp_path / "panel.parquet"
    pq.write_table(_panel_table(), panel_path)
    config_path = tmp_path / "metrics.yaml"
    config_path.write_text(_config_text(tmp_path), encoding="utf-8")
    config = load_metrics_config(config_path)

    summary = evaluate_raw_panel(config)

    assert summary.input_row_count == 6
    assert summary.scored_row_count == 6
    assert summary.primary_aggregation == "equal_contract"
    assert "trade_weighted" not in summary.aggregation_modes
    assert summary.missing_feature_note_count == 2
    for artifact in summary.artifact_paths.values():
        assert Path(artifact).exists()

    metrics = pq.read_table(tmp_path / "artifacts" / "metrics_overall.parquet").to_pylist()
    equal_contract = [
        row for row in metrics if row["aggregation_mode"] == "equal_contract"
    ][0]
    trade_weighted_brier = (0.01 * 1000 + 0.81 + 0.01 + 0.01 + 0.04 + 0.04) / 1005

    assert equal_contract["brier_score"] == pytest.approx(0.15333333333333335)
    assert equal_contract["brier_score"] != pytest.approx(trade_weighted_brier)
    assert equal_contract["expected_calibration_error"] is not None

    group_metrics = pq.read_table(tmp_path / "artifacts" / "metrics_by_group.parquet")
    assert "equal_event_family" in set(group_metrics.column("aggregation_mode").to_pylist())

    reliability = pq.read_table(tmp_path / "artifacts" / "reliability_bins.parquet").to_pylist()
    overall_bins = [row for row in reliability if row["grouping_name"] == "overall"]
    assert len(overall_bins) == 5
    assert any(row["is_empty"] for row in overall_bins)

    calibration = pq.read_table(tmp_path / "artifacts" / "calibration_fits.parquet").to_pylist()
    assert {row["grouping_name"] for row in calibration} >= {"overall", "horizon"}

    notes = pq.read_table(tmp_path / "artifacts" / "missing_feature_notes.parquet").to_pylist()
    assert {row["field"] for row in notes} == {"domain", "category"}

    summary_json = json.loads((tmp_path / "artifacts" / "summary.json").read_text())
    assert summary_json["effective_config"]["aggregation"]["primary"] == "equal_contract"


def test_trade_weighted_mode_requires_explicit_config(tmp_path: Path) -> None:
    panel_path = tmp_path / "panel.parquet"
    pq.write_table(_panel_table(), panel_path)
    config = MetricsConfig(
        panel_path=panel_path,
        artifact_dir=tmp_path / "artifacts",
        probability_column="raw_probability",
        outcome_column="observed_outcome",
        log_loss_epsilon=0.001,
        reliability_bin_count=5,
        reliability_min_bin_count=2,
        calibration_min_rows=4,
        calibration_max_iterations=50,
        calibration_tolerance=1e-8,
        primary_aggregation="equal_contract",
        secondary_aggregations=("equal_event_family",),
        include_trade_weighted_robustness=True,
        trade_weight_column="cumulative_volume_to_forecast",
        groupings=(
            _grouping("overall", ()),
            _grouping("horizon", ("horizon_name",)),
        ),
        buckets=(),
    )

    summary = evaluate_raw_panel(config)

    assert "trade_weighted" in summary.aggregation_modes
    metrics = pq.read_table(tmp_path / "artifacts" / "metrics_overall.parquet").to_pylist()
    weighted = [row for row in metrics if row["aggregation_mode"] == "trade_weighted"][0]
    assert weighted["total_weight"] == 1005


def _panel_table() -> pa.Table:
    return pa.table(
        {
            "contract_id": ["C1", "C2", "C3", "C4", "C5", "C6"],
            "event_family_id": ["E1", "E1", "E2", "E2", "E3", "E4"],
            "horizon_name": ["1d", "1d", "1d", "7d", "7d", "7d"],
            "domain": ["unknown"] * 6,
            "category": ["unknown"] * 6,
            "raw_probability": [0.9, 0.9, 0.1, 0.9, 0.2, 0.8],
            "observed_outcome": [1, 0, 0, 1, 0, 1],
            "public_liquidity_proxy": [10.0, 10.0, 0.1, 0.1, 3.0, 3.0],
            "price_staleness_seconds": [60, 60, 7200, 7200, 100000, 100000],
            "cumulative_volume_to_forecast": [1000, 1, 1, 1, 1, 1],
        }
    )


def _config_text(tmp_path: Path) -> str:
    return f"""
inputs:
  panel_path: {tmp_path / "panel.parquet"}
outputs:
  artifact_dir: {tmp_path / "artifacts"}
metrics:
  probability_column: raw_probability
  outcome_column: observed_outcome
  log_loss_epsilon: 0.001
  limit_rows:
reliability:
  bin_count: 5
  min_bin_count: 2
calibration:
  min_rows: 4
  max_iterations: 50
  tolerance: 0.00000001
aggregation:
  primary: equal_contract
  secondary:
    - equal_event_family
  include_trade_weighted_robustness: false
  trade_weight_column: cumulative_volume_to_forecast
grouping:
  dimensions:
    - name: overall
      columns: []
    - name: horizon
      columns: [horizon_name]
    - name: domain
      columns: [domain]
    - name: category
      columns: [category]
    - name: liquidity
      columns: [liquidity_bucket]
    - name: staleness
      columns: [staleness_bucket]
buckets:
  liquidity:
    column: public_liquidity_proxy
    output_column: liquidity_bucket
    edges: [2.0, 5.0]
    labels: [low, medium, high]
  staleness:
    column: price_staleness_seconds
    output_column: staleness_bucket
    edges: [3600, 86400]
    labels: [fresh, day, stale]
"""


def _grouping(name: str, columns: tuple[str, ...]):
    from predmkt.metrics.evaluation import GroupingConfig

    return GroupingConfig(name=name, columns=columns)
