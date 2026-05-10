from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from predmkt.io.kalshi_quotes import (
    QuoteObservationConfig,
    build_quote_observations,
    load_quote_observation_config,
)


def test_quote_builder_normalizes_schema_and_exclusions(tmp_path: Path) -> None:
    markets_dir = _write_raw_markets(tmp_path)
    raw_file = next(markets_dir.glob("*.parquet"))
    before = raw_file.stat().st_mtime_ns
    config = QuoteObservationConfig(
        markets_dir=markets_dir,
        output_path=tmp_path / "interim" / "quote_observations.parquet",
        exclusion_summary_path=tmp_path / "interim" / "quote_exclusions.parquet",
        summary_path=tmp_path / "interim" / "summary.json",
        quote_source="fixture_market_snapshot",
        fetched_at_timezone="UTC",
    )

    summary = build_quote_observations(config)

    assert raw_file.stat().st_mtime_ns == before
    assert summary.raw_row_count == 4
    assert summary.output_row_count == 1
    assert summary.depth_available is False
    quotes = pd.read_parquet(config.output_path)
    assert list(quotes["contract_id"]) == ["C0"]
    assert quotes["yes_bid"].iloc[0] == 0.40
    assert quotes["yes_ask"].iloc[0] == 0.45
    assert str(quotes["quote_ts"].dt.tz) == "UTC"
    exclusions = pd.read_parquet(config.exclusion_summary_path)
    assert "yes_bid_above_ask" in set(exclusions["reason"])
    assert "invalid_yes_ask" in set(exclusions["reason"])


def test_quote_config_loader_and_script_smoke(tmp_path: Path) -> None:
    markets_dir = _write_raw_markets(tmp_path)
    config_path = tmp_path / "quotes.yaml"
    config_path.write_text(
        f"""
inputs:
  markets_dir: {markets_dir}
outputs:
  quote_observations_path: {tmp_path / "quotes.parquet"}
  exclusion_summary_path: {tmp_path / "quote_exclusions.parquet"}
  summary_path: {tmp_path / "quote_summary.json"}
quotes:
  quote_source: fixture_market_snapshot
  fetched_at_timezone: UTC
  limit_rows:
""",
        encoding="utf-8",
    )

    config = load_quote_observation_config(config_path)
    assert config.markets_dir == markets_dir
    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_quote_observations.py",
            "--config",
            str(config_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(result.stdout)
    assert summary["output_row_count"] == 1
    assert (tmp_path / "quotes.parquet").exists()
    assert (tmp_path / "quote_summary.json").exists()


def _write_raw_markets(tmp_path: Path) -> Path:
    markets_dir = tmp_path / "raw" / "markets"
    markets_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "ticker": ["C0", "C1", "C2", "C3"],
            "yes_bid": [40, 60, 10, 20],
            "yes_ask": [45, 55, 101, 25],
            "no_bid": [55, 45, 90, 80],
            "no_ask": [60, 50, 95, 70],
            "_fetched_at": [
                pd.Timestamp("2024-01-01 00:00"),
                pd.Timestamp("2024-01-01 00:01"),
                pd.Timestamp("2024-01-01 00:02"),
                pd.Timestamp("2024-01-01 00:03"),
            ],
        }
    ).to_parquet(markets_dir / "markets_0_4.parquet", index=False)
    return markets_dir
