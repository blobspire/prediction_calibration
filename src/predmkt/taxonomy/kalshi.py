"""Conservative Kalshi taxonomy enrichment for contract-horizon panels."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import yaml


@dataclass(frozen=True)
class TaxonomyRule:
    """An explicit exact-match event taxonomy rule."""

    event_id: str
    domain: str
    category: str
    event_family_id: str | None = None
    taxonomy_confidence: str = "medium"
    taxonomy_notes: str = "explicit event_id mapping"


@dataclass(frozen=True)
class TaxonomyConfig:
    """Configuration for enriching a snapshot panel with taxonomy fields."""

    panel_path: Path
    contracts_path: Path
    output_panel_path: Path
    audit_path: Path
    summary_path: Path
    default_domain: str
    default_category: str
    default_taxonomy_source: str
    default_taxonomy_confidence: str
    default_taxonomy_notes: str
    event_family_proxy: str
    title_inference: str
    explicit_event_id_mappings: tuple[TaxonomyRule, ...] = ()
    config_path: Path | None = None
    config_sha256: str | None = None


@dataclass(frozen=True)
class TaxonomyBuildSummary:
    """Summary of a taxonomy enrichment run."""

    input_panel_path: str
    contracts_path: str
    output_panel_path: str
    audit_path: str
    summary_path: str
    input_row_count: int
    output_row_count: int
    dropped_row_count: int
    taxonomy_source_counts: dict[str, int]
    domain_counts: dict[str, int]
    category_counts: dict[str, int]
    unknown_row_count: int
    ambiguous_row_count: int
    missing_event_family_id_count: int
    explicit_rule_count: int
    effective_config: dict[str, Any]
    limitations: list[str]


class TaxonomyValidationError(ValueError):
    """Raised when taxonomy enrichment violates invariants."""


REQUIRED_TAXONOMY_COLUMNS = (
    "event_id",
    "title",
    "domain",
    "category",
    "event_family_id",
    "taxonomy_source",
    "taxonomy_confidence",
    "taxonomy_notes",
)


def load_taxonomy_config(path: Path) -> TaxonomyConfig:
    """Load taxonomy configuration from YAML."""

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"taxonomy config must be a mapping: {path}")

    inputs = _mapping(raw, "inputs")
    outputs = _mapping(raw, "outputs")
    taxonomy = _mapping(raw, "taxonomy")
    rules = tuple(_parse_rule(rule) for rule in taxonomy.get("explicit_event_id_mappings", ()))

    title_inference = str(taxonomy.get("title_inference", "disabled"))
    if title_inference != "disabled":
        raise ValueError("title inference must remain disabled unless explicit code supports it")

    event_family_proxy = str(taxonomy.get("event_family_proxy", "event_id"))
    if event_family_proxy != "event_id":
        raise ValueError("only event_id is supported as the conservative event-family proxy")

    return TaxonomyConfig(
        panel_path=Path(_required(inputs, "panel_path")),
        contracts_path=Path(_required(inputs, "contracts_path")),
        output_panel_path=Path(_required(outputs, "panel_path")),
        audit_path=Path(_required(outputs, "audit_path")),
        summary_path=Path(_required(outputs, "summary_path")),
        default_domain=str(taxonomy.get("default_domain", "unknown")),
        default_category=str(taxonomy.get("default_category", "unknown")),
        default_taxonomy_source=str(taxonomy.get("default_taxonomy_source", "event_id_proxy")),
        default_taxonomy_confidence=str(taxonomy.get("default_taxonomy_confidence", "low")),
        default_taxonomy_notes=str(
            taxonomy.get(
                "default_taxonomy_notes",
                "event_family_id defaults to event_id; domain/category are unknown.",
            )
        ),
        event_family_proxy=event_family_proxy,
        title_inference=title_inference,
        explicit_event_id_mappings=rules,
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def build_taxonomy_panel(config: TaxonomyConfig) -> TaxonomyBuildSummary:
    """Enrich a snapshot panel with conservative taxonomy fields."""

    config.output_panel_path.parent.mkdir(parents=True, exist_ok=True)
    config.audit_path.parent.mkdir(parents=True, exist_ok=True)
    config.summary_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    try:
        _create_rules(con, config.explicit_event_id_mappings)
        _create_enriched_panel(con, config)
        validation = _validate_enriched_sql(con)
        con.execute(
            f"COPY enriched_panel TO {_sql_string(config.output_panel_path)} (FORMAT PARQUET)"
        )
        _create_audit(con)
        con.execute(f"COPY taxonomy_audit TO {_sql_string(config.audit_path)} (FORMAT PARQUET)")
        summary = _build_summary(con, config, validation)
    finally:
        con.close()

    config.summary_path.write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def validate_taxonomy_panel(table: pa.Table) -> None:
    """Validate taxonomy panel invariants."""

    missing = [column for column in REQUIRED_TAXONOMY_COLUMNS if column not in table.column_names]
    if missing:
        raise TaxonomyValidationError(f"taxonomy panel missing required columns: {missing}")
    if table.num_rows == 0:
        return

    event_family_ok = pc.and_(
        pc.invert(pc.is_null(table["event_family_id"])),
        pc.not_equal(table["event_family_id"], ""),
    )
    if _false_count(event_family_ok):
        raise TaxonomyValidationError("event_family_id must exist for every row")

    domain_ok = pc.and_(
        pc.invert(pc.is_null(table["domain"])),
        pc.not_equal(table["domain"], ""),
    )
    if _false_count(domain_ok):
        raise TaxonomyValidationError("domain must exist for every row")

    category_ok = pc.and_(
        pc.invert(pc.is_null(table["category"])),
        pc.not_equal(table["category"], ""),
    )
    if _false_count(category_ok):
        raise TaxonomyValidationError("category must exist for every row")


def _parse_rule(raw: object) -> TaxonomyRule:
    if not isinstance(raw, dict):
        raise ValueError("taxonomy rule must be a mapping")
    return TaxonomyRule(
        event_id=str(_required(raw, "event_id")),
        domain=str(_required(raw, "domain")),
        category=str(_required(raw, "category")),
        event_family_id=(
            str(raw["event_family_id"]) if raw.get("event_family_id") is not None else None
        ),
        taxonomy_confidence=str(raw.get("taxonomy_confidence", "medium")),
        taxonomy_notes=str(raw.get("taxonomy_notes", "explicit event_id mapping")),
    )


def _create_rules(con: duckdb.DuckDBPyConnection, rules: tuple[TaxonomyRule, ...]) -> None:
    con.execute(
        """
        CREATE TEMP TABLE taxonomy_rules(
            event_id VARCHAR,
            event_family_id VARCHAR,
            domain VARCHAR,
            category VARCHAR,
            taxonomy_confidence VARCHAR,
            taxonomy_notes VARCHAR
        )
        """
    )
    if not rules:
        return
    values = ", ".join(
        "("
        f"{_sql_string(rule.event_id)}, "
        f"{_sql_string(rule.event_family_id or '')}, "
        f"{_sql_string(rule.domain)}, "
        f"{_sql_string(rule.category)}, "
        f"{_sql_string(rule.taxonomy_confidence)}, "
        f"{_sql_string(rule.taxonomy_notes)}"
        ")"
        for rule in rules
    )
    con.execute(f"INSERT INTO taxonomy_rules VALUES {values}")


def _create_enriched_panel(con: duckdb.DuckDBPyConnection, config: TaxonomyConfig) -> None:
    con.execute(
        f"""
        CREATE TEMP TABLE enriched_panel AS
        SELECT
            p.*,
            c.title,
            c.yes_sub_title,
            c.no_sub_title,
            COALESCE(NULLIF(r.event_family_id, ''), NULLIF(p.event_id, ''), p.contract_id)
                AS event_family_id,
            COALESCE(NULLIF(r.domain, ''), {_sql_string(config.default_domain)}) AS domain,
            COALESCE(NULLIF(r.category, ''), {_sql_string(config.default_category)}) AS category,
            CASE
                WHEN r.event_id IS NOT NULL THEN 'explicit_event_id_mapping'
                ELSE {_sql_string(config.default_taxonomy_source)}
            END AS taxonomy_source,
            CASE
                WHEN r.event_id IS NOT NULL THEN r.taxonomy_confidence
                ELSE {_sql_string(config.default_taxonomy_confidence)}
            END AS taxonomy_confidence,
            CASE
                WHEN r.event_id IS NOT NULL THEN r.taxonomy_notes
                ELSE {_sql_string(config.default_taxonomy_notes)}
            END AS taxonomy_notes
        FROM read_parquet({_sql_string(config.panel_path)}) AS p
        LEFT JOIN read_parquet({_sql_string(config.contracts_path)}) AS c
          ON c.contract_id = p.contract_id
        LEFT JOIN taxonomy_rules AS r
          ON r.event_id = p.event_id
        """
    )


def _validate_enriched_sql(con: duckdb.DuckDBPyConnection) -> dict[str, int | bool]:
    input_row_count = int(con.execute("SELECT count(*) FROM enriched_panel").fetchone()[0])
    bad = con.execute(
        """
        SELECT
            sum(CASE
                WHEN event_family_id IS NULL OR event_family_id = '' THEN 1 ELSE 0
            END) AS missing_event_family_id,
            sum(CASE WHEN domain IS NULL OR domain = '' THEN 1 ELSE 0 END) AS missing_domain,
            sum(CASE WHEN category IS NULL OR category = '' THEN 1 ELSE 0 END)
                AS missing_category
        FROM enriched_panel
        """
    ).fetchone()
    counts = {
        "missing_event_family_id": int(bad[0] or 0),
        "missing_domain": int(bad[1] or 0),
        "missing_category": int(bad[2] or 0),
    }
    failing = {key: value for key, value in counts.items() if value}
    if failing:
        raise TaxonomyValidationError(f"taxonomy invariant violations: {failing}")
    counts["input_row_count"] = input_row_count
    counts["passed"] = True
    return counts


def _create_audit(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TEMP TABLE taxonomy_audit AS
        SELECT
            taxonomy_source,
            domain,
            category,
            taxonomy_confidence,
            taxonomy_notes,
            domain = 'unknown' OR category = 'unknown' AS is_unknown_group,
            taxonomy_confidence = 'ambiguous' AS is_ambiguous_group,
            count(*) AS row_count,
            count(DISTINCT contract_id) AS contract_count,
            count(DISTINCT event_family_id) AS event_family_count
        FROM enriched_panel
        GROUP BY
            taxonomy_source,
            domain,
            category,
            taxonomy_confidence,
            taxonomy_notes,
            is_unknown_group,
            is_ambiguous_group
        ORDER BY row_count DESC, taxonomy_source, domain, category
        """
    )


def _build_summary(
    con: duckdb.DuckDBPyConnection,
    config: TaxonomyConfig,
    validation: dict[str, int | bool],
) -> TaxonomyBuildSummary:
    input_count_sql = f"SELECT count(*) FROM read_parquet({_sql_string(config.panel_path)})"
    input_row_count = int(con.execute(input_count_sql).fetchone()[0])
    output_row_count = int(con.execute("SELECT count(*) FROM enriched_panel").fetchone()[0])
    taxonomy_source_counts = _count_map(con, "taxonomy_source")
    domain_counts = _count_map(con, "domain")
    category_counts = _count_map(con, "category")
    unknown_row_count = int(
        con.execute(
            """
            SELECT count(*) FROM enriched_panel
            WHERE domain = 'unknown' OR category = 'unknown'
            """
        ).fetchone()[0]
    )
    ambiguous_row_count = int(
        con.execute(
            "SELECT count(*) FROM enriched_panel WHERE taxonomy_confidence = 'ambiguous'"
        ).fetchone()[0]
    )
    return TaxonomyBuildSummary(
        input_panel_path=str(config.panel_path),
        contracts_path=str(config.contracts_path),
        output_panel_path=str(config.output_panel_path),
        audit_path=str(config.audit_path),
        summary_path=str(config.summary_path),
        input_row_count=input_row_count,
        output_row_count=output_row_count,
        dropped_row_count=input_row_count - output_row_count,
        taxonomy_source_counts=taxonomy_source_counts,
        domain_counts=domain_counts,
        category_counts=category_counts,
        unknown_row_count=unknown_row_count,
        ambiguous_row_count=ambiguous_row_count,
        missing_event_family_id_count=int(validation["missing_event_family_id"]),
        explicit_rule_count=len(config.explicit_event_id_mappings),
        effective_config=_effective_config(config),
        limitations=[
            "domain/category remain unknown unless covered by explicit event_id rules",
            (
                "event_family_id defaults to event_id and is not yet a manually "
                "validated family taxonomy"
            ),
            "title inference is disabled; titles are preserved for later audited mapping work",
        ],
    )


def _count_map(con: duckdb.DuckDBPyConnection, column: str) -> dict[str, int]:
    return {
        str(row[0]): int(row[1])
        for row in con.execute(
            f"SELECT {column}, count(*) FROM enriched_panel GROUP BY 1 ORDER BY 1"
        ).fetchall()
    }


def _effective_config(config: TaxonomyConfig) -> dict[str, Any]:
    return {
        "inputs": {
            "panel_path": str(config.panel_path),
            "contracts_path": str(config.contracts_path),
        },
        "outputs": {
            "panel_path": str(config.output_panel_path),
            "audit_path": str(config.audit_path),
            "summary_path": str(config.summary_path),
        },
        "taxonomy": {
            "default_domain": config.default_domain,
            "default_category": config.default_category,
            "default_taxonomy_source": config.default_taxonomy_source,
            "default_taxonomy_confidence": config.default_taxonomy_confidence,
            "default_taxonomy_notes": config.default_taxonomy_notes,
            "event_family_proxy": config.event_family_proxy,
            "title_inference": config.title_inference,
            "explicit_event_id_mapping_count": len(config.explicit_event_id_mappings),
        },
        "config_path": str(config.config_path) if config.config_path else None,
        "config_sha256": config.config_sha256,
    }


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"taxonomy config missing mapping: {key}")
    return value


def _required(raw: dict[str, Any], key: str) -> Any:
    if key not in raw:
        raise ValueError(f"taxonomy config missing required key: {key}")
    return raw[key]


def _sql_string(path_or_value: Path | str) -> str:
    return "'" + str(path_or_value).replace("'", "''") + "'"


def _false_count(mask: pa.ChunkedArray | pa.Array) -> int:
    inverted = pc.invert(mask)
    return int(pc.sum(pc.cast(inverted, pa.int64())).as_py() or 0)
