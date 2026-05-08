import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from predmkt.plots.manuscript import make_manuscript_figures
from predmkt.reports.manuscript import load_reporting_config, make_manuscript_tables


def test_reporting_config_loads(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)

    config = load_reporting_config(config_path)

    assert config.walkforward_artifact_dir == tmp_path / "walkforward"
    assert config.edge_artifact_dir == tmp_path / "edge"
    assert config.inference_artifact_dir == tmp_path / "inference"
    assert config.decomposition_artifact_dir == tmp_path / "decomposition"
    assert config.figure_dir == tmp_path / "figures"
    assert config.table_dir == tmp_path / "tables"
    assert config.artifact_run_label == "full"
    assert config.figure_formats == ("png",)
    assert config.table_formats == ("csv", "markdown", "latex")
    assert config.config_sha256


def test_make_manuscript_figures_writes_outputs(tmp_path: Path) -> None:
    _write_artifacts(tmp_path)
    config = load_reporting_config(_write_config(tmp_path))

    summary = make_manuscript_figures(config)

    assert set(summary.figure_paths) == {
        "reliability_overall",
        "reliability_by_horizon_model",
        "calibration_slope_heatmap",
        "score_comparison",
        "edge_friction_sensitivity",
        "edge_simulated_pnl",
    }
    assert (tmp_path / "figures" / "figure_manifest.json").exists()
    for paths in summary.figure_paths.values():
        assert len(paths) == 1
        path = Path(paths[0])
        assert path.exists()
        assert path.read_bytes().startswith(b"\x89PNG")


def test_make_manuscript_tables_writes_outputs(tmp_path: Path) -> None:
    _write_artifacts(tmp_path)
    config = load_reporting_config(_write_config(tmp_path))

    summary = make_manuscript_tables(config)

    assert set(summary.table_paths) == {
        "overall_score_comparison",
        "horizon_score_comparison",
        "calibration_intercept_slope",
        "edge_friction_sensitivity",
        "edge_executability_audit",
        "edge_fee_schedule_audit",
        "edge_capacity_summary",
        "edge_simulated_pnl_summary",
        "murphy_decomposition",
        "artifact_source_limitations",
    }
    assert (tmp_path / "tables" / "table_manifest.json").exists()
    for paths in summary.table_paths.values():
        suffixes = {Path(path).suffix for path in paths}
        assert suffixes == {".csv", ".md", ".tex"}
        for path in paths:
            assert Path(path).exists()
    overall = pd.read_csv(tmp_path / "tables" / "overall_score_comparison.csv")
    assert "brier_delta_vs_raw" in overall.columns
    assert "brier_delta_ci_lower" in overall.columns
    assert "brier_delta_p_value" in overall.columns
    assert "brier_delta_q_value" in overall.columns
    assert "effective_cluster_count" in overall.columns
    assert overall.loc[overall["model_name"] == "raw", "brier_delta_vs_raw"].iloc[0] == 0.0
    calibration = pd.read_csv(tmp_path / "tables" / "calibration_intercept_slope.csv")
    assert "calibration_slope_ci_lower" in calibration.columns
    assert "calibration_slope_p_value" in calibration.columns
    decomposition = pd.read_csv(tmp_path / "tables" / "murphy_decomposition.csv")
    assert {"reliability", "resolution", "uncertainty", "binning_residual"} <= set(
        decomposition.columns
    )
    executability = pd.read_csv(tmp_path / "tables" / "edge_executability_audit.csv")
    assert "quote_depth_available" in executability.columns


def test_manuscript_scripts_support_overrides(tmp_path: Path) -> None:
    _write_artifacts(tmp_path)
    config_path = _write_config(tmp_path)
    repo = Path(__file__).resolve().parents[1]

    figure_result = subprocess.run(
        [
            sys.executable,
            "scripts/make_figures.py",
            "--config",
            str(config_path),
            "--figure-dir",
            str(tmp_path / "figures_override"),
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    table_result = subprocess.run(
        [
            sys.executable,
            "scripts/make_tables.py",
            "--config",
            str(config_path),
            "--table-dir",
            str(tmp_path / "tables_override"),
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "figure_paths" in figure_result.stdout
    assert "table_paths" in table_result.stdout
    assert (tmp_path / "figures_override" / "figure_manifest.json").exists()
    assert (tmp_path / "tables_override" / "table_manifest.json").exists()


def test_scripts_fail_clearly_when_full_artifacts_missing(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    repo = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "scripts/make_tables.py",
            "--config",
            str(config_path),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Run the full Phase 7 walk-forward evaluation, Phase 8 edge simulation" in (
        result.stderr
    )


def test_reporting_code_does_not_import_calibrators() -> None:
    repo = Path(__file__).resolve().parents[1]
    for path in (
        repo / "src" / "predmkt" / "plots" / "manuscript.py",
        repo / "src" / "predmkt" / "reports" / "manuscript.py",
    ):
        text = path.read_text(encoding="utf-8")
        assert "predmkt.calibration" not in text
        assert "make_calibrator" not in text


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "reporting.yaml"
    config_path.write_text(
        f"""
inputs:
  raw_baseline_artifact_dir: {tmp_path / "raw_baseline"}
  walkforward_artifact_dir: {tmp_path / "walkforward"}
  edge_artifact_dir: {tmp_path / "edge"}
  inference_artifact_dir: {tmp_path / "inference"}
  decomposition_artifact_dir: {tmp_path / "decomposition"}
outputs:
  figure_dir: {tmp_path / "figures"}
  table_dir: {tmp_path / "tables"}
reporting:
  artifact_run_label: full
  horizon_order: [1d, close]
  model_order: [raw, platt]
  metric_scope: pooled_equal_contract
  aggregation_mode: equal_contract
  reliability_bin_count: 5
  reliability_min_bin_count: 1
  figure_formats: [png]
  dpi: 100
  table_formats: [csv, markdown, latex]
""",
        encoding="utf-8",
    )
    return config_path


def _write_artifacts(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw_baseline"
    walk_dir = tmp_path / "walkforward"
    edge_dir = tmp_path / "edge"
    inference_dir = tmp_path / "inference"
    decomposition_dir = tmp_path / "decomposition"
    raw_dir.mkdir()
    walk_dir.mkdir()
    edge_dir.mkdir()
    inference_dir.mkdir()
    decomposition_dir.mkdir()
    (raw_dir / "summary.json").write_text(
        json.dumps({"limitations": ["raw limitation"]}),
        encoding="utf-8",
    )
    (walk_dir / "summary.json").write_text(
        json.dumps({"limitations": ["walk limitation"]}),
        encoding="utf-8",
    )
    (edge_dir / "summary.json").write_text(
        json.dumps({"limitations": ["edge limitation"]}),
        encoding="utf-8",
    )
    _raw_reliability().to_parquet(raw_dir / "reliability_bins.parquet", index=False)
    _aggregate_metrics().to_parquet(walk_dir / "aggregate_metrics.parquet", index=False)
    _fold_metrics().to_parquet(walk_dir / "fold_metrics.parquet", index=False)
    _predictions().to_parquet(walk_dir / "predictions.parquet", index=False)
    _edge_summary_by_tier().to_parquet(edge_dir / "edge_summary_by_tier.parquet", index=False)
    _edge_summary_by_model_tier().to_parquet(
        edge_dir / "edge_summary_by_model_tier.parquet",
        index=False,
    )
    _edge_summary_by_side_model_tier().to_parquet(
        edge_dir / "edge_summary_by_side_model_tier.parquet",
        index=False,
    )
    _executability_audit().to_parquet(edge_dir / "executability_audit.parquet", index=False)
    _fee_schedule_audit().to_parquet(edge_dir / "fee_schedule_audit.parquet", index=False)
    _capacity_summary().to_parquet(edge_dir / "capacity_summary.parquet", index=False)
    _simulated_pnl().to_parquet(edge_dir / "simulated_pnl.parquet", index=False)
    _write_inference(inference_dir)
    _write_decomposition(decomposition_dir)


def _aggregate_metrics() -> pd.DataFrame:
    rows = []
    for model_name, overall_scores in (
        ("raw", (0.12, 0.36, 0.05, 0.1, 0.9)),
        ("platt", (0.10, 0.31, 0.03, 0.0, 1.0)),
    ):
        rows.append(_metric_row(model_name, "overall", "overall", *overall_scores))
        rows.append(
            _metric_row(
                model_name,
                "horizon",
                "1d",
                *(value + 0.01 for value in overall_scores),
            )
        )
        rows.append(
            _metric_row(
                model_name,
                "horizon",
                "close",
                *(value + 0.02 for value in overall_scores),
            )
        )
    return pd.DataFrame(rows)


def _metric_row(
    model_name: str,
    grouping_name: str,
    group_key: str,
    brier: float,
    log_loss: float,
    ece: float,
    intercept: float,
    slope: float,
) -> dict[str, object]:
    return {
        "fold_id": None,
        "model_name": model_name,
        "metric_scope": "pooled_equal_contract",
        "grouping_name": grouping_name,
        "group_key": group_key,
        "row_count": 20,
        "brier_score": brier,
        "log_loss": log_loss,
        "expected_calibration_error": ece,
        "calibration_intercept": intercept,
        "calibration_slope": slope,
        "calibration_status": "converged",
        "fold_count": None,
    }


def _fold_metrics() -> pd.DataFrame:
    frame = _aggregate_metrics().copy()
    frame["fold_id"] = "fold_2024_01"
    frame["metric_scope"] = "fold"
    return frame


def _predictions() -> pd.DataFrame:
    rows = []
    for model_name, offset in (("raw", 0.0), ("platt", 0.03)):
        for index in range(20):
            probability = min(max(0.05 + 0.045 * index + offset, 0.01), 0.99)
            rows.append(
                {
                    "fold_id": "fold_2024_01",
                    "model_name": model_name,
                    "row_id": index,
                    "contract_id": f"C{index}",
                    "event_family_id": f"E{index // 2}",
                    "horizon_name": "1d" if index < 10 else "close",
                    "forecast_ts": pd.Timestamp("2024-01-01", tz="UTC"),
                    "resolution_ts": pd.Timestamp("2024-01-02", tz="UTC"),
                    "observed_outcome": int(index % 3 == 0),
                    "raw_probability": probability - offset,
                    "predicted_probability": probability,
                    "fit_status": "fitted",
                    "fit_row_count": 50,
                }
            )
    return pd.DataFrame(rows)


def _raw_reliability() -> pd.DataFrame:
    rows = []
    for index in range(5):
        rows.append(
            {
                "aggregation_mode": "equal_contract",
                "grouping_name": "overall",
                "group_key": "overall",
                "bin_index": index,
                "bin_lower": index / 5,
                "bin_upper": (index + 1) / 5,
                "row_count": 10,
                "mean_predicted_probability": 0.1 + index * 0.2,
                "observed_frequency": 0.08 + index * 0.2,
                "is_sparse": False,
            }
        )
    return pd.DataFrame(rows)


def _edge_summary_by_tier() -> pd.DataFrame:
    rows = []
    for tier, adjustment in (("fee_only", 0.0), ("fee_spread", -0.005)):
        rows.append(
            {
                "friction_tier": tier,
                "candidate_row_count": 40,
                "selected_row_count": 4,
                "excluded_row_count": 0,
                "selected_share": 0.10,
                "mean_net_edge": 0.01 + adjustment,
                "median_net_edge": 0.0 + adjustment,
                "selected_mean_net_edge": 0.04 + adjustment,
                "selected_mean_simulated_realized_net_per_contract": 0.02 + adjustment,
            }
        )
    return pd.DataFrame(rows)


def _edge_summary_by_model_tier() -> pd.DataFrame:
    rows = []
    for model_name in ("raw", "platt"):
        for tier, adjustment in (("fee_only", 0.0), ("fee_spread", -0.005)):
            rows.append(
                {
                    "model_name": model_name,
                    "friction_tier": tier,
                    "candidate_row_count": 20,
                    "selected_row_count": 2,
                    "excluded_row_count": 0,
                    "selected_share": 0.10,
                    "mean_net_edge": 0.01 + adjustment,
                    "median_net_edge": 0.0 + adjustment,
                    "selected_mean_net_edge": 0.04 + adjustment,
                    "selected_mean_simulated_realized_net_per_contract": 0.02 + adjustment,
                }
            )
    return pd.DataFrame(rows)


def _edge_summary_by_side_model_tier() -> pd.DataFrame:
    frame = _edge_summary_by_model_tier().copy()
    frame.insert(0, "trade_side", "YES")
    return frame


def _executability_audit() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "execution_mode": ["transaction_proxy"],
            "quote_mode_used": [False],
            "input_prediction_rows": [40],
            "rows_with_attached_quote": [0],
            "candidate_rows": [120],
            "no_side_candidate_rows": [0],
            "synthetic_no_candidate_rows": [0],
            "future_quote_candidate_rows": [0],
            "quote_depth_available": [False],
            "capacity_source": ["fixed_config_assumption_no_order_book_depth"],
            "executable_profit_evidence": [False],
            "screen_language": ["simulated_expected_value_screen"],
            "limitations": ["simulated screen without order-book depth"],
        }
    )


def _fee_schedule_audit() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fee_schedule_id": ["kalshi_proxy_default"],
            "start_date": ["1900-01-01"],
            "end_date": [None],
            "formula": ["kalshi_proxy"],
            "fee_rate": [0.07],
            "source_status": ["proxy_assumption"],
            "source_note": ["fixture fee proxy"],
            "candidate_row_count": [120],
        }
    )


def _capacity_summary() -> pd.DataFrame:
    frame = _edge_summary_by_side_model_tier()[
        [
            "trade_side",
            "model_name",
            "friction_tier",
            "candidate_row_count",
            "selected_row_count",
        ]
    ].copy()
    frame["assumed_contracts"] = 1.0
    frame["capacity_source"] = "fixed_config_assumption_no_order_book_depth"
    frame["selected_total_simulated_realized_net"] = 0.1
    frame["selected_total_effective_cost"] = 1.0
    return frame


def _simulated_pnl() -> pd.DataFrame:
    rows = []
    for model_name in ("raw", "platt"):
        for index in range(3):
            rows.append(
                {
                    "model_name": model_name,
                    "friction_tier": "fee_spread_slippage",
                    "trade_side": "YES",
                    "forecast_ts": pd.Timestamp("2024-01-01", tz="UTC")
                    + pd.Timedelta(days=index),
                    "row_id": index,
                    "simulated_realized_net_total": 0.1 - 0.02 * index,
                    "cumulative_simulated_pnl": 0.1 + 0.08 * index,
                    "pnl_label": "simulated_assumption_dependent",
                }
            )
    return pd.DataFrame(rows)


def _write_inference(inference_dir: Path) -> None:
    (inference_dir / "summary.json").write_text(
        json.dumps(
            {
                "bootstrap_unit": "event_family_id",
                "limitations": ["event-family clustered confidence intervals"],
            }
        ),
        encoding="utf-8",
    )
    _score_intervals().to_parquet(inference_dir / "score_intervals.parquet", index=False)
    _paired_differences().to_parquet(
        inference_dir / "paired_score_differences.parquet",
        index=False,
    )
    _calibration_intervals().to_parquet(
        inference_dir / "calibration_intervals.parquet",
        index=False,
    )
    _paired_differences()[
        [
            "baseline_model",
            "model_name",
            "metric_name",
            "grouping_name",
            "group_key",
            "p_value",
            "q_value",
            "reject_fdr",
        ]
    ].to_parquet(
        inference_dir / "multiple_comparison_adjustments.parquet",
        index=False,
    )


def _write_decomposition(decomposition_dir: Path) -> None:
    (decomposition_dir / "summary.json").write_text(
        json.dumps(
            {
                "limitations": [
                    "Murphy decomposition uses bins and reports binning residuals"
                ]
            }
        ),
        encoding="utf-8",
    )
    rows = []
    bin_rows = []
    for model_name in ("raw", "platt"):
        rows.append(
            {
                "model_name": model_name,
                "grouping_name": "overall",
                "group_key": "overall",
                "row_count": 20,
                "raw_brier": 0.12 if model_name == "raw" else 0.10,
                "reliability": 0.02,
                "resolution": 0.04,
                "uncertainty": 0.24,
                "decomposed_brier": 0.22,
                "binning_residual": -0.10 if model_name == "raw" else -0.12,
                "nonempty_bin_count": 5,
                "empty_bin_count": 0,
                "sparse_bin_count": 0,
                "status": "ok",
            }
        )
        for index in range(5):
            bin_rows.append(
                {
                    "model_name": model_name,
                    "grouping_name": "overall",
                    "group_key": "overall",
                    "bin_index": index,
                    "row_count": 4,
                    "mean_probability": 0.1 + index * 0.2,
                    "observed_frequency": 0.08 + index * 0.2,
                    "is_empty": False,
                    "is_sparse": False,
                }
            )
    pd.DataFrame(rows).to_parquet(
        decomposition_dir / "murphy_decomposition.parquet",
        index=False,
    )
    pd.DataFrame(bin_rows).to_parquet(decomposition_dir / "murphy_bins.parquet", index=False)


def _score_intervals() -> pd.DataFrame:
    rows = []
    for grouping_name, group_keys in (
        ("overall", ["overall"]),
        ("horizon", ["1d", "close"]),
    ):
        for group_key in group_keys:
            for model_name in ("raw", "platt"):
                for metric_name in (
                    "brier_score",
                    "log_loss",
                    "expected_calibration_error",
                ):
                    rows.append(
                        {
                            "model_name": model_name,
                            "metric_name": metric_name,
                            "grouping_name": grouping_name,
                            "group_key": group_key,
                            "estimate": 0.1,
                            "ci_lower": 0.08,
                            "ci_upper": 0.12,
                            "p_value": 0.0,
                            "row_count": 20,
                            "cluster_count": 10,
                            "effective_cluster_count": 8.5,
                            "bootstrap_iterations": 20,
                            "bootstrap_status": "ok",
                            "bootstrap_unit": "event_family_id",
                            "ci_method": "event_family_cluster_bootstrap",
                            "aggregation_mode": "equal_contract",
                        }
                    )
    return pd.DataFrame(rows)


def _paired_differences() -> pd.DataFrame:
    rows = []
    for grouping_name, group_keys in (
        ("overall", ["overall"]),
        ("horizon", ["1d", "close"]),
    ):
        for group_key in group_keys:
            for metric_name in ("brier_score", "log_loss", "expected_calibration_error"):
                rows.append(
                    {
                        "baseline_model": "raw",
                        "model_name": "platt",
                        "metric_name": metric_name,
                        "grouping_name": grouping_name,
                        "group_key": group_key,
                        "estimate_delta": -0.01,
                        "ci_lower": -0.02,
                        "ci_upper": -0.001,
                        "p_value": 0.02,
                        "row_count": 20,
                        "cluster_count": 10,
                        "effective_cluster_count": 8.5,
                        "bootstrap_iterations": 20,
                        "bootstrap_status": "ok",
                        "bootstrap_unit": "event_family_id",
                        "ci_method": "event_family_cluster_bootstrap",
                        "aggregation_mode": "equal_contract",
                        "q_value": 0.03,
                        "reject_fdr": True,
                    }
                )
    return pd.DataFrame(rows)


def _calibration_intervals() -> pd.DataFrame:
    rows = []
    for group_key in ("1d", "close"):
        for model_name in ("raw", "platt"):
            for parameter, estimate, null_value in (
                ("calibration_intercept", 0.05, 0.0),
                ("calibration_slope", 0.95, 1.0),
            ):
                rows.append(
                    {
                        "model_name": model_name,
                        "parameter": parameter,
                        "grouping_name": "horizon",
                        "group_key": group_key,
                        "estimate": estimate,
                        "null_value": null_value,
                        "ci_lower": estimate - 0.05,
                        "ci_upper": estimate + 0.05,
                        "p_value": 0.12,
                        "row_count": 20,
                        "cluster_count": 10,
                        "effective_cluster_count": 8.5,
                        "bootstrap_iterations": 20,
                        "bootstrap_status": "ok",
                        "calibration_status": "converged",
                        "bootstrap_unit": "event_family_id",
                        "ci_method": "event_family_cluster_influence_bootstrap",
                        "aggregation_mode": "equal_contract",
                    }
                )
    return pd.DataFrame(rows)
