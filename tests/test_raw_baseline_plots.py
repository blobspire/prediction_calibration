from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from predmkt.plots.raw_baseline import (
    RawBaselinePlotConfig,
    build_raw_baseline_plots,
    load_raw_baseline_plot_config,
)


def test_load_raw_baseline_plot_config(tmp_path: Path) -> None:
    config_path = tmp_path / "figures.yaml"
    config_path.write_text(
        f"""
inputs:
  raw_baseline_artifact_dir: {tmp_path / "artifacts"}
outputs:
  raw_baseline_figure_dir: {tmp_path / "figures"}
raw_baseline:
  horizon_order: [1d, close]
  aggregation_mode: equal_contract
  figure_formats: [png, svg]
  dpi: 120
""",
        encoding="utf-8",
    )

    config = load_raw_baseline_plot_config(config_path)

    assert config.artifact_dir == tmp_path / "artifacts"
    assert config.figure_dir == tmp_path / "figures"
    assert config.horizon_order == ("1d", "close")
    assert config.figure_formats == ("png", "svg")
    assert config.dpi == 120
    assert config.config_sha256


def test_build_raw_baseline_plots_writes_matplotlib_files(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts"
    figure_dir = tmp_path / "figures"
    artifact_dir.mkdir()
    _write_metric_artifacts(artifact_dir)

    summary = build_raw_baseline_plots(
        RawBaselinePlotConfig(
            artifact_dir=artifact_dir,
            figure_dir=figure_dir,
            horizon_order=("1d", "close"),
            figure_formats=("png", "svg"),
            dpi=120,
        )
    )

    assert set(summary.figure_paths) == {
        "metric_overview",
        "horizon_metrics",
        "calibration_by_horizon",
        "reliability_overall",
        "reliability_by_horizon",
    }
    for paths in summary.figure_paths.values():
        suffixes = {Path(path).suffix for path in paths}
        assert suffixes == {".png", ".svg"}
        for path in paths:
            figure_path = Path(path)
            assert figure_path.exists()
            if figure_path.suffix == ".png":
                assert figure_path.read_bytes().startswith(b"\x89PNG")
            else:
                text = figure_path.read_text(encoding="utf-8")
                assert "<svg" in text
                assert "</svg>" in text
    assert (figure_dir / "raw_baseline_plot_summary.json").exists()


def _write_metric_artifacts(artifact_dir: Path) -> None:
    pq.write_table(_metrics_table(), artifact_dir / "metrics_by_group.parquet")
    pq.write_table(_reliability_table(), artifact_dir / "reliability_bins.parquet")
    pq.write_table(_calibration_table(), artifact_dir / "calibration_fits.parquet")


def _metrics_table() -> pa.Table:
    return pa.table(
        {
            "aggregation_mode": ["equal_contract", "equal_contract", "equal_contract"],
            "grouping_name": ["overall", "horizon", "horizon"],
            "group_key": ["overall", "1d", "close"],
            "horizon_name": [None, "1d", "close"],
            "domain": [None, None, None],
            "category": [None, None, None],
            "liquidity_bucket": [None, None, None],
            "staleness_bucket": [None, None, None],
            "row_count": [4.0, 2.0, 2.0],
            "contract_count": [4, 2, 2],
            "event_family_count": [2, 1, 1],
            "total_weight": [None, None, None],
            "brier_score": [0.10, 0.12, 0.08],
            "log_loss": [0.30, 0.34, 0.26],
            "expected_calibration_error": [0.05, 0.06, 0.04],
        }
    )


def _reliability_table() -> pa.Table:
    rows = []
    for grouping, horizon in (("overall", None), ("horizon", "1d"), ("horizon", "close")):
        for index in range(2):
            rows.append(
                {
                    "aggregation_mode": "equal_contract",
                    "grouping_name": grouping,
                    "group_key": "overall" if horizon is None else horizon,
                    "horizon_name": horizon,
                    "domain": None,
                    "category": None,
                    "liquidity_bucket": None,
                    "staleness_bucket": None,
                    "bin_index": index,
                    "bin_lower": index / 2,
                    "bin_upper": (index + 1) / 2,
                    "row_count": 2,
                    "mean_predicted_probability": 0.25 + index * 0.5,
                    "observed_frequency": 0.20 + index * 0.55,
                    "absolute_calibration_gap": 0.05,
                    "is_empty": False,
                    "is_sparse": False,
                    "total_row_count": 4.0,
                    "ece_contribution": 0.025,
                }
            )
    return pa.Table.from_pylist(rows)


def _calibration_table() -> pa.Table:
    return pa.table(
        {
            "aggregation_mode": ["equal_contract", "equal_contract", "equal_contract"],
            "grouping_name": ["overall", "horizon", "horizon"],
            "group_key": ["overall", "1d", "close"],
            "horizon_name": [None, "1d", "close"],
            "domain": [None, None, None],
            "category": [None, None, None],
            "liquidity_bucket": [None, None, None],
            "staleness_bucket": [None, None, None],
            "row_count": [4, 2, 2],
            "intercept": [0.0, -0.1, 0.1],
            "slope": [1.0, 0.9, 1.1],
            "iterations": [3, 3, 3],
            "converged": [True, True, True],
            "status": ["converged", "converged", "converged"],
        }
    )
