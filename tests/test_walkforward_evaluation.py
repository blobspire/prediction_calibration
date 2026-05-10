import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from predmkt.calibration import load_models_config
from predmkt.validation.walkforward import WalkForwardEvaluationError, evaluate_walkforward


def test_walkforward_evaluation_writes_expected_artifacts(tmp_path: Path) -> None:
    panel_path = tmp_path / "panel.parquet"
    splits_path = tmp_path / "splits.parquet"
    _panel().to_parquet(panel_path, index=False)
    _splits().to_parquet(splits_path, index=False)
    config = _config(tmp_path, panel_path=panel_path, splits_path=splits_path)

    summary = evaluate_walkforward(config)

    assert summary.fold_count == 1
    assert summary.model_names == [
        "beta",
        "binned_reliability",
        "hierarchical_eb",
        "isotonic",
        "platt",
        "raw",
    ]
    assert summary.event_family_overlap_count >= 1
    for artifact in summary.artifact_paths.values():
        assert Path(artifact).exists()

    predictions = pq.read_table(tmp_path / "artifacts" / "predictions.parquet").to_pandas()
    assert "close_time" in predictions.columns
    expected_test_rows = {6, 7, 8, 9}
    for _, frame in predictions.groupby("model_name"):
        assert set(frame["row_id"]) == expected_test_rows
    raw = predictions[predictions["model_name"] == "raw"].sort_values("row_id")
    assert raw["predicted_probability"].tolist() == pytest.approx(
        raw["raw_probability"].tolist()
    )
    assert predictions["predicted_probability"].between(0.001, 0.999).all()

    fits = pq.read_table(tmp_path / "artifacts" / "calibrator_fits.parquet").to_pandas()
    assert set(fits["model_name"]) == {
        "raw",
        "platt",
        "beta",
        "isotonic",
        "binned_reliability",
        "hierarchical_eb",
    }
    assert set(fits["fit_row_count"]) == {4}
    assert set(fits["excluded_future_label_count"]) == {2}
    hierarchical = fits[fits["model_name"] == "hierarchical_eb"].iloc[0]
    assert bool(hierarchical["is_experimental"]) is True
    assert "domain" in hierarchical["context_columns_json"]

    fold_metrics = pq.read_table(tmp_path / "artifacts" / "fold_metrics.parquet").to_pandas()
    assert {"brier_score", "log_loss", "expected_calibration_error"} <= set(
        fold_metrics.columns
    )
    assert {"overall", "horizon"} <= set(fold_metrics["grouping_name"])

    aggregate = pq.read_table(tmp_path / "artifacts" / "aggregate_metrics.parquet").to_pandas()
    assert {"pooled_equal_contract", "fold_macro"} <= set(aggregate["metric_scope"])

    leakage = pq.read_table(
        tmp_path / "artifacts" / "event_family_leakage.parquet"
    ).to_pandas()
    assert "E_SHARED" in set(leakage["event_family_id"])

    summary_json = json.loads((tmp_path / "artifacts" / "summary.json").read_text())
    assert summary_json["effective_config"]["evaluation"]["fit_label_policy"] == (
        "resolved_by_test_start"
    )
    assert summary_json["git_commit"] is not None


def test_future_label_fit_rows_fail_if_not_filtered(tmp_path: Path) -> None:
    panel_path = tmp_path / "panel.parquet"
    splits_path = tmp_path / "splits.parquet"
    panel = _panel()
    panel.loc[0:5, "resolution_ts"] = pd.Timestamp("2024-02-15", tz="UTC")
    panel.to_parquet(panel_path, index=False)
    _splits().to_parquet(splits_path, index=False)
    config = _config(tmp_path, panel_path=panel_path, splits_path=splits_path)

    with pytest.raises(WalkForwardEvaluationError, match="no label-available fit rows"):
        evaluate_walkforward(config)


def test_split_panel_key_mismatch_fails(tmp_path: Path) -> None:
    panel_path = tmp_path / "panel.parquet"
    splits_path = tmp_path / "splits.parquet"
    _panel().to_parquet(panel_path, index=False)
    splits = _splits()
    splits.loc[0, "contract_id"] = "WRONG"
    splits.to_parquet(splits_path, index=False)
    config = _config(tmp_path, panel_path=panel_path, splits_path=splits_path)

    with pytest.raises(WalkForwardEvaluationError, match="key mismatch"):
        evaluate_walkforward(config)


def test_context_aware_calibrator_requires_context_columns(tmp_path: Path) -> None:
    panel_path = tmp_path / "panel.parquet"
    splits_path = tmp_path / "splits.parquet"
    _panel().drop(columns=["domain"]).to_parquet(panel_path, index=False)
    _splits().to_parquet(splits_path, index=False)
    config = _config(tmp_path, panel_path=panel_path, splits_path=splits_path)

    with pytest.raises(WalkForwardEvaluationError, match="modeling panel missing columns"):
        evaluate_walkforward(config)


def test_fit_walkforward_script_smoke(tmp_path: Path) -> None:
    panel_path = tmp_path / "panel.parquet"
    splits_path = tmp_path / "splits.parquet"
    config_path = tmp_path / "models.yaml"
    _panel().to_parquet(panel_path, index=False)
    _splits().to_parquet(splits_path, index=False)
    config_path.write_text(_config_text(tmp_path, panel_path, splits_path), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/fit_walkforward.py",
            "--config",
            str(config_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "prediction_row_count" in result.stdout
    assert (tmp_path / "artifacts" / "predictions.parquet").exists()


def _panel() -> pd.DataFrame:
    rows = []
    forecasts = [
        "2023-10-05",
        "2023-10-10",
        "2023-11-05",
        "2023-11-10",
        "2023-12-05",
        "2023-12-10",
        "2024-01-05",
        "2024-01-10",
        "2024-01-15",
        "2024-01-20",
    ]
    probabilities = [0.1, 0.2, 0.25, 0.35, 0.4, 0.7, 0.15, 0.55, 0.75, 0.9]
    outcomes = [0, 0, 0, 1, 1, 1, 0, 1, 1, 1]
    event_families = [
        "E1",
        "E2",
        "E3",
        "E_SHARED",
        "E_FUTURE",
        "E_SHARED",
        "E_SHARED",
        "E7",
        "E8",
        "E9",
    ]
    for row_id, forecast in enumerate(forecasts):
        resolution = "2024-02-15" if row_id in {4, 5} else "2023-12-20"
        rows.append(
            {
                "contract_id": f"C{row_id}",
                "event_family_id": event_families[row_id],
                "horizon_name": "1d" if row_id % 2 == 0 else "7d",
                "domain": "macro" if row_id % 2 == 0 else "sports",
                "forecast_ts": pd.Timestamp(forecast, tz="UTC"),
                "close_time": pd.Timestamp(resolution, tz="UTC"),
                "resolution_ts": pd.Timestamp(resolution, tz="UTC"),
                "raw_probability": probabilities[row_id],
                "observed_outcome": outcomes[row_id],
            }
        )
    return pd.DataFrame(rows)


def _splits() -> pd.DataFrame:
    panel = _panel()
    split_names = ["train"] * 4 + ["validation"] * 2 + ["test"] * 4
    rows = []
    for row_id, row in panel.reset_index().iterrows():
        rows.append(
            {
                "fold_id": "fold_2024_01",
                "split": split_names[row_id],
                "row_id": row_id,
                "contract_id": row["contract_id"],
                "horizon": row["horizon_name"],
                "forecast_ts": row["forecast_ts"],
                "event_family_id": row["event_family_id"],
            }
        )
    return pd.DataFrame(rows)


def _config(tmp_path: Path, *, panel_path: Path, splits_path: Path):
    config_path = tmp_path / "models.yaml"
    config_path.write_text(_config_text(tmp_path, panel_path, splits_path), encoding="utf-8")
    return replace(load_models_config(config_path), config_path=config_path)


def _config_text(tmp_path: Path, panel_path: Path, splits_path: Path) -> str:
    return f"""
inputs:
  panel_path: {panel_path}
  splits_path: {splits_path}
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
  reliability_bin_count: 5
  reliability_min_bin_count: 1
  reliability_prior_strength: 2.0
  reliability_monotone: true
  hierarchical_group_columns: [horizon_name, domain]
  hierarchical_min_group_rows: 2
  hierarchical_prior_strength: 2.0
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
  reliability_min_bin_count: 1
  calibration_min_rows: 4
  calibration_max_iterations: 50
  calibration_tolerance: 0.00000001
  groupings:
    - name: overall
      columns: []
    - name: horizon
      columns: [horizon_name]
"""
