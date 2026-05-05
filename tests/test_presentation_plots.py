from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from predmkt.plots.presentation import (
    PresentationFigureConfig,
    build_presentation_figures,
    load_presentation_figure_config,
)


def test_load_presentation_figure_config(tmp_path: Path) -> None:
    config_path = tmp_path / "presentation.yaml"
    config_path.write_text(
        f"""
inputs:
  raw_baseline_artifact_dir: {tmp_path / "raw_baseline"}
  raw_baseline_audit_dir: {tmp_path / "audit"}
  snapshot_summary_path: {tmp_path / "snapshot_summary.json"}
  modeling_panel_path: {tmp_path / "modeling.parquet"}
outputs:
  presentation_figure_dir: {tmp_path / "figures"}
presentation:
  horizon_order: [1d, close]
  aggregation_mode: equal_contract
  figure_formats: [png]
  dpi: 100
""",
        encoding="utf-8",
    )

    config = load_presentation_figure_config(config_path)

    assert config.horizon_order == ("1d", "close")
    assert config.figure_formats == ("png",)
    assert config.config_sha256


def test_build_presentation_figures_writes_outputs(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "raw_baseline"
    audit_dir = tmp_path / "audit"
    figure_dir = tmp_path / "figures"
    artifact_dir.mkdir()
    audit_dir.mkdir()
    snapshot_summary_path = tmp_path / "snapshot_summary.json"
    modeling_panel_path = tmp_path / "modeling.parquet"
    _write_sources(artifact_dir, audit_dir, snapshot_summary_path, modeling_panel_path)

    summary = build_presentation_figures(
        PresentationFigureConfig(
            artifact_dir=artifact_dir,
            audit_dir=audit_dir,
            snapshot_summary_path=snapshot_summary_path,
            modeling_panel_path=modeling_panel_path,
            figure_dir=figure_dir,
            horizon_order=("1d", "close"),
            figure_formats=("png",),
            dpi=100,
        )
    )

    assert "pipeline_flow" in summary.figure_paths
    assert "dashboard" in summary.figure_paths
    assert (figure_dir / "presentation_figure_summary.json").exists()
    for paths in summary.figure_paths.values():
        for path in paths:
            assert Path(path).exists()
            assert Path(path).read_bytes().startswith(b"\x89PNG")


def _write_sources(
    artifact_dir: Path,
    audit_dir: Path,
    snapshot_summary_path: Path,
    modeling_panel_path: Path,
) -> None:
    pq.write_table(_metrics_table(), artifact_dir / "metrics_by_group.parquet")
    pq.write_table(_calibration_table(), artifact_dir / "calibration_fits.parquet")
    pq.write_table(_reliability_table(), artifact_dir / "reliability_bins.parquet")
    pq.write_table(_staleness_table(), audit_dir / "staleness_by_horizon_method.parquet")
    pq.write_table(_method_counts_table(), audit_dir / "snapshot_method_counts.parquet")
    pq.write_table(_balanced_table(), audit_dir / "balanced_horizon_metrics.parquet")
    pq.write_table(_orientation_table(), audit_dir / "orientation_sanity_by_outcome.parquet")
    pq.write_table(_close_semantics_table(), audit_dir / "close_timestamp_semantics.parquet")
    pd.DataFrame(
        {
            "horizon_name": ["1d", "1d", "close", "close"],
            "raw_probability": [0.2, 0.8, 0.05, 0.95],
        }
    ).to_parquet(modeling_panel_path, index=False)
    snapshot_summary_path.write_text(
        """
{
  "row_count": 4,
  "horizon_counts": {"1d": 2, "close": 2},
  "horizon_snapshot_policies": {
    "1d": {
      "primary_method": "last_trade",
      "vwap_window_seconds": 3600,
      "max_staleness_seconds": 86400
    },
    "close": {
      "primary_method": "last_trade",
      "vwap_window_seconds": 300,
      "max_staleness_seconds": 300
    }
  }
}
""",
        encoding="utf-8",
    )


def _metrics_table() -> pa.Table:
    return pa.Table.from_pylist(
        [
            _metric_row("1d", 2, 0.12, 0.34, 0.06),
            _metric_row("close", 2, 0.08, 0.24, 0.04),
        ]
    )


def _metric_row(
    horizon: str,
    row_count: int,
    brier: float,
    log_loss: float,
    ece: float,
) -> dict[str, object]:
    return {
        "aggregation_mode": "equal_contract",
        "grouping_name": "horizon",
        "group_key": horizon,
        "horizon_name": horizon,
        "row_count": float(row_count),
        "brier_score": brier,
        "log_loss": log_loss,
        "expected_calibration_error": ece,
    }


def _calibration_table() -> pa.Table:
    return pa.Table.from_pylist(
        [
            {
                "aggregation_mode": "equal_contract",
                "grouping_name": "horizon",
                "horizon_name": "1d",
                "intercept": -0.1,
                "slope": 0.9,
            },
            {
                "aggregation_mode": "equal_contract",
                "grouping_name": "horizon",
                "horizon_name": "close",
                "intercept": 0.1,
                "slope": 1.1,
            },
        ]
    )


def _reliability_table() -> pa.Table:
    rows = []
    for horizon in ("1d", "close"):
        for index in range(10):
            predicted = 0.05 + index / 10
            rows.append(
                {
                    "aggregation_mode": "equal_contract",
                    "grouping_name": "horizon",
                    "horizon_name": horizon,
                    "bin_index": index,
                    "bin_lower": index / 10,
                    "bin_upper": (index + 1) / 10,
                    "row_count": 10 + index,
                    "mean_predicted_probability": predicted,
                    "observed_frequency": min(max(predicted + 0.02, 0.0), 1.0),
                    "absolute_calibration_gap": 0.02,
                }
            )
    return pa.Table.from_pylist(rows)


def _staleness_table() -> pa.Table:
    return pa.Table.from_pylist(
        [
            _staleness_row("1d", 7200, 10000, 15000, 20000),
            _staleness_row("close", 60, 120, 240, 300),
        ]
    )


def _staleness_row(
    horizon: str,
    median: int,
    p75: int,
    p90: int,
    p95: int,
) -> dict[str, object]:
    return {
        "horizon_name": horizon,
        "snapshot_method": "all",
        "row_count": 2,
        "median_staleness_seconds": median,
        "p75_staleness_seconds": p75,
        "p90_staleness_seconds": p90,
        "p95_staleness_seconds": p95,
    }


def _method_counts_table() -> pa.Table:
    return pa.Table.from_pylist(
        [
            {"horizon_name": "1d", "snapshot_method": "last_trade", "row_count": 2},
            {"horizon_name": "close", "snapshot_method": "last_trade", "row_count": 2},
        ]
    )


def _balanced_table() -> pa.Table:
    rows = []
    for panel_type in ("unbalanced", "balanced"):
        for horizon in ("1d", "close"):
            rows.append(
                {
                    "horizon_name": horizon,
                    "panel_type": panel_type,
                    "brier_score": 0.1,
                    "log_loss": 0.3,
                    "expected_calibration_error": 0.05,
                }
            )
    return pa.Table.from_pylist(rows)


def _orientation_table() -> pa.Table:
    return pa.Table.from_pylist(
        [
            {
                "outcome": "yes",
                "row_count": 2,
                "bad_outcome_mapping_count": 0,
                "invalid_snapshot_price_count": 0,
            },
            {
                "outcome": "no",
                "row_count": 2,
                "bad_outcome_mapping_count": 0,
                "invalid_snapshot_price_count": 0,
            },
        ]
    )


def _close_semantics_table() -> pa.Table:
    return pa.Table.from_pylist(
        [
            {
                "snapshot_method": "last_trade",
                "median_resolution_minus_price_timestamp_seconds": 120.0,
                "p95_resolution_minus_price_timestamp_seconds": 300.0,
            }
        ]
    )
