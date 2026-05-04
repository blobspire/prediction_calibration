"""Schema definitions and validation helpers for raw Kalshi data inspection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class FieldSpec:
    """Canonical field requirement with optional source-column aliases."""

    name: str
    description: str
    required: bool = True
    aliases: tuple[str, ...] = ()

    @property
    def accepted_names(self) -> frozenset[str]:
        return frozenset((self.name, *self.aliases))


@dataclass(frozen=True)
class TableSchema:
    """Minimum column expectations for a raw source table."""

    name: str
    description: str
    fields: tuple[FieldSpec, ...]

    @property
    def required_fields(self) -> tuple[FieldSpec, ...]:
        return tuple(field for field in self.fields if field.required)


@dataclass(frozen=True)
class FieldValidation:
    """Validation result for one canonical field."""

    field_name: str
    required: bool
    matched_column: str | None
    accepted_names: tuple[str, ...]

    @property
    def present(self) -> bool:
        return self.matched_column is not None


@dataclass(frozen=True)
class SchemaValidationResult:
    """Column-level validation result for one source table candidate."""

    schema_name: str
    columns: tuple[str, ...]
    fields: tuple[FieldValidation, ...]
    extra_columns: tuple[str, ...]

    @property
    def missing_required(self) -> tuple[str, ...]:
        return tuple(field.field_name for field in self.fields if field.required and not field.present)

    @property
    def ok(self) -> bool:
        return not self.missing_required


CONTRACTS_SCHEMA = TableSchema(
    name="contracts",
    description="Resolved binary contract metadata needed before snapshot construction.",
    fields=(
        FieldSpec(
            "contract_id",
            "Stable contract identifier.",
            aliases=("ticker", "contract_ticker"),
        ),
        FieldSpec(
            "event_id",
            "Event or market-family identifier used for dependence checks.",
            aliases=("market_id", "event_ticker", "series_ticker"),
        ),
        FieldSpec(
            "resolution_ts",
            "Explicit timestamp when the contract outcome became knowable.",
            aliases=("resolved_at", "settled_at", "close_time", "expiration_time"),
        ),
        FieldSpec(
            "outcome",
            "Resolved binary outcome encoded separately from market price history.",
            aliases=("result", "settlement_value", "settlement"),
        ),
        FieldSpec(
            "status",
            "Lifecycle status used to exclude voided, canceled, delisted, or unresolved contracts.",
            aliases=("contract_status", "market_status"),
        ),
        FieldSpec(
            "title",
            "Human-readable contract title for audits and event-family mapping.",
            required=False,
            aliases=("name", "subtitle"),
        ),
        FieldSpec(
            "category",
            "Domain/category used for slice reporting.",
            required=False,
            aliases=("domain", "market_category"),
        ),
    ),
)

PRICE_OBSERVATIONS_SCHEMA = TableSchema(
    name="price_observations",
    description="Pre-resolution transaction or price observations used to build horizon snapshots.",
    fields=(
        FieldSpec(
            "contract_id",
            "Stable contract identifier linking prices to contracts.",
            aliases=("ticker", "contract_ticker"),
        ),
        FieldSpec(
            "source_ts",
            "Explicit observation timestamp; must be at or before any forecast timestamp using it.",
            aliases=("trade_ts", "created_time", "created_at", "timestamp", "ts"),
        ),
        FieldSpec(
            "yes_price",
            "Observed YES-side transaction price or probability proxy.",
            aliases=("price", "yes_bid", "yes_ask", "yes_price_cents"),
        ),
        FieldSpec(
            "volume",
            "Quantity or volume used for VWAP and liquidity diagnostics.",
            required=False,
            aliases=("count", "quantity", "trade_count"),
        ),
    ),
)

RAW_KALSHI_SCHEMAS: tuple[TableSchema, ...] = (CONTRACTS_SCHEMA, PRICE_OBSERVATIONS_SCHEMA)


def validate_columns(columns: Iterable[str], schema: TableSchema) -> SchemaValidationResult:
    """Validate source columns against a canonical schema and report missing/extra fields."""

    column_tuple = tuple(columns)
    column_lookup = {column.lower(): column for column in column_tuple}
    used_columns: set[str] = set()
    field_results: list[FieldValidation] = []

    for field in schema.fields:
        accepted_names = tuple((field.name, *field.aliases))
        matched_column = next(
            (column_lookup[name.lower()] for name in accepted_names if name.lower() in column_lookup),
            None,
        )
        if matched_column is not None:
            used_columns.add(matched_column)
        field_results.append(
            FieldValidation(
                field_name=field.name,
                required=field.required,
                matched_column=matched_column,
                accepted_names=accepted_names,
            )
        )

    extra_columns = tuple(column for column in column_tuple if column not in used_columns)
    return SchemaValidationResult(
        schema_name=schema.name,
        columns=column_tuple,
        fields=tuple(field_results),
        extra_columns=extra_columns,
    )

