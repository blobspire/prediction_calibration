"""Readers for Becker Kalshi raw Parquet directories."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.dataset as ds

KALSHI_MARKET_COLUMNS = (
    "ticker",
    "event_ticker",
    "market_type",
    "title",
    "yes_sub_title",
    "no_sub_title",
    "status",
    "yes_bid",
    "yes_ask",
    "no_bid",
    "no_ask",
    "last_price",
    "volume",
    "volume_24h",
    "open_interest",
    "result",
    "created_time",
    "open_time",
    "close_time",
    "_fetched_at",
)

KALSHI_TRADE_COLUMNS = (
    "trade_id",
    "ticker",
    "count",
    "yes_price",
    "no_price",
    "taker_side",
    "created_time",
    "_fetched_at",
)


@dataclass(frozen=True)
class KalshiRawPaths:
    """Paths to Becker Kalshi raw tables."""

    markets_dir: Path
    trades_dir: Path

    @classmethod
    def from_kalshi_root(cls, root: Path) -> KalshiRawPaths:
        return cls(markets_dir=root / "markets", trades_dir=root / "trades")


def read_markets(paths: KalshiRawPaths) -> pa.Table:
    """Read Becker Kalshi market snapshots needed for contract cleaning."""

    return ds.dataset(str(paths.markets_dir), format="parquet").to_table(
        columns=list(KALSHI_MARKET_COLUMNS)
    )


def trade_scanner(paths: KalshiRawPaths, batch_size: int = 1_000_000) -> ds.Scanner:
    """Return a streaming scanner for Becker Kalshi trades."""

    return ds.dataset(str(paths.trades_dir), format="parquet").scanner(
        columns=list(KALSHI_TRADE_COLUMNS),
        batch_size=batch_size,
    )
