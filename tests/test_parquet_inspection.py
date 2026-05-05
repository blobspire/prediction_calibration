from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from predmkt.io.inspection import inspect_raw_path


def test_inspect_raw_path_reads_parquet_columns(tmp_path: Path) -> None:
    raw_file = tmp_path / "trades.parquet"
    table = pa.table(
        {
            "ticker": ["ABC"],
            "created_time": ["2024-01-01T00:00:00Z"],
            "yes_price": [55],
        }
    )
    pq.write_table(table, raw_file)

    inspection = inspect_raw_path(raw_file)

    assert len(inspection) == 1
    assert inspection[0].columns == ("ticker", "created_time", "yes_price")
    price_schema = next(
        result
        for result in inspection[0].schema_results
        if result.schema_name == "price_observations"
    )
    assert price_schema.ok
