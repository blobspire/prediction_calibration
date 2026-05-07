import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from predmkt.edge import (
    EdgeSimulationConfig,
    EdgeSimulationError,
    FrictionTier,
    capital_lockup_cost,
    kalshi_proxy_taker_fee,
    load_edge_simulation_config,
    run_edge_simulation,
)


def test_kalshi_proxy_fee_subtracts_from_edge(tmp_path: Path) -> None:
    config = _config(tmp_path, capital_enabled=False, tiers=(FrictionTier("fee_only", 0.0, 0.0),))

    summary = run_edge_simulation(config)

    candidates = pd.read_parquet(Path(summary.artifact_paths["edge_candidates"]))
    row = candidates[candidates["row_id"] == 0].iloc[0]
    assert kalshi_proxy_taker_fee(0.5, 0.07) == pytest.approx(0.0175)
    assert row["fee_cost"] == pytest.approx(0.0175)
    assert row["gross_edge"] == pytest.approx(0.08)
    assert row["net_edge"] == pytest.approx(0.0625)


def test_thresholding_uses_net_edge(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        min_net_edge=0.05,
        capital_enabled=False,
        tiers=(FrictionTier("fee_only", 0.0, 0.0),),
    )

    summary = run_edge_simulation(config)

    candidates = pd.read_parquet(Path(summary.artifact_paths["edge_candidates"]))
    selected = candidates.sort_values("row_id")["passes_threshold"].tolist()
    assert selected == [True, False, True]


def test_negative_cost_assumptions_fail_clearly(tmp_path: Path) -> None:
    config = _config(tmp_path, tiers=(FrictionTier("bad", -0.01, 0.0),))

    with pytest.raises(EdgeSimulationError, match="spread_cost cannot be negative"):
        run_edge_simulation(config)

    with pytest.raises(ValueError, match="annual_rate cannot be negative"):
        capital_lockup_cost(0.5, 100.0, -0.01)


def test_effective_cost_is_never_negative(tmp_path: Path) -> None:
    config = _config(tmp_path)

    summary = run_edge_simulation(config)

    candidates = pd.read_parquet(Path(summary.artifact_paths["edge_candidates"]))
    assert (candidates["effective_cost"] >= 0.0).all()
    assert (candidates["cost_before_lockup"] >= candidates["entry_price"]).all()


def test_capital_lockup_increases_with_holding_time() -> None:
    assert capital_lockup_cost(0.5, 0.0, 0.05) == 0.0
    short = capital_lockup_cost(0.5, 86_400.0, 0.05)
    long = capital_lockup_cost(0.5, 10.0 * 86_400.0, 0.05)
    assert long > short > 0.0


def test_tier_ordering_is_conservative(tmp_path: Path) -> None:
    config = _config(tmp_path, capital_enabled=False)

    summary = run_edge_simulation(config)

    candidates = pd.read_parquet(Path(summary.artifact_paths["edge_candidates"]))
    pivot = candidates.pivot(index="row_id", columns="friction_tier", values="net_edge")
    assert (pivot["fee_only"] >= pivot["fee_spread"]).all()
    assert (pivot["fee_spread"] >= pivot["fee_spread_slippage"]).all()


def test_no_synthetic_no_candidates_are_generated(tmp_path: Path) -> None:
    config = _config(tmp_path)

    summary = run_edge_simulation(config)

    candidates = pd.read_parquet(Path(summary.artifact_paths["edge_candidates"]))
    assert set(candidates["trade_side"]) == {"YES"}

    with pytest.raises(EdgeSimulationError, match="synthetic NO"):
        run_edge_simulation(replace(config, allow_synthetic_no=True))


def test_filters_write_excluded_rows(tmp_path: Path) -> None:
    config = replace(_config(tmp_path), max_staleness_seconds=60.0)

    summary = run_edge_simulation(config)

    excluded = pd.read_parquet(Path(summary.artifact_paths["excluded_rows"]))
    assert summary.excluded_row_count > 0
    assert "stale_price" in set(excluded["exclusion_reason"])


def test_run_edge_sim_script_writes_expected_artifacts(tmp_path: Path) -> None:
    predictions_path, panel_path = _write_inputs(tmp_path)
    config_path = tmp_path / "backtest.yaml"
    config_path.write_text(_config_text(tmp_path, predictions_path, panel_path), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_edge_sim.py",
            "--config",
            str(config_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(result.stdout)
    assert summary["candidate_row_count"] == 9
    for artifact in (
        "edge_candidates.parquet",
        "edge_summary_by_tier.parquet",
        "edge_summary_by_model_tier.parquet",
        "excluded_rows.parquet",
        "summary.json",
    ):
        assert (tmp_path / "artifacts" / artifact).exists()


def test_config_loader_reads_friction_tiers(tmp_path: Path) -> None:
    predictions_path, panel_path = _write_inputs(tmp_path)
    config_path = tmp_path / "backtest.yaml"
    config_path.write_text(_config_text(tmp_path, predictions_path, panel_path), encoding="utf-8")

    config = load_edge_simulation_config(config_path)

    assert config.trade_side == "yes_only"
    assert [tier.name for tier in config.tiers] == [
        "fee_only",
        "fee_spread",
        "fee_spread_slippage",
    ]


def _config(
    tmp_path: Path,
    *,
    min_net_edge: float = 0.02,
    capital_enabled: bool = True,
    tiers: tuple[FrictionTier, ...] = (
        FrictionTier("fee_only", 0.0, 0.0),
        FrictionTier("fee_spread", 0.005, 0.0),
        FrictionTier("fee_spread_slippage", 0.005, 0.005),
    ),
) -> EdgeSimulationConfig:
    predictions_path, panel_path = _write_inputs(tmp_path)
    return EdgeSimulationConfig(
        predictions_path=predictions_path,
        panel_path=panel_path,
        artifact_dir=tmp_path / "artifacts",
        row_id_column="row_id",
        entry_price_column="raw_probability",
        predicted_probability_column="predicted_probability",
        outcome_column="observed_outcome",
        forecast_column="forecast_ts",
        resolution_column="resolution_ts",
        model_column="model_name",
        fold_column="fold_id",
        contract_column="contract_id",
        horizon_column="horizon_name",
        event_family_column="event_family_id",
        staleness_column="price_staleness_seconds",
        liquidity_column="public_liquidity_proxy",
        cumulative_volume_column="cumulative_volume_to_forecast",
        trade_side="yes_only",
        allow_synthetic_no=False,
        min_net_edge=min_net_edge,
        fee_formula="kalshi_proxy",
        fee_rate=0.07,
        capital_lockup_enabled=capital_enabled,
        capital_annual_rate=0.05,
        capital_day_count=365.25,
        max_staleness_seconds=None,
        min_liquidity_proxy=None,
        min_cumulative_volume=None,
        tiers=tiers,
    )


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    predictions_path = tmp_path / "predictions.parquet"
    panel_path = tmp_path / "panel.parquet"
    _predictions().to_parquet(predictions_path, index=False)
    _panel().to_parquet(panel_path, index=False)
    return predictions_path, panel_path


def _predictions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fold_id": ["fold_2024_01"] * 3,
            "model_name": ["platt"] * 3,
            "row_id": [0, 1, 2],
            "contract_id": ["C0", "C1", "C2"],
            "event_family_id": ["E0", "E1", "E2"],
            "horizon_name": ["1d", "1d", "close"],
            "forecast_ts": [
                pd.Timestamp("2024-01-01", tz="UTC"),
                pd.Timestamp("2024-01-01", tz="UTC"),
                pd.Timestamp("2024-01-01", tz="UTC"),
            ],
            "resolution_ts": [
                pd.Timestamp("2024-01-31", tz="UTC"),
                pd.Timestamp("2024-01-31", tz="UTC"),
                pd.Timestamp("2024-01-02", tz="UTC"),
            ],
            "observed_outcome": [1, 1, 0],
            "raw_probability": [0.5, 0.8, 0.4],
            "predicted_probability": [0.58, 0.82, 0.5],
        }
    )


def _panel() -> pd.DataFrame:
    panel = _predictions().drop(columns=["fold_id", "model_name", "predicted_probability"])
    panel["price_staleness_seconds"] = [30.0, 120.0, 10.0]
    panel["public_liquidity_proxy"] = [5.0, 2.0, 1.0]
    panel["cumulative_volume_to_forecast"] = [100.0, 50.0, 20.0]
    panel["snapshot_method"] = ["last_trade", "last_trade", "last_trade"]
    panel["price_timestamp"] = [
        pd.Timestamp("2024-01-01", tz="UTC"),
        pd.Timestamp("2024-01-01", tz="UTC"),
        pd.Timestamp("2024-01-01", tz="UTC"),
    ]
    panel["domain"] = ["unknown", "unknown", "unknown"]
    panel["category"] = ["unknown", "unknown", "unknown"]
    return panel


def _config_text(tmp_path: Path, predictions_path: Path, panel_path: Path) -> str:
    return f"""
inputs:
  predictions_path: {predictions_path}
  panel_path: {panel_path}
outputs:
  artifact_dir: {tmp_path / "artifacts"}
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
  min_net_edge: 0.02
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
  - name: fee_spread
    spread_cost: 0.005
    slippage_cost: 0.0
  - name: fee_spread_slippage
    spread_cost: 0.005
    slippage_cost: 0.005
"""
