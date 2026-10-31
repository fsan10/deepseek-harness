from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from decimal import Decimal
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
            SELECT split_row.id AS split_id,split_row.ods_id,split_row.batch_id,
                   split_row.original_amount,split_row.expense_type_id,split_row.account_entry_id,split_row.remark
            FROM dwd.dwd_statement_split split_row
            JOIN ods.ods_bank_statement ods ON ods.id=split_row.ods_id
            JOIN fund.import_record record ON record.batch_id=split_row.batch_id
            WHERE (SELECT COUNT(*) FROM dwd.dwd_statement_split sibling WHERE sibling.ods_id=split_row.ods_id)=1
              AND split_row.original_amount>100
            ORDER BY record.is_submitted,record.created_at DESC,split_row.id
            LIMIT 1
            FOR UPDATE OF split_row,record
            """
        )
        target = cursor.fetchone()
        if not target:
            raise AssertionError("缺少可用于金额复原回测的流水")
        cursor.execute(
            "UPDATE fund.import_record SET is_submitted=FALSE,submitted_at=NULL WHERE batch_id=%s",
            (target["batch_id"],),
        )

        @contextmanager
        def shared_transaction():
            yield cursor

        database.transaction = shared_transaction  # type: ignore[method-assign]
        database.statement = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]

        source_amount = target["original_amount"]
        database.adjust(
            target["batch_id"], target["split_id"], source_amount + Decimal("100.00"),
            "金额复原回测", "127.0.0.1",
        )
        restored_row = database.restore_amount(
            target["batch_id"], {"split_id": target["split_id"]}, "金额复原回测", "127.0.0.1"
        )
        assert restored_row["restored"] is True
        cursor.execute("SELECT adjusted_diff,is_adjusted FROM dwd.dwd_statement_split WHERE id=%s", (target["split_id"],))
        ordinary = cursor.fetchone()
        assert ordinary["adjusted_diff"] == Decimal("0.00")
        assert ordinary["is_adjusted"] is False

        first_amount = (source_amount * Decimal("0.40")).quantize(Decimal("0.01"))
        database.split(
            target["batch_id"],
            {
                "ods_id": target["ods_id"],
                "splits": [
                    {
                        "amount": str(first_amount),
                        "expense_type_id": target["expense_type_id"],
                        "account_entry_id": target["account_entry_id"],
                        "remark": target["remark"],
                    },
                    {
                        "amount": None,
                        "expense_type_id": target["expense_type_id"],
                        "account_entry_id": target["account_entry_id"],
                        "remark": "",
                    },
                ],
            },
            "金额复原回测",
            "127.0.0.1",
        )
        cursor.execute(
            "SELECT id,split_index,original_amount,adjusted_diff FROM dwd.dwd_statement_split "
            "WHERE ods_id=%s ORDER BY split_index",
            (target["ods_id"],),
        )
        children = cursor.fetchall()
        assert len(children) == 2

        database.adjust_parent(
            target["batch_id"], target["ods_id"], source_amount + Decimal("100.00"),
            "金额复原回测", "127.0.0.1",
        )
        restored_parent = database.restore_amount(
            target["batch_id"], {"ods_id": target["ods_id"]}, "金额复原回测", "127.0.0.1"
        )
        assert restored_parent["new_amount"] == source_amount
        cursor.execute(
            "SELECT SUM(original_amount+adjusted_diff) AS total FROM dwd.dwd_statement_split WHERE ods_id=%s",
            (target["ods_id"],),
        )
        assert cursor.fetchone()["total"] == source_amount

        cursor.execute(
            "SELECT id,original_amount,original_amount+adjusted_diff AS adjusted_amount "
            "FROM dwd.dwd_statement_split WHERE ods_id=%s ORDER BY split_index",
            (target["ods_id"],),
        )
        children = cursor.fetchall()
        manual_child, auto_child = children
        child_test_amount = min(
            manual_child["original_amount"] + Decimal("10.00"),
            manual_child["adjusted_amount"] + Decimal("5.00"),
        )
        database.adjust_child(
            target["batch_id"], manual_child["id"], child_test_amount,
            "金额复原回测", "127.0.0.1",
        )
        database.restore_amount(
            target["batch_id"], {"split_id": manual_child["id"]}, "金额复原回测", "127.0.0.1"
        )
        cursor.execute(
            "SELECT id,original_amount,original_amount+adjusted_diff AS adjusted_amount "
            "FROM dwd.dwd_statement_split WHERE ods_id=%s ORDER BY split_index",
            (target["ods_id"],),
        )
        restored_children = cursor.fetchall()
        assert restored_children[0]["adjusted_amount"] == restored_children[0]["original_amount"]
        assert sum((row["adjusted_amount"] for row in restored_children), Decimal("0.00")) == source_amount
        assert restored_children[1]["id"] == auto_child["id"]

        cursor.execute(
            "SELECT COUNT(*) AS count FROM fund.operation_log WHERE operation_type='restore' AND operator=%s",
            ("金额复原回测",),
        )
        assert cursor.fetchone()["count"] == 3
        print("金额复原回测通过：普通行、拆分母行、拆分子项及操作日志均符合预期")
    finally:
        connection.rollback()
        connection.close()


if __name__ == "__main__":
    main()
