from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from predmkt.features.kalshi import (
    FeatureBuildConfig,
    FeatureValidationError,
    build_feature_panel,
    load_feature_config,
    validate_feature_panel,
)


def test_load_feature_config(tmp_path: Path) -> None:
    config_path = tmp_path / "features.yaml"
    config_path.write_text(
        """
inputs:
  panel_path: data/processed/contract_horizon_panel_taxonomy.parquet
  price_observations_path: data/interim/kalshi/price_observations.parquet
  contracts_path: data/interim/kalshi/contracts.parquet
outputs:
  panel_path: data/processed/modeling_panel.parquet
  summary_path: data/processed/modeling_panel_summary.json
features:
  probability_epsilon: 0.000001
  momentum_window: 24h
  volatility_window: 24h
  liquidity_window: 7d
  event_family_source: taxonomy_event_family_id
  domain_category_source: taxonomy_fields
  missing_domain_category_policy: keep_unknown_with_flags
  limit_rows:
""",
        encoding="utf-8",
    )

    config = load_feature_config(config_path)

    assert config.probability_epsilon == 0.000001
    assert config.momentum_window.total_seconds() == 86_400
    assert config.volatility_window.total_seconds() == 86_400
    assert config.liquidity_window.days == 7
    assert config.config_sha256


def test_build_feature_panel_uses_only_pre_forecast_observations(tmp_path: Path) -> None:
    panel_path, prices_path, contracts_path = _write_inputs(tmp_path)
    output = tmp_path / "features.parquet"
    summary_path = tmp_path / "summary.json"

    summary = build_feature_panel(
        FeatureBuildConfig(
            panel_path=panel_path,
            price_observations_path=prices_path,
            contracts_path=contracts_path,
            output_path=output,
            summary_path=summary_path,
            probability_epsilon=0.001,
            momentum_window=_hours(24),
            volatility_window=_hours(24),
            liquidity_window=_hours(48),
            event_family_source="taxonomy_event_family_id",
            domain_category_source="taxonomy_fields",
            missing_domain_category_policy="keep_unknown_with_flags",
        )
    )

    table = pq.read_table(output)
    validate_feature_panel(table)
    row = table.to_pylist()[0]
    assert summary.input_row_count == 1
    assert summary.output_row_count == 1
    assert row["raw_probability"] == 0.9995
    assert row["clipped_probability"] == pytest.approx(0.999)
    assert row["logit_probability"] == pytest.approx(6.906754778648553)
    assert row["horizon_name"] == "1d"
    assert row["horizon_timedelta"] == 86_400
    assert row["close_time"] == datetime(2024, 1, 10, tzinfo=UTC)
    assert row["forecast_month"] == "2024-01"
    assert row["listing_month"] == "2023-12"
    assert row["price_staleness_seconds"] == 0

    assert row["cumulative_trade_count_to_forecast"] == 3
    assert row["cumulative_volume_to_forecast"] == 60
    assert row["liquidity_window_trade_count"] == 3
    assert row["liquidity_window_volume"] == 60
    assert row["public_liquidity_proxy"] == pytest.approx(4.110873864173311)

    assert row["short_run_momentum"] == pytest.approx(0.50)
    assert row["short_run_volatility"] == pytest.approx(0.3535533905932738)
    assert row["max_feature_source_ts"] == datetime(2024, 1, 9, tzinfo=UTC)
    assert row["max_feature_source_ts"] <= row["forecast_ts"]
    assert row["price_timestamp"] <= row["forecast_ts"]

    assert row["domain_missing_or_unknown"] is True
    assert row["category_missing_or_unknown"] is True
    assert row["event_family_id_inferred"] is True
    assert row["event_family_id_missing"] is False
    assert row["listing_ts_missing"] is False
    assert row["momentum_missing"] is False
    assert row["volatility_missing"] is False
    assert row["liquidity_missing"] is False
    assert summary.no_lookahead_validation["passed"] is True
    assert summary.duplicate_key_validation == {"duplicate_rows": 0, "passed": True}


def test_feature_windows_control_momentum_and_volatility(tmp_path: Path) -> None:
    panel_path, prices_path, contracts_path = _write_inputs(tmp_path)
    output = tmp_path / "features.parquet"
    summary_path = tmp_path / "summary.json"

    build_feature_panel(
        FeatureBuildConfig(
            panel_path=panel_path,
            price_observations_path=prices_path,
            contracts_path=contracts_path,
            output_path=output,
            summary_path=summary_path,
            probability_epsilon=0.001,
            momentum_window=_hours(6),
            volatility_window=_hours(6),
            liquidity_window=_hours(6),
            event_family_source="taxonomy_event_family_id",
            domain_category_source="taxonomy_fields",
            missing_domain_category_policy="keep_unknown_with_flags",
        )
    )

    row = pq.read_table(output).to_pylist()[0]
    assert row["short_run_momentum"] is None
    assert row["short_run_volatility"] is None
    assert row["liquidity_window_trade_count"] == 1
    assert row["liquidity_window_volume"] == 30
    assert row["momentum_missing"] is True
    assert row["volatility_missing"] is True


def test_validate_feature_panel_rejects_future_feature_source() -> None:
    table = _feature_validation_table(
        max_feature_source_ts=datetime(2024, 1, 9, 1, tzinfo=UTC),
    )

    with pytest.raises(FeatureValidationError, match="max_feature_source_ts"):
        validate_feature_panel(table)


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    panel_path = tmp_path / "panel.parquet"
    prices_path = tmp_path / "prices.parquet"
    contracts_path = tmp_path / "contracts.parquet"
    pq.write_table(_panel_table(), panel_path)
    pq.write_table(_prices_table(), prices_path)
    pq.write_table(_contracts_table(), contracts_path)
    return panel_path, prices_path, contracts_path


def _panel_table() -> pa.Table:
    return pa.table(
        {
            "contract_id": ["C1"],
            "event_id": ["E1"],
            "outcome": ["yes"],
            "observed_outcome": [1],
            "horizon_bucket": ["1d"],
            "horizon_timedelta_seconds": [86_400],
            "forecast_ts": _ts_array([datetime(2024, 1, 9, tzinfo=UTC)]),
            "close_time": _ts_array([datetime(2024, 1, 10, tzinfo=UTC)]),
            "resolution_ts": _ts_array([datetime(2024, 1, 10, tzinfo=UTC)]),
            "snapshot_price": [0.9995],
            "snapshot_method": ["last_trade"],
            "price_timestamp": _ts_array([datetime(2024, 1, 9, tzinfo=UTC)]),
            "staleness_seconds": [0],
            "domain": ["unknown"],
            "category": ["unknown"],
            "event_family_id": ["E1"],
            "taxonomy_source": ["event_id_proxy"],
            "taxonomy_confidence": ["low"],
            "taxonomy_notes": ["event_family_id defaults to event_id"],
        }
    )


def _prices_table() -> pa.Table:
    return pa.table(
        {
            "trade_id": ["old", "window_start", "at_forecast", "future"],
            "contract_id": ["C1", "C1", "C1", "C1"],
            "source_ts": _ts_array(
                [
                    datetime(2024, 1, 7, 12, tzinfo=UTC),
                    datetime(2024, 1, 8, 12, tzinfo=UTC),
                    datetime(2024, 1, 9, tzinfo=UTC),
                    datetime(2024, 1, 9, 1, tzinfo=UTC),
                ]
            ),
            "yes_price_cents": [10, 40, 90, 1],
            "no_price_cents": [90, 60, 10, 99],
            "yes_price": [0.10, 0.40, 0.90, 0.01],
            "no_price": [0.90, 0.60, 0.10, 0.99],
            "volume": [10, 20, 30, 10_000],
            "taker_side": ["yes", "yes", "yes", "no"],
        }
    )


def _contracts_table() -> pa.Table:
    return pa.table(
        {
            "contract_id": ["C1"],
            "created_ts": _ts_array([datetime(2023, 12, 1, tzinfo=UTC)]),
            "open_ts": _ts_array([datetime(2023, 12, 15, tzinfo=UTC)]),
            "volume": [100],
            "open_interest": [50],
        }
    )


def _feature_validation_table(*, max_feature_source_ts: datetime) -> pa.Table:
    table = _panel_table().append_column("raw_probability", pa.array([0.5], pa.float64()))
    table = table.append_column("clipped_probability", pa.array([0.5], pa.float64()))
    table = table.append_column("logit_probability", pa.array([0.0], pa.float64()))
    table = table.append_column("horizon_name", pa.array(["1d"], pa.string()))
    table = table.append_column("horizon_timedelta", pa.array([86_400], pa.int64()))
    table = table.append_column("forecast_month", pa.array(["2024-01"], pa.string()))
    table = table.append_column("price_staleness_seconds", pa.array([0], pa.int64()))
    table = table.append_column("cumulative_volume_to_forecast", pa.array([1], pa.int64()))
    table = table.append_column("cumulative_trade_count_to_forecast", pa.array([1], pa.int64()))
    table = table.append_column("short_run_momentum", pa.array([0.0], pa.float64()))
    table = table.append_column("short_run_volatility", pa.array([0.0], pa.float64()))
    table = table.append_column("public_liquidity_proxy", pa.array([0.0], pa.float64()))
    table = table.append_column("max_feature_source_ts", _ts_array([max_feature_source_ts]))
    return table


def _ts_array(values: list[datetime]) -> pa.Array:
    return pa.array(values, type=pa.timestamp("us", tz="UTC"))


def _hours(value: int) -> timedelta:
    return timedelta(hours=value)
