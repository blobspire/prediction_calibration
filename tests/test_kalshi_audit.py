from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from predmkt.io.kalshi_audit import audit_directory_schemas, schema_ok_for_all
from predmkt.io.schema import PRICE_OBSERVATIONS_SCHEMA


def test_audit_directory_schemas_groups_identical_parquet_schemas(tmp_path: Path) -> None:
    for name in ("a.parquet", "b.parquet"):
        pq.write_table(
            pa.table(
                {
                    "ticker": ["ABC"],
                    "created_time": ["2024-01-01T00:00:00Z"],
                    "yes_price": [55],
                }
            ),
            tmp_path / name,
        )

    audit = audit_directory_schemas(tmp_path)

    assert audit.file_count == 2
    assert len(audit.schema_groups) == 1
    assert audit.schema_groups[0].file_count == 2
    assert audit.unreadable_files == ()
    assert schema_ok_for_all(audit, PRICE_OBSERVATIONS_SCHEMA)

