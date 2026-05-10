import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from predmkt.metrics.decomposition import (
    evaluate_decomposition,
    load_decomposition_config,
    murphy_decomposition,
)


def test_murphy_decomposition_known_components() -> None:
    probabilities = [0.1, 0.2, 0.8, 0.9]
    outcomes = [0.0, 0.0, 1.0, 1.0]

    components, bins = murphy_decomposition(
        probabilities,
        outcomes,
        bin_count=2,
        min_bin_count=2,
        min_rows=1,
    )

    assert components["reliability"] == pytest.approx(0.0225)
    assert components["resolution"] == pytest.approx(0.25)
    assert components["uncertainty"] == pytest.approx(0.25)
    assert components["decomposed_brier"] == pytest.approx(0.0225)
    assert components["raw_brier"] == pytest.approx(0.025)
    assert components["binning_residual"] == pytest.approx(0.0025)
    assert len(bins) == 2
    assert not any(row["is_sparse"] for row in bins)


def test_binning_residual_is_reported_for_varied_bin_probabilities() -> None:
    components, bins = murphy_decomposition(
        [0.1, 0.4, 0.8, 0.9],
        [0.0, 1.0, 1.0, 1.0],
        bin_count=2,
        min_bin_count=3,
        min_rows=10,
    )

    assert components["decomposed_brier"] == pytest.approx(
        components["reliability"] - components["resolution"] + components["uncertainty"]
    )
    assert components["binning_residual"] != pytest.approx(0.0)
    assert components["status"] == "too_few_rows"
    assert any(row["is_sparse"] for row in bins)


def test_decomposition_script_writes_expected_artifacts(tmp_path: Path) -> None:
    predictions = _predictions()
    predictions_path = tmp_path / "predictions.parquet"
    predictions.to_parquet(predictions_path, index=False)
    config_path = _write_config(tmp_path, predictions_path)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/evaluate_decomposition.py",
            "--config",
            str(config_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "murphy_decomposition" in result.stdout
    assert (tmp_path / "decomposition" / "murphy_decomposition.parquet").exists()
    assert (tmp_path / "decomposition" / "murphy_bins.parquet").exists()
    summary = json.loads((tmp_path / "decomposition" / "summary.json").read_text())
    assert summary["input_row_count"] == len(predictions)
    rows = pd.read_parquet(tmp_path / "decomposition" / "murphy_decomposition.parquet")
    assert {"raw", "platt"} == set(rows["model_name"])
    assert {"overall", "horizon"} == set(rows["grouping_name"])


def test_decomposition_config_loading_and_direct_evaluation(tmp_path: Path) -> None:
    predictions_path = tmp_path / "predictions.parquet"
    _predictions().to_parquet(predictions_path, index=False)
    config = load_decomposition_config(_write_config(tmp_path, predictions_path))

    summary = evaluate_decomposition(config)

    assert config.bin_count == 5
    assert summary.group_count == 6
    assert Path(summary.artifact_paths["murphy_bins"]).exists()


def _write_config(tmp_path: Path, predictions_path: Path) -> Path:
    config_path = tmp_path / "decomposition.yaml"
    config_path.write_text(
        f"""
inputs:
  predictions_path: {predictions_path}
outputs:
  artifact_dir: {tmp_path / "decomposition"}
columns:
  probability_column: predicted_probability
  outcome_column: observed_outcome
  model_column: model_name
decomposition:
  bin_count: 5
  min_bin_count: 2
  min_rows: 2
  groupings:
    - name: overall
      columns: []
    - name: horizon
      columns: [horizon_name]
""",
        encoding="utf-8",
    )
    return config_path


def _predictions() -> pd.DataFrame:
    rows = []
    for model_name, offset in (("raw", 0.0), ("platt", 0.05)):
        for row_id in range(12):
            rows.append(
                {
                    "model_name": model_name,
                    "row_id": row_id,
                    "horizon_name": "1d" if row_id < 6 else "close",
                    "observed_outcome": int(row_id % 3 == 0),
                    "predicted_probability": min(max(0.1 + row_id * 0.06 + offset, 0.001), 0.999),
                }
            )
    return pd.DataFrame(rows)
