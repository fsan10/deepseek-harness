from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from apps.fund_split_adjust.database import ConflictError, Database, RealDictCursor
from apps.fund_split_adjust.domain import allocate_adjustment_diffs, allocate_split_amounts


def verify_case(database: Database, adjustment: Decimal) -> None:
    connection = database.connect()
    try:
        cursor = connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT split.ods_id,split.batch_id,split.expense_type_id,split.account_entry_id,split.remark,
                   COALESCE(ABS(ods.debit_amount),ABS(ods.credit_amount)) AS source_amount
            FROM dwd.dwd_statement_split split
            JOIN ods.ods_bank_statement ods ON ods.id=split.ods_id
            JOIN fund.import_record record ON record.batch_id=split.batch_id
            WHERE record.is_submitted=FALSE
              AND COALESCE(ABS(ods.debit_amount),ABS(ods.credit_amount))>1000
              AND (SELECT COUNT(*) FROM dwd.dwd_statement_split sibling WHERE sibling.ods_id=split.ods_id)=1
            ORDER BY split.id
            LIMIT 1
            FOR UPDATE OF split
            """
        )
        source = cursor.fetchone()
        if not source:
            raise AssertionError("没有可用于回滚测试的未提交单行流水")
        cursor.execute(
            "UPDATE dwd.dwd_statement_split SET adjusted_diff=%s,is_adjusted=TRUE WHERE ods_id=%s",
            (adjustment, source["ods_id"]),
        )

        @contextmanager
        def shared_transaction():
            yield cursor

        database.transaction = shared_transaction  # type: ignore[method-assign]
        database.statement = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
        template = {
            "amount": None,
            "expense_type_id": source["expense_type_id"],
            "account_entry_id": source["account_entry_id"],
            "remark": source["remark"],
        }
        database.split(
            source["batch_id"],
            {"ods_id": source["ods_id"], "splits": [template, {**template, "remark": ""}]},
            "自动回滚测试",
            "127.0.0.1",
        )
        cursor.execute(
            """
            SELECT split_amount,original_amount,adjusted_diff,is_adjusted
            FROM dwd.dwd_statement_split WHERE ods_id=%s ORDER BY split_index
            """,
            (source["ods_id"],),
        )
        children = cursor.fetchall()
        expected = allocate_adjustment_diffs(adjustment, 2)
        assert len(children) == 2
        assert [row["adjusted_diff"] for row in children] == expected
        assert sum((row["adjusted_diff"] for row in children), Decimal("0.00")) == adjustment
        assert sum((row["original_amount"] for row in children), Decimal("0.00")) == source["source_amount"]
        assert all(row["is_adjusted"] for row in children)
        assert all(row["original_amount"] + row["adjusted_diff"] > 0 for row in children)

        parent_total = (source["source_amount"] + adjustment).quantize(Decimal("0.01"))
        result = database.adjust_parent(
            source["batch_id"], source["ods_id"], parent_total, "自动回滚测试", "127.0.0.1"
        )
        cursor.execute(
            """
            SELECT id,original_amount,adjusted_diff,original_amount+adjusted_diff AS adjusted_amount
            FROM dwd.dwd_statement_split WHERE ods_id=%s ORDER BY split_index
            """,
            (source["ods_id"],),
        )
        adjusted_children = cursor.fetchall()
        expected_current = allocate_split_amounts(parent_total, [None, None])
        assert [row["adjusted_amount"] for row in adjusted_children] == expected_current
        assert [item["split_id"] for item in result["child_amounts"]] == [row["id"] for row in adjusted_children]

        first, second = adjusted_children
        child_new_amount = first["adjusted_amount"] + Decimal("25.00")
        cursor.execute(
            "SELECT COALESCE(SUM(adjusted_diff),0) AS total_diff FROM dwd.dwd_statement_split WHERE batch_id=%s",
            (source["batch_id"],),
        )
        batch_diff_before = cursor.fetchone()["total_diff"]
        child_result = database.adjust_child(
            source["batch_id"], first["id"], child_new_amount, "自动回滚测试", "127.0.0.1"
        )
        cursor.execute(
            """
            SELECT id,original_amount+adjusted_diff AS adjusted_amount
            FROM dwd.dwd_statement_split WHERE ods_id=%s ORDER BY split_index
            """,
            (source["ods_id"],),
        )
        individually_adjusted = cursor.fetchall()
        assert individually_adjusted[0]["id"] == first["id"]
        assert individually_adjusted[0]["adjusted_amount"] == child_new_amount
        assert individually_adjusted[1]["id"] == second["id"]
        assert individually_adjusted[1]["adjusted_amount"] == second["adjusted_amount"] - Decimal("25.00")
        assert child_result["auto_split_id"] == second["id"]
        assert sum((row["adjusted_amount"] for row in individually_adjusted), Decimal("0.00")) == parent_total
        cursor.execute(
            "SELECT COALESCE(SUM(adjusted_diff),0) AS total_diff FROM dwd.dwd_statement_split WHERE batch_id=%s",
            (source["batch_id"],),
        )
        assert cursor.fetchone()["total_diff"] == batch_diff_before

        try:
            database.adjust_child(
                source["batch_id"], second["id"], second["adjusted_amount"], "自动回滚测试", "127.0.0.1"
            )
        except ConflictError as error:
            assert "自动分配子项不能调账" in str(error)
        else:
            raise AssertionError("自动分配子项应禁止调账")

        try:
            database.adjust(
                source["batch_id"], first["id"], child_new_amount, "自动回滚测试", "127.0.0.1"
            )
        except ConflictError as error:
            assert "请使用子项调账" in str(error)
        else:
            raise AssertionError("拆分子项不应通过普通调账改变母行总额")
    finally:
        connection.rollback()
        connection.close()


def main() -> None:
    for adjustment in (Decimal("300.00"), Decimal("-300.00")):
        database = Database(
            host=os.getenv("PGHOST", "192.168.77.111"),
            port=int(os.getenv("PGPORT", "5432")),
            dbname=os.getenv("PGDATABASE", "mock_coffice"),
            user=os.getenv("PGUSER", "postgres"),
            password=os.getenv("PGPASSWORD"),
            upload_dir=PROJECT_ROOT / "apps" / "fund_split_adjust" / "uploads",
        )
        verify_case(database, adjustment)
    print("子项调账数据库回滚测试通过：目标子项与自动项反向联动，母行总额和待分配差额均不变")


if __name__ == "__main__":
    main()
