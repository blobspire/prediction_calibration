import json
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from predmkt.sampling.snapshots import (
    DEFAULT_HORIZON_NAMES,
    HorizonSnapshotPolicy,
    HorizonSpec,
    SnapshotBuildConfig,
    SnapshotValidationError,
    build_snapshot_panel,
    load_snapshot_config,
    parse_duration,
    parse_horizons,
    validate_snapshot_panel,
)


def test_parse_duration() -> None:
    assert parse_duration("7d").days == 7
    assert parse_duration("6h").total_seconds() == 21_600
    assert parse_duration("30m").total_seconds() == 1_800
    assert parse_duration("close").total_seconds() == 60
    with pytest.raises(ValueError):
        parse_duration("1w")


def test_default_horizon_grid_includes_initial_recommended_buckets() -> None:
    horizons = parse_horizons(DEFAULT_HORIZON_NAMES)

    assert [horizon.name for horizon in horizons] == [
        "30d",
        "14d",
        "7d",
        "3d",
        "1d",
        "6h",
        "1h",
        "close",
    ]
    assert all(horizon.duration.total_seconds() > 0 for horizon in horizons)


def test_load_snapshot_config(tmp_path: Path) -> None:
    config_path = tmp_path / "sampling.yaml"
    config_path.write_text(
        """
inputs:
  contracts_path: data/interim/kalshi/contracts.parquet
  price_observations_path: data/interim/kalshi/price_observations.parquet
outputs:
  panel_path: data/processed/contract_horizon_panel.parquet
  summary_path: data/processed/contract_horizon_panel_summary.json
sampling:
  horizons: [30d, 14d, 7d, 3d, 1d, 6h, 1h, close]
  close_horizon_definition: close = resolution_ts - 1 minute
  snapshot:
    default_method_preference: [last_trade, vwap]
    default_max_staleness: 7d
    default_vwap_window: 6h
    horizons:
      1h:
        vwap_window: 5m
        max_staleness: 1h
      close:
        method_preference: [last_trade, vwap]
        vwap_window: 5m
        max_staleness: 5m
  limit_contracts:
""",
        encoding="utf-8",
    )

    config = load_snapshot_config(config_path)

    assert [horizon.name for horizon in config.horizons] == [
        "30d",
        "14d",
        "7d",
        "3d",
        "1d",
        "6h",
        "1h",
        "close",
    ]
    assert config.max_staleness == parse_duration("7d")
    assert config.vwap_window == parse_duration("6h")
    assert config.snapshot_methods == ("last_trade", "vwap")
    assert config.horizon_policies[-2].horizon_name == "1h"
    assert config.horizon_policies[-2].vwap_window == parse_duration("5m")
    assert config.horizon_policies[-2].max_staleness == parse_duration("1h")
    assert config.horizon_policies[-1].horizon_name == "close"
    assert config.horizon_policies[-1].max_staleness == parse_duration("5m")
    assert config.config_path == config_path
    assert config.config_sha256


def test_build_snapshot_panel_prevents_lookahead_and_computes_vwap(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts.parquet"
    prices = tmp_path / "prices.parquet"
    output = tmp_path / "panel.parquet"
    summary = tmp_path / "summary.json"
    pq.write_table(_contracts_table(), contracts)
    pq.write_table(_prices_table(), prices)

    build_summary = build_snapshot_panel(
        SnapshotBuildConfig(
            contracts_path=contracts,
            price_observations_path=prices,
            output_path=output,
            summary_path=summary,
            horizons=(HorizonSpec("1d", parse_duration("1d")),),
            max_staleness=parse_duration("3d"),
            vwap_window=parse_duration("2d"),
        )
    )

    panel = pq.read_table(output)
    validate_snapshot_panel(panel)
    assert build_summary.row_count == 1
    assert build_summary.candidate_count == 1
    assert build_summary.dropped_no_price_count == 0
    assert build_summary.dropped_stale_count == 0
    assert build_summary.snapshot_method_counts == {"vwap": 1}
    assert build_summary.duplicate_key_validation == {"duplicate_rows": 0, "passed": True}
    assert build_summary.no_lookahead_validation["passed"] is True
    assert panel.num_rows == 1
    assert set(_canonical_columns()).issubset(panel.column_names)
    row = panel.to_pylist()[0]
    assert row["contract_id"] == "A"
    assert row["horizon_bucket"] == "1d"
    assert row["horizon_timedelta_seconds"] == 86_400
    assert row["forecast_ts"] == datetime(2024, 1, 9, tzinfo=UTC)
    assert row["forecast_ts"] < row["resolution_ts"]
    assert row["observed_outcome"] == 1
    assert row["last_trade_ts"] == datetime(2024, 1, 8, 12, tzinfo=UTC)
    assert row["last_trade_price"] == 0.4
    assert row["vwap_trade_count"] == 2
    assert row["vwap_volume"] == 30
    assert row["vwap_price"] == pytest.approx((0.20 * 10 + 0.40 * 20) / 30)
    assert row["snapshot_method"] == "vwap"
    assert row["price_timestamp"] == row["max_source_ts"]
    assert row["price_timestamp"] <= row["forecast_ts"]
    assert row["last_trade_ts"] <= row["forecast_ts"]
    assert row["max_source_ts"] <= row["forecast_ts"]
    assert row["staleness_seconds"] == 43_200

    summary_payload = json.loads(summary.read_text(encoding="utf-8"))
    assert summary_payload["effective_config"]["sampling"]["horizons"] == ["1d"]
    assert summary_payload["effective_config"]["sampling"]["snapshot_methods"] == [
        "vwap",
        "last_trade",
    ]


def test_horizon_specific_snapshot_policy_controls_primary_method_and_staleness(
    tmp_path: Path,
) -> None:
    contracts = tmp_path / "contracts.parquet"
    prices = tmp_path / "prices.parquet"
    output = tmp_path / "panel.parquet"
    summary = tmp_path / "summary.json"
    pq.write_table(_contracts_table(), contracts)
    pq.write_table(_policy_prices_table(), prices)

    build_summary = build_snapshot_panel(
        SnapshotBuildConfig(
            contracts_path=contracts,
            price_observations_path=prices,
            output_path=output,
            summary_path=summary,
            horizons=(
                HorizonSpec("1h", parse_duration("1h")),
                HorizonSpec("close", parse_duration("close")),
            ),
            max_staleness=parse_duration("7d"),
            vwap_window=parse_duration("6h"),
            snapshot_methods=("last_trade", "vwap"),
            horizon_policies=(
                HorizonSnapshotPolicy(
                    horizon_name="1h",
                    max_staleness=parse_duration("2h"),
                    vwap_window=parse_duration("1h"),
                    snapshot_methods=("vwap", "last_trade"),
                ),
                HorizonSnapshotPolicy(
                    horizon_name="close",
                    max_staleness=parse_duration("5m"),
                    vwap_window=parse_duration("5m"),
                    snapshot_methods=("last_trade", "vwap"),
                ),
            ),
        )
    )

    panel = pq.read_table(output)
    validate_snapshot_panel(panel)
    rows = {row["horizon_bucket"]: row for row in panel.to_pylist()}

    assert build_summary.row_count == 2
    assert rows["1h"]["snapshot_method"] == "vwap"
    assert rows["1h"]["horizon_vwap_window_seconds"] == 3_600
    assert rows["1h"]["horizon_max_staleness_seconds"] == 7_200
    assert rows["1h"]["vwap_trade_count"] == 2
    assert rows["1h"]["vwap_price"] == pytest.approx((0.20 * 10 + 0.50 * 20) / 30)
    assert rows["close"]["snapshot_method"] == "last_trade"
    assert rows["close"]["snapshot_price"] == 0.9
    assert rows["close"]["horizon_vwap_window_seconds"] == 300
    assert rows["close"]["horizon_max_staleness_seconds"] == 300
    assert rows["close"]["staleness_seconds"] == 60

    summary_payload = json.loads(summary.read_text(encoding="utf-8"))
    policies = summary_payload["horizon_snapshot_policies"]
    assert policies["close"]["primary_method"] == "last_trade"
    assert policies["1h"]["primary_method"] == "vwap"


def test_build_snapshot_panel_has_at_most_one_row_per_contract_horizon(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts.parquet"
    prices = tmp_path / "prices.parquet"
    output = tmp_path / "panel.parquet"
    summary = tmp_path / "summary.json"
    pq.write_table(_contracts_table(), contracts)
    pq.write_table(_prices_table(), prices)

    build_snapshot_panel(
        SnapshotBuildConfig(
            contracts_path=contracts,
            price_observations_path=prices,
            output_path=output,
            summary_path=summary,
            horizons=(
                HorizonSpec("1d", parse_duration("1d")),
                HorizonSpec("2d", parse_duration("2d")),
            ),
            max_staleness=parse_duration("3d"),
            vwap_window=parse_duration("2d"),
        )
    )

    panel = pq.read_table(output)
    keys = list(
        zip(panel["contract_id"].to_pylist(), panel["horizon_bucket"].to_pylist(), strict=False)
    )
    assert len(keys) == len(set(keys))
    assert set(keys) == {("A", "1d"), ("A", "2d")}


def test_stale_price_tolerance_excludes_candidate(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts.parquet"
    prices = tmp_path / "prices.parquet"
    output = tmp_path / "panel.parquet"
    summary = tmp_path / "summary.json"
    pq.write_table(_contracts_table(), contracts)
    pq.write_table(_prices_table(), prices)

    build_summary = build_snapshot_panel(
        SnapshotBuildConfig(
            contracts_path=contracts,
            price_observations_path=prices,
            output_path=output,
            summary_path=summary,
            horizons=(HorizonSpec("1d", parse_duration("1d")),),
            max_staleness=parse_duration("6h"),
            vwap_window=parse_duration("6h"),
        )
    )

    panel = pq.read_table(output)
    validate_snapshot_panel(panel)
    assert panel.num_rows == 0
    assert build_summary.candidate_count == 1
    assert build_summary.dropped_no_price_count == 0
    assert build_summary.dropped_stale_count == 1


def test_validate_snapshot_panel_rejects_future_source_timestamp() -> None:
    table = _panel_table(
        last_trade_ts=datetime(2024, 1, 9, 1, tzinfo=UTC),
        max_source_ts=datetime(2024, 1, 9, 1, tzinfo=UTC),
        price_timestamp=datetime(2024, 1, 9, 1, tzinfo=UTC),
    )

    with pytest.raises(SnapshotValidationError, match="last_trade_ts"):
        validate_snapshot_panel(table)


def test_validate_snapshot_panel_rejects_duplicate_keys() -> None:
    table = pa.concat_tables([_panel_table(), _panel_table()])

    with pytest.raises(SnapshotValidationError, match="duplicate"):
        validate_snapshot_panel(table)


def test_validate_snapshot_panel_rejects_price_timestamp_lookahead() -> None:
    table = _panel_table(
        last_trade_ts=datetime(2024, 1, 9, tzinfo=UTC),
        max_source_ts=datetime(2024, 1, 9, tzinfo=UTC),
        price_timestamp=datetime(2024, 1, 9, 1, tzinfo=UTC),
    )

    with pytest.raises(SnapshotValidationError, match="price_timestamp"):
        validate_snapshot_panel(table)


def _contracts_table() -> pa.Table:
    return pa.table(
        {
            "contract_id": ["A"],
            "event_id": ["E1"],
            "outcome": ["yes"],
            "close_time": _ts_array([datetime(2024, 1, 10, tzinfo=UTC)]),
            "resolution_ts": _ts_array([datetime(2024, 1, 10, tzinfo=UTC)]),
        }
    )


def _prices_table() -> pa.Table:
    return pa.table(
        {
            "trade_id": ["old", "last_before", "future"],
            "contract_id": ["A", "A", "A"],
            "source_ts": _ts_array(
                [
                    datetime(2024, 1, 8, tzinfo=UTC),
                    datetime(2024, 1, 8, 12, tzinfo=UTC),
                    datetime(2024, 1, 9, 12, tzinfo=UTC),
                ]
            ),
            "yes_price_cents": [20, 40, 99],
            "yes_price": [0.20, 0.40, 0.99],
            "volume": [10, 20, 1000],
        }
    )


def _policy_prices_table() -> pa.Table:
    return pa.table(
        {
            "trade_id": ["first_1h", "last_1h", "close_trade", "future"],
            "contract_id": ["A", "A", "A", "A"],
            "source_ts": _ts_array(
                [
                    datetime(2024, 1, 9, 22, 15, tzinfo=UTC),
                    datetime(2024, 1, 9, 22, 50, tzinfo=UTC),
                    datetime(2024, 1, 9, 23, 58, tzinfo=UTC),
                    datetime(2024, 1, 10, 0, 1, tzinfo=UTC),
                ]
            ),
            "yes_price_cents": [20, 50, 90, 99],
            "yes_price": [0.20, 0.50, 0.90, 0.99],
            "volume": [10, 20, 100, 1000],
        }
    )


def _ts_array(values: list[datetime]) -> pa.Array:
    return pa.array(values, type=pa.timestamp("us", tz="UTC"))


def _panel_table(
    *,
    last_trade_ts: datetime = datetime(2024, 1, 9, tzinfo=UTC),
    max_source_ts: datetime | None = datetime(2024, 1, 9, tzinfo=UTC),
    price_timestamp: datetime = datetime(2024, 1, 9, tzinfo=UTC),
) -> pa.Table:
    return pa.table(
        {
            "contract_id": ["A"],
            "event_id": ["E1"],
            "outcome": ["yes"],
            "observed_outcome": [1],
            "horizon_bucket": ["1d"],
            "horizon_timedelta_seconds": [86_400],
            "forecast_ts": _ts_array([datetime(2024, 1, 9, tzinfo=UTC)]),
            "close_time": _ts_array([datetime(2024, 1, 10, tzinfo=UTC)]),
            "resolution_ts": _ts_array([datetime(2024, 1, 10, tzinfo=UTC)]),
            "snapshot_price": [0.4],
            "snapshot_method": ["last_trade"],
            "price_timestamp": _ts_array([price_timestamp]),
            "staleness_seconds": [0],
            "last_trade_ts": _ts_array([last_trade_ts]),
            "max_source_ts": _ts_array([max_source_ts]) if max_source_ts else _ts_array([None]),
            "vwap_volume": pa.array([None], type=pa.float64()),
            "vwap_trade_count": pa.array([None], type=pa.int64()),
        }
    )


def _canonical_columns() -> tuple[str, ...]:
    return (
        "contract_id",
        "event_id",
        "outcome",
        "observed_outcome",
        "horizon_bucket",
        "horizon_timedelta_seconds",
        "forecast_ts",
        "close_time",
        "resolution_ts",
        "snapshot_price",
        "snapshot_method",
        "price_timestamp",
        "staleness_seconds",
        "last_trade_ts",
        "max_source_ts",
        "vwap_volume",
        "vwap_trade_count",
    )
