"""Conservative Kalshi taxonomy enrichment for contract-horizon panels."""

from __future__ import annotations

import hashlib
import json
import re
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
    rule_id: str | None = None
    event_family_id: str | None = None
    is_sports: bool = False
    taxonomy_confidence: str = "medium"
    taxonomy_notes: str = "explicit event_id mapping"


@dataclass(frozen=True)
class PrefixTaxonomyRule:
    """A documented ticker-prefix taxonomy rule."""

    rule_id: str
    pattern: str
    domain: str
    category: str
    is_sports: bool = False
    taxonomy_confidence: str = "medium"
    taxonomy_notes: str = "explicit prefix rule"
    priority: int = 100


@dataclass(frozen=True)
class TitleKeywordTaxonomyRule:
    """A lower-confidence explicit title-keyword taxonomy rule."""

    rule_id: str
    keywords: tuple[str, ...]
    domain: str
    category: str
    is_sports: bool = False
    taxonomy_confidence: str = "low"
    taxonomy_notes: str = "explicit title-keyword rule"
    priority: int = 1000
    pattern: str | None = None


@dataclass(frozen=True)
class EventFamilyRegexRule:
    """A regex rule that groups related contracts into audited event families."""

    rule_id: str
    pattern: str
    family_id_prefix: str
    group_index: int = 1
    source_column: str = "event_id"
    event_family_confidence: str = "medium"
    taxonomy_notes: str = "event-family regex rule"
    priority: int = 100


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
    default_is_sports: bool = False
    explicit_event_id_mappings: tuple[TaxonomyRule, ...] = ()
    prefix_rules: tuple[PrefixTaxonomyRule, ...] = ()
    title_keyword_rules: tuple[TitleKeywordTaxonomyRule, ...] = ()
    event_family_regex_rules: tuple[EventFamilyRegexRule, ...] = ()
    config_path: Path | None = None
    config_sha256: str | None = None
    examples_path: Path | None = None


@dataclass(frozen=True)
class TaxonomyBuildSummary:
    """Summary of a taxonomy enrichment run."""

    input_panel_path: str
    contracts_path: str
    output_panel_path: str
    audit_path: str
    examples_path: str
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
    prefix_rule_count: int
    title_keyword_rule_count: int
    event_family_regex_rule_count: int
    unknown_rate: float
    ambiguous_rate: float
    sports_row_count: int
    sports_rate: float
    event_family_source_counts: dict[str, int]
    taxonomy_confidence_counts: dict[str, int]
    event_family_confidence_counts: dict[str, int]
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
    "is_sports",
    "taxonomy_rule_id",
    "taxonomy_ambiguous",
    "event_family_source",
    "event_family_confidence",
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
    prefix_rules = tuple(_parse_prefix_rule(rule) for rule in taxonomy.get("prefix_rules", ()))
    title_rules = tuple(
        _parse_title_rule(rule) for rule in taxonomy.get("title_keyword_rules", ())
    )
    family_rules = tuple(
        _parse_family_rule(rule) for rule in taxonomy.get("event_family_regex_rules", ())
    )

    title_inference = str(taxonomy.get("title_inference", "disabled"))
    if title_inference not in {"disabled", "explicit_rules"}:
        raise ValueError("taxonomy.title_inference must be 'disabled' or 'explicit_rules'")
    if title_rules and title_inference != "explicit_rules":
        raise ValueError("title_keyword_rules require taxonomy.title_inference = explicit_rules")

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
        default_is_sports=bool(taxonomy.get("default_is_sports", False)),
        explicit_event_id_mappings=rules,
        prefix_rules=prefix_rules,
        title_keyword_rules=title_rules,
        event_family_regex_rules=family_rules,
        config_path=path,
        config_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        examples_path=(
            Path(outputs["examples_path"]) if outputs.get("examples_path") is not None else None
        ),
    )


def build_taxonomy_panel(config: TaxonomyConfig) -> TaxonomyBuildSummary:
    """Enrich a snapshot panel with conservative taxonomy fields."""

    config.output_panel_path.parent.mkdir(parents=True, exist_ok=True)
    config.audit_path.parent.mkdir(parents=True, exist_ok=True)
    config.summary_path.parent.mkdir(parents=True, exist_ok=True)
    examples_path = _examples_path(config)
    examples_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    try:
        _create_rules(con, config.explicit_event_id_mappings)
        _create_prefix_rules(con, config.prefix_rules)
        _create_title_rules(con, config.title_keyword_rules)
        _create_family_rules(con, config.event_family_regex_rules)
        _create_enriched_panel(con, config)
        validation = _validate_enriched_sql(con)
        con.execute(
            f"COPY enriched_panel TO {_sql_string(config.output_panel_path)} (FORMAT PARQUET)"
        )
        _create_audit(con)
        con.execute(f"COPY taxonomy_audit TO {_sql_string(config.audit_path)} (FORMAT PARQUET)")
        _create_examples(con)
        con.execute(f"COPY taxonomy_examples TO {_sql_string(examples_path)} (FORMAT PARQUET)")
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
        rule_id=str(raw.get("rule_id", raw.get("event_id", "exact_event_id"))),
        domain=str(_required(raw, "domain")),
        category=str(_required(raw, "category")),
        event_family_id=(
            str(raw["event_family_id"]) if raw.get("event_family_id") is not None else None
        ),
        is_sports=bool(raw.get("is_sports", False)),
        taxonomy_confidence=str(raw.get("taxonomy_confidence", "medium")),
        taxonomy_notes=str(raw.get("taxonomy_notes", "explicit event_id mapping")),
    )


def _parse_prefix_rule(raw: object) -> PrefixTaxonomyRule:
    if not isinstance(raw, dict):
        raise ValueError("prefix taxonomy rule must be a mapping")
    return PrefixTaxonomyRule(
        rule_id=str(_required(raw, "rule_id")),
        pattern=str(_required(raw, "pattern")),
        domain=str(_required(raw, "domain")),
        category=str(_required(raw, "category")),
        is_sports=bool(raw.get("is_sports", False)),
        taxonomy_confidence=str(raw.get("taxonomy_confidence", "medium")),
        taxonomy_notes=str(raw.get("taxonomy_notes", "explicit prefix rule")),
        priority=int(raw.get("priority", 100)),
    )


def _parse_title_rule(raw: object) -> TitleKeywordTaxonomyRule:
    if not isinstance(raw, dict):
        raise ValueError("title-keyword taxonomy rule must be a mapping")
    keywords = tuple(str(keyword) for keyword in raw.get("keywords", ()))
    pattern = raw.get("pattern")
    if pattern is None and not keywords:
        raise ValueError("title-keyword taxonomy rules require keywords or pattern")
    return TitleKeywordTaxonomyRule(
        rule_id=str(_required(raw, "rule_id")),
        keywords=keywords,
        pattern=str(pattern) if pattern is not None else None,
        domain=str(_required(raw, "domain")),
        category=str(_required(raw, "category")),
        is_sports=bool(raw.get("is_sports", False)),
        taxonomy_confidence=str(raw.get("taxonomy_confidence", "low")),
        taxonomy_notes=str(raw.get("taxonomy_notes", "explicit title-keyword rule")),
        priority=int(raw.get("priority", 1000)),
    )


def _parse_family_rule(raw: object) -> EventFamilyRegexRule:
    if not isinstance(raw, dict):
        raise ValueError("event-family regex rule must be a mapping")
    source_column = str(raw.get("source_column", "event_id"))
    if source_column not in {"event_id", "contract_id"}:
        raise ValueError("event-family source_column must be 'event_id' or 'contract_id'")
    return EventFamilyRegexRule(
        rule_id=str(_required(raw, "rule_id")),
        pattern=str(_required(raw, "pattern")),
        family_id_prefix=str(_required(raw, "family_id_prefix")),
        group_index=int(raw.get("group_index", 1)),
        source_column=source_column,
        event_family_confidence=str(raw.get("event_family_confidence", "medium")),
        taxonomy_notes=str(raw.get("taxonomy_notes", "event-family regex rule")),
        priority=int(raw.get("priority", 100)),
    )


def _create_rules(con: duckdb.DuckDBPyConnection, rules: tuple[TaxonomyRule, ...]) -> None:
    con.execute(
        """
        CREATE TEMP TABLE taxonomy_rules(
            rule_id VARCHAR,
            event_id VARCHAR,
            event_family_id VARCHAR,
            domain VARCHAR,
            category VARCHAR,
            is_sports BOOLEAN,
            taxonomy_confidence VARCHAR,
            taxonomy_notes VARCHAR
        )
        """
    )
    if not rules:
        return
    values = ", ".join(
        "("
        f"{_sql_string(rule.rule_id or rule.event_id)}, "
        f"{_sql_string(rule.event_id)}, "
        f"{_sql_string(rule.event_family_id or '')}, "
        f"{_sql_string(rule.domain)}, "
        f"{_sql_string(rule.category)}, "
        f"{str(rule.is_sports).lower()}, "
        f"{_sql_string(rule.taxonomy_confidence)}, "
        f"{_sql_string(rule.taxonomy_notes)}"
        ")"
        for rule in rules
    )
    con.execute(f"INSERT INTO taxonomy_rules VALUES {values}")


def _create_prefix_rules(
    con: duckdb.DuckDBPyConnection,
    rules: tuple[PrefixTaxonomyRule, ...],
) -> None:
    con.execute(
        """
        CREATE TEMP TABLE prefix_rules(
            rule_id VARCHAR,
            pattern VARCHAR,
            domain VARCHAR,
            category VARCHAR,
            is_sports BOOLEAN,
            taxonomy_confidence VARCHAR,
            taxonomy_notes VARCHAR,
            priority INTEGER
        )
        """
    )
    if not rules:
        return
    values = ", ".join(
        "("
        f"{_sql_string(rule.rule_id)}, "
        f"{_sql_string(rule.pattern)}, "
        f"{_sql_string(rule.domain)}, "
        f"{_sql_string(rule.category)}, "
        f"{str(rule.is_sports).lower()}, "
        f"{_sql_string(rule.taxonomy_confidence)}, "
        f"{_sql_string(rule.taxonomy_notes)}, "
        f"{rule.priority}"
        ")"
        for rule in rules
    )
    con.execute(f"INSERT INTO prefix_rules VALUES {values}")


def _create_title_rules(
    con: duckdb.DuckDBPyConnection,
    rules: tuple[TitleKeywordTaxonomyRule, ...],
) -> None:
    con.execute(
        """
        CREATE TEMP TABLE title_rules(
            rule_id VARCHAR,
            pattern VARCHAR,
            domain VARCHAR,
            category VARCHAR,
            is_sports BOOLEAN,
            taxonomy_confidence VARCHAR,
            taxonomy_notes VARCHAR,
            priority INTEGER
        )
        """
    )
    if not rules:
        return
    values = ", ".join(
        "("
        f"{_sql_string(rule.rule_id)}, "
        f"{_sql_string(_title_pattern(rule))}, "
        f"{_sql_string(rule.domain)}, "
        f"{_sql_string(rule.category)}, "
        f"{str(rule.is_sports).lower()}, "
        f"{_sql_string(rule.taxonomy_confidence)}, "
        f"{_sql_string(rule.taxonomy_notes)}, "
        f"{rule.priority}"
        ")"
        for rule in rules
    )
    con.execute(f"INSERT INTO title_rules VALUES {values}")


def _create_family_rules(
    con: duckdb.DuckDBPyConnection,
    rules: tuple[EventFamilyRegexRule, ...],
) -> None:
    con.execute(
        """
        CREATE TEMP TABLE event_family_rules(
            rule_id VARCHAR,
            pattern VARCHAR,
            family_id_prefix VARCHAR,
            group_index INTEGER,
            source_column VARCHAR,
            event_family_confidence VARCHAR,
            taxonomy_notes VARCHAR,
            priority INTEGER
        )
        """
    )
    if not rules:
        return
    values = ", ".join(
        "("
        f"{_sql_string(rule.rule_id)}, "
        f"{_sql_string(rule.pattern)}, "
        f"{_sql_string(rule.family_id_prefix)}, "
        f"{rule.group_index}, "
        f"{_sql_string(rule.source_column)}, "
        f"{_sql_string(rule.event_family_confidence)}, "
        f"{_sql_string(rule.taxonomy_notes)}, "
        f"{rule.priority}"
        ")"
        for rule in rules
    )
    con.execute(f"INSERT INTO event_family_rules VALUES {values}")


def _create_enriched_panel(con: duckdb.DuckDBPyConnection, config: TaxonomyConfig) -> None:
    con.execute(
        f"""
        CREATE TEMP TABLE enriched_panel AS
        WITH base_panel AS (
            SELECT
                row_number() OVER () AS taxonomy_row_id,
                p.*,
                c.title,
                c.yes_sub_title,
                c.no_sub_title
            FROM read_parquet({_sql_string(config.panel_path)}) AS p
            LEFT JOIN read_parquet({_sql_string(config.contracts_path)}) AS c
              ON c.contract_id = p.contract_id
        ),
        taxonomy_matches AS (
            SELECT
                b.taxonomy_row_id,
                0 AS source_priority,
                0 AS rule_priority,
                r.rule_id,
                'exact_event_id_mapping' AS taxonomy_source,
                r.domain,
                r.category,
                r.is_sports,
                r.taxonomy_confidence,
                r.taxonomy_notes
            FROM base_panel AS b
            JOIN taxonomy_rules AS r
              ON r.event_id = b.event_id
            UNION ALL
            SELECT
                b.taxonomy_row_id,
                2 AS source_priority,
                r.priority AS rule_priority,
                r.rule_id,
                'prefix_regex_rule' AS taxonomy_source,
                r.domain,
                r.category,
                r.is_sports,
                r.taxonomy_confidence,
                r.taxonomy_notes
            FROM base_panel AS b
            JOIN prefix_rules AS r
              ON regexp_matches(
                    concat_ws(' ', coalesce(b.event_id, ''), coalesce(b.contract_id, '')),
                    r.pattern,
                    'i'
                 )
            UNION ALL
            SELECT
                b.taxonomy_row_id,
                3 AS source_priority,
                r.priority AS rule_priority,
                r.rule_id,
                'title_keyword_rule' AS taxonomy_source,
                r.domain,
                r.category,
                r.is_sports,
                r.taxonomy_confidence,
                r.taxonomy_notes
            FROM base_panel AS b
            JOIN title_rules AS r
              ON regexp_matches(
                    concat_ws(
                        ' ',
                        coalesce(b.title, ''),
                        coalesce(b.yes_sub_title, ''),
                        coalesce(b.no_sub_title, '')
                    ),
                    r.pattern,
                    'i'
                 )
        ),
        title_conflicts AS (
            SELECT taxonomy_row_id
            FROM taxonomy_matches
            WHERE taxonomy_source = 'title_keyword_rule'
            GROUP BY taxonomy_row_id
            HAVING count(DISTINCT concat(domain, '|', category)) > 1
        ),
        ranked_taxonomy AS (
            SELECT *
            FROM (
                SELECT
                    m.*,
                    row_number() OVER (
                        PARTITION BY taxonomy_row_id
                        ORDER BY source_priority, rule_priority, rule_id
                    ) AS rn
                FROM taxonomy_matches AS m
            )
            WHERE rn = 1
        ),
        family_matches AS (
            SELECT
                b.taxonomy_row_id,
                0 AS source_priority,
                0 AS rule_priority,
                r.rule_id,
                r.event_family_id,
                'exact_event_id_mapping' AS event_family_source,
                r.taxonomy_confidence AS event_family_confidence
            FROM base_panel AS b
            JOIN taxonomy_rules AS r
              ON r.event_id = b.event_id
             AND r.event_family_id IS NOT NULL
             AND r.event_family_id != ''
            UNION ALL
            SELECT
                b.taxonomy_row_id,
                1 AS source_priority,
                r.priority AS rule_priority,
                r.rule_id,
                concat(
                    r.family_id_prefix,
                    CASE r.group_index
                        WHEN 0 THEN regexp_extract(
                            CASE
                                WHEN r.source_column = 'contract_id'
                                THEN coalesce(b.contract_id, '')
                                ELSE coalesce(b.event_id, '')
                            END,
                            r.pattern,
                            0
                        )
                        WHEN 2 THEN regexp_extract(
                            CASE
                                WHEN r.source_column = 'contract_id'
                                THEN coalesce(b.contract_id, '')
                                ELSE coalesce(b.event_id, '')
                            END,
                            r.pattern,
                            2
                        )
                        ELSE regexp_extract(
                            CASE
                                WHEN r.source_column = 'contract_id'
                                THEN coalesce(b.contract_id, '')
                                ELSE coalesce(b.event_id, '')
                            END,
                            r.pattern,
                            1
                        )
                    END
                ) AS event_family_id,
                'event_family_regex_rule' AS event_family_source,
                r.event_family_confidence
            FROM base_panel AS b
            JOIN event_family_rules AS r
              ON regexp_matches(
                    CASE
                        WHEN r.source_column = 'contract_id' THEN coalesce(b.contract_id, '')
                        ELSE coalesce(b.event_id, '')
                    END,
                    r.pattern,
                    'i'
                 )
        ),
        ranked_family AS (
            SELECT *
            FROM (
                SELECT
                    m.*,
                    row_number() OVER (
                        PARTITION BY taxonomy_row_id
                        ORDER BY source_priority, rule_priority, rule_id
                    ) AS rn
                FROM family_matches AS m
                WHERE m.event_family_id IS NOT NULL AND m.event_family_id != ''
            )
            WHERE rn = 1
        )
        SELECT
            b.* EXCLUDE (taxonomy_row_id),
            COALESCE(NULLIF(f.event_family_id, ''), NULLIF(b.event_id, ''), b.contract_id)
                AS event_family_id,
            CASE
                WHEN tc.taxonomy_row_id IS NOT NULL THEN 'ambiguous'
                ELSE COALESCE(NULLIF(t.domain, ''), {_sql_string(config.default_domain)})
            END AS domain,
            CASE
                WHEN tc.taxonomy_row_id IS NOT NULL THEN 'ambiguous'
                ELSE COALESCE(NULLIF(t.category, ''), {_sql_string(config.default_category)})
            END AS category,
            CASE
                WHEN tc.taxonomy_row_id IS NOT NULL THEN 'ambiguous_title_keyword_rule'
                WHEN t.rule_id IS NOT NULL THEN t.taxonomy_source
                ELSE {_sql_string(config.default_taxonomy_source)}
            END AS taxonomy_source,
            CASE
                WHEN tc.taxonomy_row_id IS NOT NULL THEN 'ambiguous'
                WHEN t.rule_id IS NOT NULL THEN t.taxonomy_confidence
                ELSE {_sql_string(config.default_taxonomy_confidence)}
            END AS taxonomy_confidence,
            CASE
                WHEN tc.taxonomy_row_id IS NOT NULL THEN 'conflicting explicit title-keyword rules'
                WHEN t.rule_id IS NOT NULL THEN t.taxonomy_notes
                ELSE {_sql_string(config.default_taxonomy_notes)}
            END AS taxonomy_notes,
            CASE
                WHEN tc.taxonomy_row_id IS NOT NULL THEN false
                ELSE COALESCE(t.is_sports, {str(config.default_is_sports).lower()})
            END AS is_sports,
            CASE
                WHEN tc.taxonomy_row_id IS NOT NULL THEN 'ambiguous_title_keyword_rule'
                ELSE COALESCE(t.rule_id, 'default_unknown')
            END AS taxonomy_rule_id,
            tc.taxonomy_row_id IS NOT NULL AS taxonomy_ambiguous,
            CASE
                WHEN f.rule_id IS NOT NULL THEN f.event_family_source
                WHEN b.event_id IS NOT NULL AND b.event_id != '' THEN 'event_id_fallback'
                ELSE 'contract_id_fallback'
            END AS event_family_source,
            CASE
                WHEN f.rule_id IS NOT NULL THEN f.event_family_confidence
                WHEN b.event_id IS NOT NULL AND b.event_id != '' THEN 'low'
                ELSE 'low'
            END AS event_family_confidence
        FROM base_panel AS b
        LEFT JOIN ranked_taxonomy AS t
          ON t.taxonomy_row_id = b.taxonomy_row_id
        LEFT JOIN title_conflicts AS tc
          ON tc.taxonomy_row_id = b.taxonomy_row_id
        LEFT JOIN ranked_family AS f
          ON f.taxonomy_row_id = b.taxonomy_row_id
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
            is_sports,
            taxonomy_rule_id,
            taxonomy_ambiguous,
            event_family_source,
            event_family_confidence,
            taxonomy_notes,
            domain = 'unknown' OR category = 'unknown' AS is_unknown_group,
            taxonomy_ambiguous AS is_ambiguous_group,
            count(*) AS row_count,
            count(DISTINCT contract_id) AS contract_count,
            count(DISTINCT event_family_id) AS event_family_count
        FROM enriched_panel
        GROUP BY
            taxonomy_source,
            domain,
            category,
            taxonomy_confidence,
            is_sports,
            taxonomy_rule_id,
            taxonomy_ambiguous,
            event_family_source,
            event_family_confidence,
            taxonomy_notes,
            is_unknown_group,
            is_ambiguous_group
        ORDER BY row_count DESC, taxonomy_source, domain, category
        """
    )


def _create_examples(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TEMP TABLE taxonomy_examples AS
        WITH candidates AS (
            SELECT
                taxonomy_source,
                domain,
                category,
                taxonomy_confidence,
                taxonomy_rule_id,
                taxonomy_ambiguous,
                event_family_source,
                event_family_confidence,
                event_id,
                contract_id,
                title,
                yes_sub_title,
                no_sub_title,
                row_number() OVER (
                    PARTITION BY
                        taxonomy_source,
                        domain,
                        category,
                        taxonomy_confidence,
                        taxonomy_ambiguous
                    ORDER BY contract_id
                ) AS example_rank
            FROM enriched_panel
            WHERE
                domain IN ('unknown', 'ambiguous')
                OR category IN ('unknown', 'ambiguous')
                OR taxonomy_ambiguous
        )
        SELECT *
        FROM candidates
        WHERE example_rank <= 25
        ORDER BY taxonomy_source, domain, category, example_rank
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
    event_family_source_counts = _count_map(con, "event_family_source")
    taxonomy_confidence_counts = _count_map(con, "taxonomy_confidence")
    event_family_confidence_counts = _count_map(con, "event_family_confidence")
    unknown_row_count = int(
        con.execute(
            """
            SELECT count(*) FROM enriched_panel
            WHERE domain = 'unknown' OR category = 'unknown'
            """
        ).fetchone()[0]
    )
    ambiguous_row_count = int(
        con.execute("SELECT count(*) FROM enriched_panel WHERE taxonomy_ambiguous").fetchone()[0]
    )
    sports_row_count = int(
        con.execute("SELECT count(*) FROM enriched_panel WHERE is_sports").fetchone()[0]
    )
    return TaxonomyBuildSummary(
        input_panel_path=str(config.panel_path),
        contracts_path=str(config.contracts_path),
        output_panel_path=str(config.output_panel_path),
        audit_path=str(config.audit_path),
        examples_path=str(_examples_path(config)),
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
        prefix_rule_count=len(config.prefix_rules),
        title_keyword_rule_count=len(config.title_keyword_rules),
        event_family_regex_rule_count=len(config.event_family_regex_rules),
        unknown_rate=unknown_row_count / output_row_count if output_row_count else 0.0,
        ambiguous_rate=ambiguous_row_count / output_row_count if output_row_count else 0.0,
        sports_row_count=sports_row_count,
        sports_rate=sports_row_count / output_row_count if output_row_count else 0.0,
        event_family_source_counts=event_family_source_counts,
        taxonomy_confidence_counts=taxonomy_confidence_counts,
        event_family_confidence_counts=event_family_confidence_counts,
        effective_config=_effective_config(config),
        limitations=[
            "taxonomy rules are explicit and config-driven; title-keyword rules are lower "
            "confidence",
            "ambiguous title-keyword conflicts are flagged rather than silently resolved",
            "event_family_id falls back to event_id or contract_id when regex grouping is "
            "unavailable",
            "domain/category claims remain conditional on taxonomy confidence and ambiguity audits",
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
            "examples_path": str(_examples_path(config)),
            "summary_path": str(config.summary_path),
        },
        "taxonomy": {
            "default_domain": config.default_domain,
            "default_category": config.default_category,
            "default_taxonomy_source": config.default_taxonomy_source,
            "default_taxonomy_confidence": config.default_taxonomy_confidence,
            "default_taxonomy_notes": config.default_taxonomy_notes,
            "default_is_sports": config.default_is_sports,
            "event_family_proxy": config.event_family_proxy,
            "title_inference": config.title_inference,
            "explicit_event_id_mapping_count": len(config.explicit_event_id_mappings),
            "prefix_rule_count": len(config.prefix_rules),
            "title_keyword_rule_count": len(config.title_keyword_rules),
            "event_family_regex_rule_count": len(config.event_family_regex_rules),
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


def _title_pattern(rule: TitleKeywordTaxonomyRule) -> str:
    if rule.pattern:
        return rule.pattern
    escaped = [re.escape(keyword) for keyword in rule.keywords if keyword]
    if not escaped:
        raise ValueError(f"title-keyword rule has no usable keywords: {rule.rule_id}")
    return "|".join(escaped)


def _examples_path(config: TaxonomyConfig) -> Path:
    if config.examples_path is not None:
        return config.examples_path
    return config.audit_path.with_name(f"{config.audit_path.stem}_examples.parquet")


def _false_count(mask: pa.ChunkedArray | pa.Array) -> int:
    inverted = pc.invert(mask)
    return int(pc.sum(pc.cast(inverted, pa.int64())).as_py() or 0)
