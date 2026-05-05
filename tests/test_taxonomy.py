from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from predmkt.taxonomy.kalshi import (
    TaxonomyConfig,
    TaxonomyRule,
    build_taxonomy_panel,
    load_taxonomy_config,
    validate_taxonomy_panel,
)


def test_default_taxonomy_uses_event_id_proxy_and_unknowns(tmp_path: Path) -> None:
    panel_path = tmp_path / "panel.parquet"
    contracts_path = tmp_path / "contracts.parquet"
    output_path = tmp_path / "taxonomy.parquet"
    audit_path = tmp_path / "audit.parquet"
    summary_path = tmp_path / "summary.json"
    pq.write_table(_panel_table(), panel_path)
    pq.write_table(_contracts_table(), contracts_path)

    summary = build_taxonomy_panel(
        TaxonomyConfig(
            panel_path=panel_path,
            contracts_path=contracts_path,
            output_panel_path=output_path,
            audit_path=audit_path,
            summary_path=summary_path,
            default_domain="unknown",
            default_category="unknown",
            default_taxonomy_source="event_id_proxy",
            default_taxonomy_confidence="low",
            default_taxonomy_notes="event_family_id defaults to event_id",
            event_family_proxy="event_id",
            title_inference="disabled",
        )
    )

    enriched = pq.read_table(output_path)
    validate_taxonomy_panel(enriched)
    rows = enriched.to_pylist()
    assert summary.input_row_count == 2
    assert summary.output_row_count == 2
    assert summary.dropped_row_count == 0
    assert {row["event_id"] for row in rows} == {"EVT", None}
    assert rows[0]["event_family_id"] == "EVT"
    assert rows[1]["event_family_id"] == "C2"
    assert {row["domain"] for row in rows} == {"unknown"}
    assert {row["category"] for row in rows} == {"unknown"}
    assert {row["taxonomy_source"] for row in rows} == {"event_id_proxy"}
    assert rows[0]["title"] == "Mapped event title"

    audit = pq.read_table(audit_path)
    assert audit.num_rows == 1
    assert audit.to_pylist()[0]["row_count"] == 2
    assert audit.to_pylist()[0]["is_unknown_group"] is True


def test_explicit_event_id_mapping_overrides_defaults(tmp_path: Path) -> None:
    panel_path = tmp_path / "panel.parquet"
    contracts_path = tmp_path / "contracts.parquet"
    output_path = tmp_path / "taxonomy.parquet"
    audit_path = tmp_path / "audit.parquet"
    summary_path = tmp_path / "summary.json"
    pq.write_table(_panel_table(), panel_path)
    pq.write_table(_contracts_table(), contracts_path)

    build_taxonomy_panel(
        TaxonomyConfig(
            panel_path=panel_path,
            contracts_path=contracts_path,
            output_panel_path=output_path,
            audit_path=audit_path,
            summary_path=summary_path,
            default_domain="unknown",
            default_category="unknown",
            default_taxonomy_source="event_id_proxy",
            default_taxonomy_confidence="low",
            default_taxonomy_notes="event_family_id defaults to event_id",
            event_family_proxy="event_id",
            title_inference="disabled",
            explicit_event_id_mappings=(
                TaxonomyRule(
                    event_id="EVT",
                    event_family_id="FAM-EVT",
                    domain="economics",
                    category="inflation",
                    taxonomy_confidence="high",
                    taxonomy_notes="test exact event_id rule",
                ),
            ),
        )
    )

    rows = pq.read_table(output_path).to_pylist()
    mapped = next(row for row in rows if row["contract_id"] == "C1")
    defaulted = next(row for row in rows if row["contract_id"] == "C2")
    assert mapped["event_id"] == "EVT"
    assert mapped["event_family_id"] == "FAM-EVT"
    assert mapped["domain"] == "economics"
    assert mapped["category"] == "inflation"
    assert mapped["taxonomy_source"] == "explicit_event_id_mapping"
    assert mapped["taxonomy_confidence"] == "high"
    assert defaulted["event_family_id"] == "C2"
    assert defaulted["domain"] == "unknown"
    assert defaulted["category"] == "unknown"


def test_load_taxonomy_config(tmp_path: Path) -> None:
    config_path = tmp_path / "taxonomy.yaml"
    config_path.write_text(
        """
inputs:
  panel_path: data/processed/contract_horizon_panel.parquet
  contracts_path: data/interim/kalshi/contracts.parquet
outputs:
  panel_path: data/processed/contract_horizon_panel_taxonomy.parquet
  audit_path: data/processed/contract_horizon_taxonomy_audit.parquet
  summary_path: data/processed/contract_horizon_taxonomy_summary.json
taxonomy:
  default_domain: unknown
  default_category: unknown
  default_taxonomy_source: event_id_proxy
  default_taxonomy_confidence: low
  default_taxonomy_notes: event_family_id defaults to event_id
  event_family_proxy: event_id
  title_inference: disabled
  explicit_event_id_mappings:
    - event_id: EVT
      event_family_id: FAM-EVT
      domain: economics
      category: inflation
      taxonomy_confidence: high
      taxonomy_notes: explicit test mapping
""",
        encoding="utf-8",
    )

    config = load_taxonomy_config(config_path)

    assert config.default_domain == "unknown"
    assert config.title_inference == "disabled"
    assert len(config.explicit_event_id_mappings) == 1
    assert config.explicit_event_id_mappings[0].event_id == "EVT"
    assert config.config_sha256


def _panel_table() -> pa.Table:
    return pa.table(
        {
            "contract_id": ["C1", "C2"],
            "event_id": ["EVT", None],
            "outcome": ["yes", "no"],
            "observed_outcome": [1, 0],
            "horizon_bucket": ["1d", "1d"],
            "horizon_timedelta_seconds": [86_400, 86_400],
            "forecast_ts": _ts_array(
                [
                    datetime(2024, 1, 9, tzinfo=UTC),
                    datetime(2024, 1, 9, tzinfo=UTC),
                ]
            ),
            "resolution_ts": _ts_array(
                [
                    datetime(2024, 1, 10, tzinfo=UTC),
                    datetime(2024, 1, 10, tzinfo=UTC),
                ]
            ),
            "snapshot_price": [0.4, 0.6],
            "snapshot_method": ["last_trade", "last_trade"],
            "price_timestamp": _ts_array(
                [
                    datetime(2024, 1, 9, tzinfo=UTC),
                    datetime(2024, 1, 9, tzinfo=UTC),
                ]
            ),
            "staleness_seconds": [0, 0],
        }
    )


def _contracts_table() -> pa.Table:
    return pa.table(
        {
            "contract_id": ["C1", "C2"],
            "event_id": ["EVT", None],
            "title": ["Mapped event title", "No event title"],
            "yes_sub_title": ["Yes", "Yes"],
            "no_sub_title": ["No", "No"],
        }
    )


def _ts_array(values: list[datetime]) -> pa.Array:
    return pa.array(values, type=pa.timestamp("us", tz="UTC"))
