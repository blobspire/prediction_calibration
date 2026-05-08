from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from predmkt.cleaning.kalshi import (
    KalshiInterimOutputs,
    build_interim_kalshi,
    clean_contracts,
    clean_price_observations,
)
from predmkt.io.kalshi_readers import KalshiRawPaths


def test_clean_contracts_identifies_resolved_binary_contracts() -> None:
    table = _market_table()

    result = clean_contracts(table)

    assert result.raw_rows == 5
    assert result.cleaned_rows == 1
    assert result.exclusion_counts["status_not_finalized"] == 1
    assert result.exclusion_counts["missing_result"] == 1
    assert result.exclusion_counts["invalid_result"] == 1
    assert result.exclusion_counts["duplicate_resolved_market_snapshot"] == 1
    assert result.table["contract_id"].to_pylist() == ["A"]
    assert result.table["outcome"].to_pylist() == ["yes"]
    assert result.table["close_time"].type == pa.timestamp("us", tz="UTC")
    assert result.table["resolution_ts"].type == pa.timestamp("us", tz="UTC")
    assert result.table["close_time"].to_pylist() == result.table["resolution_ts"].to_pylist()


def test_clean_price_observations_filters_invalid_and_unresolved_trades() -> None:
    table = _trade_table()

    result = clean_price_observations(table, resolved_contract_ids=pa.array(["A"]))

    assert result.raw_rows == 5
    assert result.cleaned_rows == 1
    assert result.exclusion_counts["contract_not_resolved_binary"] == 1
    assert result.exclusion_counts["missing_source_ts"] == 1
    assert result.exclusion_counts["invalid_yes_price"] == 1
    assert result.exclusion_counts["invalid_volume"] == 1
    assert result.table["contract_id"].to_pylist() == ["A"]
    assert result.table["yes_price"].to_pylist() == [0.55]
    assert result.table["source_ts"].type == pa.timestamp("us", tz="UTC")


def test_build_interim_kalshi_writes_outputs(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw" / "kalshi"
    markets_dir = raw_root / "markets"
    trades_dir = raw_root / "trades"
    markets_dir.mkdir(parents=True)
    trades_dir.mkdir(parents=True)
    pq.write_table(_market_table(), markets_dir / "markets_0_10000.parquet")
    pq.write_table(_trade_table(), trades_dir / "trades_0_10000.parquet")

    outputs = KalshiInterimOutputs.from_output_dir(tmp_path / "interim" / "kalshi")
    summary = build_interim_kalshi(
        KalshiRawPaths.from_kalshi_root(raw_root),
        outputs,
        batch_size=2,
    )

    assert outputs.contracts.exists()
    assert outputs.price_observations.exists()
    assert outputs.contract_exclusion_summary.exists()
    assert outputs.price_observation_exclusion_summary.exists()
    assert outputs.summary.exists()
    assert summary["contracts"]["cleaned_rows"] == 1
    assert summary["price_observations"]["cleaned_rows"] == 1
    assert pq.read_table(outputs.contracts).num_rows == 1
    assert pq.read_table(outputs.price_observations).num_rows == 1


def _market_table() -> pa.Table:
    return pa.table(
        {
            "ticker": ["A", "A", "B", "C", "D"],
            "event_ticker": ["E1", "E1", "E2", "E3", "E4"],
            "market_type": ["binary", "binary", "binary", "binary", "binary"],
            "title": ["A old", "A new", "B", "C", "D"],
            "yes_sub_title": ["Yes"] * 5,
            "no_sub_title": ["No"] * 5,
            "status": ["finalized", "finalized", "active", "finalized", "finalized"],
            "yes_bid": [50, 55, 40, 60, 70],
            "yes_ask": [51, 56, 41, 61, 71],
            "no_bid": [49, 44, 59, 39, 29],
            "no_ask": [50, 45, 60, 40, 30],
            "last_price": [50, 55, 40, 60, 70],
            "volume": [10, 20, 30, 40, 50],
            "volume_24h": [1, 2, 3, 4, 5],
            "open_interest": [100, 200, 300, 400, 500],
            "result": ["yes", "yes", "", "", "voided"],
            "created_time": _ts_array(
                [
                    "2024-01-01T00:00:00+00:00",
                    "2024-01-01T00:00:00+00:00",
                    "2024-01-01T00:00:00+00:00",
                    "2024-01-01T00:00:00+00:00",
                    "2024-01-01T00:00:00+00:00",
                ]
            ),
            "open_time": _ts_array(
                [
                    "2024-01-01T00:00:00+00:00",
                    "2024-01-01T00:00:00+00:00",
                    "2024-01-01T00:00:00+00:00",
                    "2024-01-01T00:00:00+00:00",
                    "2024-01-01T00:00:00+00:00",
                ]
            ),
            "close_time": _ts_array(
                [
                    "2024-01-03T00:00:00+00:00",
                    "2024-01-03T00:00:00+00:00",
                    "2024-01-03T00:00:00+00:00",
                    "2024-01-03T00:00:00+00:00",
                    "2024-01-03T00:00:00+00:00",
                ]
            ),
            "_fetched_at": pa.array(
                [
                    datetime(2024, 1, 2, 0, 0, 0),
                    datetime(2024, 1, 2, 1, 0, 0),
                    datetime(2024, 1, 2, 0, 0, 0),
                    datetime(2024, 1, 2, 0, 0, 0),
                    datetime(2024, 1, 2, 0, 0, 0),
                ],
                type=pa.timestamp("us"),
            ),
        }
    )


def _trade_table() -> pa.Table:
    return pa.table(
        {
            "trade_id": ["t1", "t2", "t3", "t4", "t5"],
            "ticker": ["A", "B", "A", "A", "A"],
            "count": [10, 10, 10, 0, 10],
            "yes_price": [55, 55, 55, 55, 0],
            "no_price": [45, 45, 45, 45, 100],
            "taker_side": ["yes", "yes", "yes", "yes", "yes"],
            "created_time": pa.array(
                [
                    datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC),
                    datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC),
                    None,
                    datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC),
                    datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC),
                ],
                type=pa.timestamp("us", tz="UTC"),
            ),
            "_fetched_at": pa.array(
                [
                    datetime(2024, 1, 2, 0, 1, 0),
                    datetime(2024, 1, 2, 0, 1, 0),
                    datetime(2024, 1, 2, 0, 1, 0),
                    datetime(2024, 1, 2, 0, 1, 0),
                    datetime(2024, 1, 2, 0, 1, 0),
                ],
                type=pa.timestamp("us"),
            ),
        }
    )


def _ts_array(values: list[str]) -> pa.Array:
    return pa.array(
        [datetime.fromisoformat(value) for value in values],
        type=pa.timestamp("us", tz="UTC"),
    )
