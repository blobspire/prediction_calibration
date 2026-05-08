from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from predmkt.inference import (
    InferenceError,
    benjamini_hochberg,
    effective_cluster_count,
    load_inference_config,
    run_inference,
)


def test_benjamini_hochberg_known_values() -> None:
    q_values, rejected = benjamini_hochberg([0.01, 0.04, 0.03, 0.002], alpha=0.05)

    assert q_values == pytest.approx([0.02, 0.04, 0.04, 0.008])
    assert rejected == [True, True, True, True]


def test_effective_cluster_count_uses_kish_formula() -> None:
    assert effective_cluster_count([2, 2, 4]) == pytest.approx(64 / 24)


def test_run_inference_writes_artifacts_and_known_paired_delta(tmp_path: Path) -> None:
    config = load_inference_config(_write_fixture(tmp_path))

    summary = run_inference(config)

    assert summary.bootstrap_unit == "event_family_id"
    for artifact_name in (
        "score_intervals",
        "paired_score_differences",
        "calibration_intervals",
        "multiple_comparison_adjustments",
        "paired_loss_diagnostics",
        "bootstrap_replicates",
        "summary",
    ):
        assert Path(summary.artifact_paths[artifact_name]).exists()
    paired = pd.read_parquet(Path(summary.artifact_paths["paired_score_differences"]))
    brier = paired[
        (paired["model_name"] == "platt")
        & (paired["metric_name"] == "brier_score")
        & (paired["grouping_name"] == "overall")
    ].iloc[0]
    assert brier["estimate_delta"] == pytest.approx(-0.08)
    assert brier["bootstrap_unit"] == "event_family_id"
    assert brier["aggregation_mode"] == "equal_contract"
    assert pd.notna(brier["q_value"])
    calibration = pd.read_parquet(Path(summary.artifact_paths["calibration_intervals"]))
    usable = calibration[calibration["bootstrap_status"] == "ok"]
    assert not usable.empty
    assert usable["ci_lower"].notna().any()


def test_deterministic_seed_reproduces_intervals(tmp_path: Path) -> None:
    config = load_inference_config(_write_fixture(tmp_path))
    first = run_inference(replace(config, artifact_dir=tmp_path / "first"))
    second = run_inference(replace(config, artifact_dir=tmp_path / "second"))

    left = pd.read_parquet(Path(first.artifact_paths["paired_score_differences"]))
    right = pd.read_parquet(Path(second.artifact_paths["paired_score_differences"]))

    pd.testing.assert_frame_equal(left, right)


def test_sparse_groups_return_explicit_status(tmp_path: Path) -> None:
    config = load_inference_config(_write_fixture(tmp_path))
    summary = run_inference(
        replace(config, min_rows=1, min_clusters=99, artifact_dir=tmp_path / "sparse")
    )

    scores = pd.read_parquet(Path(summary.artifact_paths["score_intervals"]))

    assert set(scores["bootstrap_status"]) == {"too_few_clusters"}
    assert scores["ci_lower"].isna().all()


def test_iid_or_row_bootstrap_is_rejected(tmp_path: Path) -> None:
    config = load_inference_config(_write_fixture(tmp_path))

    with pytest.raises(InferenceError, match="cluster"):
        run_inference(replace(config, bootstrap_unit="row_id", artifact_dir=tmp_path / "bad"))


def test_prediction_panel_key_mismatch_fails(tmp_path: Path) -> None:
    config_path = _write_fixture(tmp_path, bad_panel_key=True)
    config = load_inference_config(config_path)

    with pytest.raises(InferenceError, match="prediction/panel key mismatch"):
        run_inference(config)


def test_run_inference_script_smoke(tmp_path: Path) -> None:
    config_path = _write_fixture(tmp_path)
    repo = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_inference.py",
            "--config",
            str(config_path),
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "score_intervals" in result.stdout
    assert (tmp_path / "inference" / "summary.json").exists()


def _write_fixture(tmp_path: Path, *, bad_panel_key: bool = False) -> Path:
    predictions_path = tmp_path / "predictions.parquet"
    panel_path = tmp_path / "panel.parquet"
    aggregate_path = tmp_path / "aggregate_metrics.parquet"
    fold_path = tmp_path / "fold_metrics.parquet"
    _predictions().to_parquet(predictions_path, index=False)
    _panel(bad_panel_key=bad_panel_key).to_parquet(panel_path, index=False)
    pd.DataFrame({"metric_scope": ["pooled_equal_contract"]}).to_parquet(
        aggregate_path,
        index=False,
    )
    pd.DataFrame({"metric_scope": ["fold"]}).to_parquet(fold_path, index=False)
    config_path = tmp_path / "inference.yaml"
    config_path.write_text(
        f"""
inputs:
  predictions_path: {predictions_path}
  panel_path: {panel_path}
  aggregate_metrics_path: {aggregate_path}
  fold_metrics_path: {fold_path}
outputs:
  artifact_dir: {tmp_path / "inference"}
columns:
  row_id_column: row_id
  contract_column: contract_id
  horizon_column: horizon_name
  cluster_column: event_family_id
  outcome_column: observed_outcome
  raw_probability_column: raw_probability
  predicted_probability_column: predicted_probability
inference:
  baseline_model: raw
  comparison_models: [platt, beta, isotonic]
  bootstrap_unit: event_family_id
  bootstrap_iterations: 20
  confidence_level: 0.95
  random_seed: 20260507
  min_rows: 4
  min_clusters: 2
  fdr_alpha: 0.10
  log_loss_epsilon: 0.000001
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
    - name: domain
      columns: [domain]
    - name: liquidity
      columns: [liquidity_bucket]
  calibration_groupings:
    - name: overall
      columns: []
    - name: horizon
      columns: [horizon_name]
  buckets:
    liquidity_bucket:
      column: public_liquidity_proxy
      edges: [2.0, 5.0]
      labels: [low, medium, high]
""",
        encoding="utf-8",
    )
    return config_path


def _predictions() -> pd.DataFrame:
    probabilities = {
        "raw": [0.2, 0.8, 0.3, 0.7],
        "platt": [0.1, 0.9, 0.4, 0.6],
        "beta": [0.18, 0.82, 0.28, 0.72],
        "isotonic": [0.25, 0.75, 0.35, 0.65],
    }
    outcomes = [0, 1, 1, 0]
    rows = []
    for model_name, values in probabilities.items():
        for row_id, probability in enumerate(values):
            rows.append(
                {
                    "fold_id": "fold_2024_01",
                    "model_name": model_name,
                    "row_id": row_id,
                    "contract_id": f"C{row_id}",
                    "event_family_id": f"E{row_id // 2}",
                    "horizon_name": "1d" if row_id < 2 else "close",
                    "forecast_ts": pd.Timestamp("2024-01-01", tz="UTC"),
                    "resolution_ts": pd.Timestamp("2024-01-02", tz="UTC"),
                    "observed_outcome": outcomes[row_id],
                    "raw_probability": probabilities["raw"][row_id],
                    "predicted_probability": probability,
                    "fit_status": "fitted",
                    "fit_row_count": 4,
                }
            )
    return pd.DataFrame(rows)


def _panel(*, bad_panel_key: bool) -> pd.DataFrame:
    rows = []
    for row_id in range(4):
        rows.append(
            {
                "contract_id": "WRONG" if bad_panel_key and row_id == 0 else f"C{row_id}",
                "event_family_id": f"E{row_id // 2}",
                "horizon_name": "1d" if row_id < 2 else "close",
                "forecast_ts": pd.Timestamp("2024-01-01", tz="UTC"),
                "resolution_ts": pd.Timestamp("2024-01-02", tz="UTC"),
                "domain": "sports" if row_id < 2 else "finance",
                "category": "basketball" if row_id < 2 else "crypto",
                "taxonomy_confidence": "high",
                "taxonomy_ambiguous": False,
                "is_sports": row_id < 2,
                "public_liquidity_proxy": 1.0 + row_id * 2.0,
                "price_staleness_seconds": 60.0 * row_id,
            }
        )
    return pd.DataFrame(rows)
