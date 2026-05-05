from pathlib import Path

import pandas as pd

from predmkt.reports.raw_baseline_audit import (
    RawBaselineAuditConfig,
    balanced_horizon_metrics,
    close_timestamp_semantics,
    load_raw_baseline_audit_config,
    orientation_diagnostics,
    snapshot_method_counts,
    snapshot_method_metrics,
    staleness_diagnostics,
)


def test_load_raw_baseline_audit_config(tmp_path: Path) -> None:
    config_path = tmp_path / "audit.yaml"
    config_path.write_text(
        f"""
inputs:
  modeling_panel_path: {tmp_path / "modeling.parquet"}
  price_observations_path: {tmp_path / "prices.parquet"}
  contracts_path: {tmp_path / "contracts.parquet"}
  raw_baseline_artifact_dir: {tmp_path / "raw_baseline"}
outputs:
  audit_dir: {tmp_path / "audit"}
audit:
  horizons: [1h, close]
  close_and_near_horizons: [1h, close]
  staleness_thresholds_seconds: [300, 900]
  strict_vwap_windows_seconds: [300]
  strict_max_staleness_seconds: [300, 900]
  log_loss_epsilon: 0.001
  reliability_bin_count: 5
  calibration_min_rows: 2
  calibration_max_iterations: 10
  calibration_tolerance: 0.000001
  figure_formats: [png]
  figure_dpi: 100
  close_stale_flag_threshold_seconds: 900
""",
        encoding="utf-8",
    )

    config = load_raw_baseline_audit_config(config_path)

    assert config.horizons == ("1h", "close")
    assert config.staleness_thresholds_seconds == (300, 900)
    assert config.log_loss_epsilon == 0.001
    assert config.config_sha256


def test_staleness_and_method_diagnostics() -> None:
    panel = _panel()
    config = _config()

    staleness = staleness_diagnostics(panel, config)
    counts = snapshot_method_counts(panel, config)
    metrics = snapshot_method_metrics(panel, config)

    close_all = staleness[
        (staleness["horizon_name"] == "close") & (staleness["snapshot_method"] == "all")
    ].iloc[0]
    assert close_all["row_count"] == 2
    assert close_all["median_staleness_seconds"] == 600
    assert close_all["share_staleness_gt_300s"] == 0.5

    close_counts = counts[counts["horizon_name"] == "close"]
    assert set(close_counts["snapshot_method"]) == {"last_trade", "vwap"}
    assert close_counts["share_of_horizon"].sum() == 1.0

    metric_row = metrics[
        (metrics["horizon_name"] == "1h") & (metrics["snapshot_method"] == "vwap")
    ].iloc[0]
    assert metric_row["row_count"] == 2
    assert metric_row["brier_score"] >= 0
    assert metric_row["expected_calibration_error"] >= 0


def test_balanced_panel_and_orientation_diagnostics() -> None:
    panel = _panel()
    config = _config()

    balanced = balanced_horizon_metrics(panel, config)
    orientation = orientation_diagnostics(panel)

    balanced_rows = balanced[balanced["panel_type"] == "balanced"]
    assert set(balanced_rows["horizon_name"].astype(str)) == {"1h", "close"}
    assert balanced_rows["contract_count"].max() == 2

    assert orientation["bad_outcome_mapping_count"].sum() == 0
    assert orientation["invalid_snapshot_price_count"].sum() == 0


def test_close_semantics_uses_optional_contract_timestamps(tmp_path: Path) -> None:
    panel = _panel()
    contracts_path = tmp_path / "contracts.parquet"
    pd.DataFrame(
        {
            "contract_id": ["C1", "C2"],
            "resolution_ts": [
                pd.Timestamp("2024-01-10T00:00:00Z"),
                pd.Timestamp("2024-01-10T00:00:00Z"),
            ],
            "close_time": [
                pd.Timestamp("2024-01-10T00:00:00Z"),
                pd.Timestamp("2024-01-10T00:00:00Z"),
            ],
        }
    ).to_parquet(contracts_path, index=False)
    config = _config(contracts_path=contracts_path)

    semantics = close_timestamp_semantics(panel, config)

    assert set(semantics["close_time_available"]) == {True}
    assert set(semantics["contract_resolution_ts_available"]) == {True}
    assert semantics["share_panel_resolution_matches_contract_resolution"].min() == 1.0


def _config(contracts_path: Path | None = None) -> RawBaselineAuditConfig:
    return RawBaselineAuditConfig(
        modeling_panel_path=Path("modeling.parquet"),
        price_observations_path=Path("prices.parquet"),
        contracts_path=contracts_path or Path("contracts.parquet"),
        raw_baseline_artifact_dir=Path("raw_baseline"),
        audit_dir=Path("audit"),
        horizons=("1h", "close"),
        close_and_near_horizons=("1h", "close"),
        staleness_thresholds_seconds=(300, 900),
        strict_vwap_windows_seconds=(300,),
        strict_max_staleness_seconds=(300, 900),
        log_loss_epsilon=0.001,
        reliability_bin_count=5,
        calibration_min_rows=2,
        calibration_max_iterations=10,
        calibration_tolerance=1e-6,
        figure_formats=("png",),
        figure_dpi=100,
        close_stale_flag_threshold_seconds=900,
    )


def _panel() -> pd.DataFrame:
    base_time = pd.Timestamp("2024-01-10T00:00:00Z")
    return pd.DataFrame(
        {
            "contract_id": ["C1", "C1", "C2", "C2"],
            "event_id": ["E1", "E1", "E2", "E2"],
            "event_family_id": ["E1", "E1", "E2", "E2"],
            "outcome": ["yes", "yes", "no", "no"],
            "observed_outcome": [1, 1, 0, 0],
            "horizon_name": ["1h", "close", "1h", "close"],
            "forecast_ts": [
                base_time - pd.Timedelta(hours=1),
                base_time - pd.Timedelta(minutes=1),
                base_time - pd.Timedelta(hours=1),
                base_time - pd.Timedelta(minutes=1),
            ],
            "resolution_ts": [base_time] * 4,
            "snapshot_method": ["vwap", "vwap", "vwap", "last_trade"],
            "snapshot_price": [0.8, 0.9, 0.2, 0.1],
            "raw_probability": [0.8, 0.9, 0.2, 0.1],
            "last_trade_price": [0.8, 0.9, 0.2, 0.1],
            "last_trade_ts": [
                base_time - pd.Timedelta(hours=1),
                base_time - pd.Timedelta(minutes=1),
                base_time - pd.Timedelta(hours=1),
                base_time - pd.Timedelta(minutes=16),
            ],
            "last_trade_staleness_seconds": [0, 0, 0, 900],
            "price_timestamp": [
                base_time - pd.Timedelta(hours=1),
                base_time - pd.Timedelta(minutes=1),
                base_time - pd.Timedelta(hours=1),
                base_time - pd.Timedelta(minutes=16),
            ],
            "staleness_seconds": [0, 0, 0, 1200],
            "vwap_price": [0.8, 0.9, 0.2, None],
            "vwap_trade_count": [2, 2, 2, None],
            "vwap_volume": [10, 10, 10, None],
        }
    )
