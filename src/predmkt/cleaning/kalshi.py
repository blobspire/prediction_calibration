"""Cleaning functions for Becker Kalshi raw tables."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from predmkt.io.kalshi_readers import KalshiRawPaths, read_markets, trade_scanner

UTC_TIMESTAMP = pa.timestamp("us", tz="UTC")
FETCH_TIMESTAMP = pa.timestamp("us")


@dataclass(frozen=True)
class CleanedTable:
    """A cleaned table plus exclusion counts."""

    table: pa.Table
    raw_rows: int
    exclusion_counts: dict[str, int]

    @property
    def cleaned_rows(self) -> int:
        return self.table.num_rows

    @property
    def excluded_rows(self) -> int:
        return sum(self.exclusion_counts.values())


@dataclass(frozen=True)
class KalshiInterimOutputs:
    """Output paths produced by the interim Kalshi build."""

    output_dir: Path
    contracts: Path
    price_observations: Path
    contract_exclusion_summary: Path
    price_observation_exclusion_summary: Path
    summary: Path

    @classmethod
    def from_output_dir(cls, output_dir: Path) -> KalshiInterimOutputs:
        return cls(
            output_dir=output_dir,
            contracts=output_dir / "contracts.parquet",
            price_observations=output_dir / "price_observations.parquet",
            contract_exclusion_summary=output_dir / "contract_exclusion_summary.parquet",
            price_observation_exclusion_summary=output_dir
            / "price_observation_exclusion_summary.parquet",
            summary=output_dir / "summary.json",
        )


def clean_contracts(raw_markets: pa.Table) -> CleanedTable:
    """Identify resolved binary contracts and normalize one row per contract."""

    masks = _contract_masks(raw_markets)
    eligible_mask = _and_all(
        (
            masks["has_contract_id"],
            masks["binary_market"],
            masks["finalized"],
            masks["has_resolution_ts"],
            masks["valid_result"],
        )
    )
    eligible = raw_markets.filter(eligible_mask)
    grouped = _latest_row_per_ticker(eligible)
    table = _canonical_contract_table(grouped)

    exclusion_counts = _priority_exclusion_counts(
        raw_markets.num_rows,
        (
            ("missing_contract_id", pc.invert(masks["has_contract_id"])),
            ("non_binary_market_type", pc.invert(masks["binary_market"])),
            ("status_not_finalized", pc.invert(masks["finalized"])),
            ("missing_resolution_ts", pc.invert(masks["has_resolution_ts"])),
            ("missing_result", masks["missing_result"]),
            ("invalid_result", pc.invert(masks["valid_result"])),
        ),
    )
    duplicate_count = eligible.num_rows - table.num_rows
    if duplicate_count > 0:
        exclusion_counts["duplicate_resolved_market_snapshot"] = duplicate_count

    return CleanedTable(
        table=table,
        raw_rows=raw_markets.num_rows,
        exclusion_counts=exclusion_counts,
    )


def clean_price_observations(
    raw_trades: pa.Table,
    resolved_contract_ids: pa.Array | None = None,
) -> CleanedTable:
    """Normalize valid Kalshi trade observations for resolved contracts."""

    masks = _trade_masks(raw_trades, resolved_contract_ids)
    eligible_mask = _and_all(
        (
            masks["has_contract_id"],
            masks["resolved_contract"],
            masks["has_source_ts"],
            masks["valid_yes_price"],
            masks["valid_no_price"],
            masks["valid_volume"],
            masks["valid_taker_side"],
        )
    )
    eligible = raw_trades.filter(eligible_mask)
    table = _canonical_price_observation_table(eligible)

    exclusion_counts = _priority_exclusion_counts(
        raw_trades.num_rows,
        (
            ("missing_contract_id", pc.invert(masks["has_contract_id"])),
            ("contract_not_resolved_binary", pc.invert(masks["resolved_contract"])),
            ("missing_source_ts", pc.invert(masks["has_source_ts"])),
            ("invalid_yes_price", pc.invert(masks["valid_yes_price"])),
            ("invalid_no_price", pc.invert(masks["valid_no_price"])),
            ("invalid_volume", pc.invert(masks["valid_volume"])),
            ("invalid_taker_side", pc.invert(masks["valid_taker_side"])),
        ),
    )
    return CleanedTable(
        table=table,
        raw_rows=raw_trades.num_rows,
        exclusion_counts=exclusion_counts,
    )


def build_interim_kalshi(
    raw_paths: KalshiRawPaths,
    outputs: KalshiInterimOutputs,
    batch_size: int = 1_000_000,
) -> dict[str, object]:
    """Build cleaned interim Kalshi outputs from immutable raw Parquet inputs."""

    outputs.output_dir.mkdir(parents=True, exist_ok=True)

    contracts_result = clean_contracts(read_markets(raw_paths))
    pq.write_table(contracts_result.table, outputs.contracts)
    _write_exclusion_summary(
        outputs.contract_exclusion_summary,
        contracts_result.exclusion_counts,
        raw_rows=contracts_result.raw_rows,
        cleaned_rows=contracts_result.cleaned_rows,
    )

    resolved_contract_ids = contracts_result.table["contract_id"].combine_chunks()
    price_exclusions: dict[str, int] = {}
    raw_trade_rows = 0
    cleaned_trade_rows = 0
    writer: pq.ParquetWriter | None = None
    try:
        for batch in trade_scanner(raw_paths, batch_size=batch_size).to_batches():
            result = clean_price_observations(pa.Table.from_batches([batch]), resolved_contract_ids)
            raw_trade_rows += result.raw_rows
            cleaned_trade_rows += result.cleaned_rows
            _merge_counts(price_exclusions, result.exclusion_counts)
            if writer is None:
                writer = pq.ParquetWriter(outputs.price_observations, result.table.schema)
            if result.table.num_rows:
                writer.write_table(result.table)
    finally:
        if writer is not None:
            writer.close()

    if writer is None:
        pq.write_table(_empty_price_observation_table(), outputs.price_observations)

    _write_exclusion_summary(
        outputs.price_observation_exclusion_summary,
        price_exclusions,
        raw_rows=raw_trade_rows,
        cleaned_rows=cleaned_trade_rows,
    )

    summary = {
        "raw": {
            "markets_dir": str(raw_paths.markets_dir),
            "trades_dir": str(raw_paths.trades_dir),
        },
        "outputs": {
            key: str(value) for key, value in asdict(outputs).items() if key != "output_dir"
        },
        "contracts": {
            "raw_rows": contracts_result.raw_rows,
            "cleaned_rows": contracts_result.cleaned_rows,
            "excluded_rows": contracts_result.excluded_rows,
            "exclusion_counts": contracts_result.exclusion_counts,
        },
        "price_observations": {
            "raw_rows": raw_trade_rows,
            "cleaned_rows": cleaned_trade_rows,
            "excluded_rows": sum(price_exclusions.values()),
            "exclusion_counts": price_exclusions,
        },
        "assumptions": {
            "contract_filter": (
                "market_type == binary; status == finalized; result in {yes,no}; "
                "close_time present"
            ),
            "price_filter": (
                "trade has resolved binary contract_id, source timestamp, prices in [1,99], "
                "positive count, taker_side in {yes,no}"
            ),
            "unit_of_analysis_note": (
                "Price observations remain trade observations only as source data for later "
                "contract-horizon snapshot construction."
            ),
        },
    }
    outputs.summary.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _contract_masks(table: pa.Table) -> dict[str, pa.Array]:
    result = table["result"]
    return {
        "has_contract_id": _non_empty_string(table["ticker"]),
        "binary_market": pc.equal(table["market_type"], "binary"),
        "finalized": pc.equal(table["status"], "finalized"),
        "has_resolution_ts": pc.invert(pc.is_null(table["close_time"])),
        "missing_result": pc.or_(pc.is_null(result), pc.equal(result, "")),
        "valid_result": pc.is_in(result, value_set=pa.array(["yes", "no"])),
    }


def _trade_masks(table: pa.Table, resolved_contract_ids: pa.Array | None) -> dict[str, pa.Array]:
    ticker = table["ticker"]
    resolved = (
        pc.is_in(ticker, value_set=resolved_contract_ids)
        if resolved_contract_ids is not None
        else _true_array(table.num_rows)
    )
    return {
        "has_contract_id": _non_empty_string(ticker),
        "resolved_contract": resolved,
        "has_source_ts": pc.invert(pc.is_null(table["created_time"])),
        "valid_yes_price": _int_between(table["yes_price"], 1, 99),
        "valid_no_price": _int_between(table["no_price"], 1, 99),
        "valid_volume": pc.greater(table["count"], 0),
        "valid_taker_side": pc.is_in(table["taker_side"], value_set=pa.array(["yes", "no"])),
    }


def _latest_row_per_ticker(table: pa.Table) -> pa.Table:
    if table.num_rows == 0:
        return table
    sorted_table = table.sort_by([("ticker", "ascending"), ("_fetched_at", "ascending")])
    aggregates = [(name, "last") for name in sorted_table.column_names if name != "ticker"]
    return sorted_table.group_by("ticker", use_threads=False).aggregate(aggregates)


def _canonical_contract_table(grouped: pa.Table) -> pa.Table:
    if grouped.num_rows == 0:
        return _empty_contract_table()
    return pa.table(
        {
            "contract_id": grouped["ticker"],
            "event_id": grouped["event_ticker_last"],
            "market_type": grouped["market_type_last"],
            "title": grouped["title_last"],
            "yes_sub_title": grouped["yes_sub_title_last"],
            "no_sub_title": grouped["no_sub_title_last"],
            "status": grouped["status_last"],
            "outcome": grouped["result_last"],
            "created_ts": _cast_timestamp(grouped["created_time_last"], UTC_TIMESTAMP),
            "open_ts": _cast_timestamp(grouped["open_time_last"], UTC_TIMESTAMP),
            "resolution_ts": _cast_timestamp(grouped["close_time_last"], UTC_TIMESTAMP),
            "source_fetched_ts": _cast_timestamp(grouped["_fetched_at_last"], FETCH_TIMESTAMP),
            "last_price_cents": grouped["last_price_last"],
            "yes_bid_cents": grouped["yes_bid_last"],
            "yes_ask_cents": grouped["yes_ask_last"],
            "no_bid_cents": grouped["no_bid_last"],
            "no_ask_cents": grouped["no_ask_last"],
            "volume": grouped["volume_last"],
            "open_interest": grouped["open_interest_last"],
        }
    )


def _canonical_price_observation_table(table: pa.Table) -> pa.Table:
    if table.num_rows == 0:
        return _empty_price_observation_table()
    yes_price_cents = table["yes_price"]
    no_price_cents = table["no_price"]
    return pa.table(
        {
            "trade_id": table["trade_id"],
            "contract_id": table["ticker"],
            "source_ts": _cast_timestamp(table["created_time"], UTC_TIMESTAMP),
            "yes_price_cents": yes_price_cents,
            "no_price_cents": no_price_cents,
            "yes_price": pc.divide(pc.cast(yes_price_cents, pa.float64()), 100.0),
            "no_price": pc.divide(pc.cast(no_price_cents, pa.float64()), 100.0),
            "volume": table["count"],
            "taker_side": table["taker_side"],
            "source_fetched_ts": _cast_timestamp(table["_fetched_at"], FETCH_TIMESTAMP),
        }
    )


def _empty_contract_table() -> pa.Table:
    return pa.table(
        {
            "contract_id": pa.array([], pa.string()),
            "event_id": pa.array([], pa.string()),
            "market_type": pa.array([], pa.string()),
            "title": pa.array([], pa.string()),
            "yes_sub_title": pa.array([], pa.string()),
            "no_sub_title": pa.array([], pa.string()),
            "status": pa.array([], pa.string()),
            "outcome": pa.array([], pa.string()),
            "created_ts": pa.array([], UTC_TIMESTAMP),
            "open_ts": pa.array([], UTC_TIMESTAMP),
            "resolution_ts": pa.array([], UTC_TIMESTAMP),
            "source_fetched_ts": pa.array([], FETCH_TIMESTAMP),
            "last_price_cents": pa.array([], pa.int64()),
            "yes_bid_cents": pa.array([], pa.int64()),
            "yes_ask_cents": pa.array([], pa.int64()),
            "no_bid_cents": pa.array([], pa.int64()),
            "no_ask_cents": pa.array([], pa.int64()),
            "volume": pa.array([], pa.int64()),
            "open_interest": pa.array([], pa.int64()),
        }
    )


def _empty_price_observation_table() -> pa.Table:
    return pa.table(
        {
            "trade_id": pa.array([], pa.string()),
            "contract_id": pa.array([], pa.string()),
            "source_ts": pa.array([], UTC_TIMESTAMP),
            "yes_price_cents": pa.array([], pa.int64()),
            "no_price_cents": pa.array([], pa.int64()),
            "yes_price": pa.array([], pa.float64()),
            "no_price": pa.array([], pa.float64()),
            "volume": pa.array([], pa.int64()),
            "taker_side": pa.array([], pa.string()),
            "source_fetched_ts": pa.array([], FETCH_TIMESTAMP),
        }
    )


def _write_exclusion_summary(
    path: Path,
    counts: dict[str, int],
    *,
    raw_rows: int,
    cleaned_rows: int,
) -> None:
    rows = [{"reason": reason, "rows": count} for reason, count in sorted(counts.items())]
    rows.append({"reason": "cleaned_rows", "rows": cleaned_rows})
    rows.append({"reason": "raw_rows", "rows": raw_rows})
    schema = pa.schema([("reason", pa.string()), ("rows", pa.int64())])
    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, path)


def _priority_exclusion_counts(
    row_count: int,
    ordered_reasons: Iterable[tuple[str, pa.Array]],
) -> dict[str, int]:
    remaining = _true_array(row_count)
    counts: dict[str, int] = {}
    for reason, mask in ordered_reasons:
        reason_mask = pc.and_(remaining, mask)
        count = _true_count(reason_mask)
        if count:
            counts[reason] = count
        remaining = pc.and_(remaining, pc.invert(reason_mask))
    return counts


def _merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for reason, count in source.items():
        target[reason] = target.get(reason, 0) + count


def _and_all(masks: Iterable[pa.Array]) -> pa.Array:
    iterator = iter(masks)
    try:
        result = next(iterator)
    except StopIteration:
        return pa.array([], pa.bool_())
    for mask in iterator:
        result = pc.and_(result, mask)
    return result


def _non_empty_string(values: pa.ChunkedArray) -> pa.Array:
    return pc.and_(pc.invert(pc.is_null(values)), pc.not_equal(values, ""))


def _int_between(values: pa.ChunkedArray, lower: int, upper: int) -> pa.Array:
    return pc.and_(pc.greater_equal(values, lower), pc.less_equal(values, upper))


def _true_array(row_count: int) -> pa.Array:
    return pa.array([True] * row_count, type=pa.bool_())


def _true_count(mask: pa.Array) -> int:
    return int(pc.sum(pc.cast(mask, pa.int64())).as_py() or 0)


def _cast_timestamp(values: pa.ChunkedArray, target_type: pa.DataType) -> pa.ChunkedArray:
    return values.cast(target_type)
