from predmkt.io.schema import CONTRACTS_SCHEMA, PRICE_OBSERVATIONS_SCHEMA, validate_columns


def test_validate_columns_reports_missing_required_fields() -> None:
    result = validate_columns(["contract_id", "resolution_ts"], CONTRACTS_SCHEMA)

    assert not result.ok
    assert result.missing_required == ("event_id", "outcome", "status")
    assert result.extra_columns == ()


def test_validate_columns_uses_aliases_and_reports_extra_columns() -> None:
    result = validate_columns(
        ["ticker", "created_at", "price", "unexpected_column"],
        PRICE_OBSERVATIONS_SCHEMA,
    )

    assert result.ok
    assert result.missing_required == ()
    assert result.extra_columns == ("unexpected_column",)
    matched = {field.field_name: field.matched_column for field in result.fields}
    assert matched["contract_id"] == "ticker"
    assert matched["source_ts"] == "created_at"
    assert matched["yes_price"] == "price"

