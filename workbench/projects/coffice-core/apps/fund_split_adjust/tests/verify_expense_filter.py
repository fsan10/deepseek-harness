from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from apps.fund_split_adjust.database import Database, RealDictCursor


def main() -> None:
    database = Database(
        host=os.getenv("PGHOST", "192.168.77.111"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "mock_coffice"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD"),
        upload_dir=PROJECT_ROOT / "apps" / "fund_split_adjust" / "uploads",
    )
    connection = database.connect()
    try:
        cursor = connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT split.id,split.ods_id,split.batch_id,split.expense_type_id
            FROM dwd.dwd_statement_split split
            JOIN fund.import_record record ON record.batch_id=split.batch_id
            WHERE record.is_submitted=FALSE
              AND split.expense_type_id IS NOT NULL
              AND (SELECT COUNT(*) FROM dwd.dwd_statement_split sibling WHERE sibling.ods_id=split.ods_id)=1
            ORDER BY split.id LIMIT 1 FOR UPDATE OF split
            """
        )
        target = cursor.fetchone()
        if not target:
            raise AssertionError("没有可用于费用类型筛选回滚测试的单行流水")

        @contextmanager
        def shared_transaction():
            yield cursor

        database.transaction = shared_transaction  # type: ignore[method-assign]
        assigned = database.statement(
            target["batch_id"], {"page_size": "200", "expense_type_id": str(target["expense_type_id"])}
        )
        assert target["ods_id"] in {parent["ods_id"] for parent in assigned["rows"]}

        cursor.execute(
            "UPDATE dwd.dwd_statement_split SET expense_type_id=NULL,account_entry_id=NULL WHERE id=%s",
            (target["id"],),
        )
        unassigned = database.statement(
            target["batch_id"], {"page_size": "200", "expense_type_id": "unassigned"}
        )
        assert target["ods_id"] in {parent["ods_id"] for parent in unassigned["rows"]}
        print("费用类型筛选数据库回滚测试通过：具体费用类型和未分配均可正确筛选")
    finally:
        connection.rollback()
        connection.close()


if __name__ == "__main__":
    main()
