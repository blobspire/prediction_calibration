from pathlib import Path

from predmkt.io.inspection import inspect_raw_path


def test_inspect_raw_path_reports_empty_directory(tmp_path: Path) -> None:
    assert inspect_raw_path(tmp_path) == ()


def test_inspect_raw_path_reads_csv_columns_and_hashes(tmp_path: Path) -> None:
    raw_file = tmp_path / "prices.csv"
    raw_file.write_text("ticker,created_at,price\nABC,2024-01-01T00:00:00Z,0.55\n", encoding="utf-8")

    inspection = inspect_raw_path(tmp_path)

    assert len(inspection) == 1
    assert inspection[0].columns == ("ticker", "created_at", "price")
    assert inspection[0].manifest.sha256
    price_schema = next(
        result for result in inspection[0].schema_results if result.schema_name == "price_observations"
    )
    assert price_schema.ok

