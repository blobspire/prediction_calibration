from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from predmkt.reports.robustness import (
    RobustnessError,
    load_robustness_config,
    run_robustness,
)


def test_robustness_config_and_outputs(tmp_path: Path) -> None:
    config_path = _write_fixture(tmp_path)
    config = load_robustness_config(config_path)

    summary = run_robustness(config, run_snapshot_variants=False)

    assert summary.artifact_dir.endswith("robustness")
    assert summary.input_prediction_rows == 8
    snapshot = pd.read_parquet(tmp_path / "robustness" / "snapshot_method_slices.parquet")
    assert set(snapshot["non_confirmatory"]) == {True}
    assert set(snapshot["aggregation_mode"]) == {"equal_contract"}
    assert set(snapshot["snapshot_method"]) == {"last_trade", "vwap"}

    domain = pd.read_parquet(tmp_path / "robustness" / "domain_exclusion_status.parquet")
    assert domain["status"].tolist() == ["not_applicable"]
    assert domain["reason"].tolist() == ["domain_and_category_are_all_unknown"]

    friction = pd.read_parquet(
        tmp_path / "robustness" / "friction_assumption_sensitivity.parquet"
    )
    assert set(friction["scenario_name"]) == {"base", "strict"}
    assert (tmp_path / "robustness" / "summary.json").exists()
    assert (tmp_path / "tables" / "snapshot_method_slices.csv").exists()

    manifest = json.loads((tmp_path / "robustness" / "summary.json").read_text())
    assert manifest["effective_config"]["robustness"]["analysis_label"] == (
        "robustness_non_confirmatory"
    )


def test_liquidity_missing_column_fails_clearly(tmp_path: Path) -> None:
    config_path = _write_fixture(tmp_path, include_liquidity=False)
    config = load_robustness_config(config_path)

    with pytest.raises(RobustnessError, match="liquidity-filter diagnostics"):
        run_robustness(config, run_snapshot_variants=False)


def _write_fixture(tmp_path: Path, *, include_liquidity: bool = True) -> Path:
    panel_path = tmp_path / "panel.parquet"
    walkforward_dir = tmp_path / "walkforward"
    edge_dir = tmp_path / "edge"
    walkforward_dir.mkdir()
    edge_dir.mkdir()

    forecast = pd.date_range("2024-01-01", periods=4, tz="UTC", freq="h")
    base_panel = pd.DataFrame(
        {
            "contract_id": [f"C{i}" for i in range(4)],
            "event_family_id": [f"E{i}" for i in range(4)],
            "horizon_name": ["1h", "1h", "close", "close"],
            "forecast_ts": forecast,
            "resolution_ts": forecast + pd.Timedelta(hours=2),
            "raw_probability": [0.2, 0.4, 0.6, 0.8],
            "observed_outcome": [0, 0, 1, 1],
            "snapshot_method": ["last_trade", "vwap", "last_trade", "vwap"],
            "price_staleness_seconds": [10.0, 20.0, 30.0, 40.0],
            "cumulative_volume_to_forecast": [10.0, 200.0, 300.0, 400.0],
            "domain": ["unknown"] * 4,
            "category": ["unknown"] * 4,
        }
    )
    if include_liquidity:
        base_panel["public_liquidity_proxy"] = [1.0, 2.0, 3.0, 4.0]
    base_panel.to_parquet(panel_path, index=False)

    predictions = []
    for model in ("raw", "platt"):
        for row_id, row in base_panel.iterrows():
            predictions.append(
                {
                    "fold_id": "fold_2024_01",
                    "model_name": model,
                    "row_id": row_id,
                    "contract_id": row["contract_id"],
                    "event_family_id": row["event_family_id"],
                    "horizon_name": row["horizon_name"],
                    "forecast_ts": row["forecast_ts"],
                    "resolution_ts": row["resolution_ts"],
                    "observed_outcome": row["observed_outcome"],
                    "raw_probability": row["raw_probability"],
                    "predicted_probability": row["raw_probability"],
                }
            )
    pd.DataFrame(predictions).to_parquet(walkforward_dir / "predictions.parquet", index=False)
    (walkforward_dir / "summary.json").write_text("{}", encoding="utf-8")
    (edge_dir / "summary.json").write_text("{}", encoding="utf-8")

    backtest_path = tmp_path / "backtest.yaml"
    backtest_path.write_text(
        f"""
inputs:
  predictions_path: {walkforward_dir / "predictions.parquet"}
  panel_path: {panel_path}
outputs:
  artifact_dir: {tmp_path / "edge_base"}
columns:
  row_id_column: row_id
  entry_price_column: raw_probability
  predicted_probability_column: predicted_probability
  outcome_column: observed_outcome
  forecast_column: forecast_ts
  resolution_column: resolution_ts
  model_column: model_name
  fold_column: fold_id
  contract_column: contract_id
  horizon_column: horizon_name
  event_family_column: event_family_id
  staleness_column: price_staleness_seconds
  liquidity_column: public_liquidity_proxy
  cumulative_volume_column: cumulative_volume_to_forecast
screen:
  trade_side: yes_only
  allow_synthetic_no: false
  min_net_edge: 0.0
  limit_rows:
fee:
  formula: kalshi_proxy
  fee_rate: 0.07
capital_lockup:
  enabled: true
  annual_rate: 0.05
  day_count: 365.25
filters:
  max_staleness_seconds:
  min_liquidity_proxy:
  min_cumulative_volume:
tiers:
  - name: fee_only
    spread_cost: 0.0
    slippage_cost: 0.0
""",
        encoding="utf-8",
    )
    config_path = tmp_path / "robustness.yaml"
    config_path.write_text(
        f"""
inputs:
  panel_path: {panel_path}
  walkforward_artifact_dir: {walkforward_dir}
  edge_artifact_dir: {edge_dir}
  backtest_config_path: {backtest_path}
  sampling_config_path: configs/sampling.yaml
  contracts_path: data/interim/kalshi/contracts.parquet
  price_observations_path: data/interim/kalshi/price_observations.parquet
outputs:
  artifact_dir: {tmp_path / "robustness"}
  table_dir: {tmp_path / "tables"}
columns:
  row_id_column: row_id
  model_column: model_name
  horizon_column: horizon_name
  contract_column: contract_id
  event_family_column: event_family_id
  probability_column: predicted_probability
  outcome_column: observed_outcome
  snapshot_method_column: snapshot_method
  liquidity_column: public_liquidity_proxy
  cumulative_volume_column: cumulative_volume_to_forecast
  staleness_column: price_staleness_seconds
  domain_column: domain
  category_column: category
metrics:
  log_loss_epsilon: 0.000001
  reliability_bin_count: 5
  reliability_min_bin_count: 2
  calibration_min_rows: 2
  calibration_max_iterations: 20
  calibration_tolerance: 0.00000001
robustness:
  analysis_label: robustness_non_confirmatory
  limit_rows:
  liquidity_filters:
    - name: all_rows
      min_liquidity_proxy:
      min_cumulative_volume:
    - name: volume_ge_100
      min_liquidity_proxy:
      min_cumulative_volume: 100
  domain_exclusions:
    - name: exclude_unknown_domain
      exclude_domains: [unknown]
      exclude_categories: []
  friction_scenarios:
    - name: base
      fee_rate: 0.07
      capital_annual_rate: 0.05
      min_net_edge: 0.0
      tiers:
        - name: fee_only
          spread_cost: 0.0
          slippage_cost: 0.0
    - name: strict
      fee_rate: 0.10
      capital_annual_rate: 0.10
      min_net_edge: 0.0
      tiers:
        - name: fee_spread_slippage
          spread_cost: 0.01
          slippage_cost: 0.01
  snapshot_variants:
    enabled: false
    limit_contracts: 10
    output_dir: {tmp_path / "snapshot_variants"}
    variants:
      - name: last_trade_primary
        snapshot_methods: [last_trade, vwap]
""",
        encoding="utf-8",
    )
    return config_path
