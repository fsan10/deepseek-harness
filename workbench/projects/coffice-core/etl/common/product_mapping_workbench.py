"""Shared product mapping snapshot lifecycle; callers own commit/rollback."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATE_SQL = ROOT / "sql/common/457_product_mapping_refresh_state_postgres.sql"
CREATE_SQL = ROOT / "sql/ads/operating_sales/458_ads_product_code_mapping_workbench_postgres.sql"
REFRESH_SQL = ROOT / "sql/ads/operating_sales/459_refresh_ads_product_code_mapping_workbench_postgres.sql"


def lock_product_refresh(cursor, *, global_lock_held: bool = False) -> None:
    # The registered ETL executor holds the global session lock for this process.
    # The metric connection must not reacquire it on another connection.
    if not global_lock_held:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('mock_coffice_global_etl'))")
    cursor.execute("SELECT pg_advisory_xact_lock(hashtext('mock_coffice_product_mapping_refresh'))")


def create_workbench(cursor) -> None:
    for path in (STATE_SQL, CREATE_SQL):
        cursor.execute(path.read_text(encoding="utf-8"))


def publish_workbench(cursor) -> dict:
    cursor.execute(REFRESH_SQL.read_text(encoding="utf-8"))
    cursor.execute("SELECT summary FROM ops.refresh_watermark WHERE watermark_key = 'product_code_mapping'")
    row = cursor.fetchone()
    return dict(row["summary"] if isinstance(row, dict) else row[0])
