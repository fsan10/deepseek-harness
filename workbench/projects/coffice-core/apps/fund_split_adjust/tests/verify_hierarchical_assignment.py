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
            SELECT split_row.id AS split_id,split_row.batch_id,
                   split_row.expense_type_id AS old_expense_id,
                   split_row.account_entry_id AS old_account_id,
                   alternative.expense_type_id AS new_expense_id,
                   alternative.account_entry_id AS compatible_account_id
            FROM dwd.dwd_statement_split split_row
            JOIN fund.import_record record ON record.batch_id=split_row.batch_id
            CROSS JOIN LATERAL (
              SELECT relation.expense_type_id,MIN(relation.account_entry_id) AS account_entry_id
              FROM dim.dim_account_entry_expense_type relation
              JOIN dim.dim_expense_type expense ON expense.id=relation.expense_type_id AND expense.is_active=TRUE
              JOIN dim.dim_account_entry account_entry ON account_entry.id=relation.account_entry_id AND account_entry.is_active=TRUE
              WHERE relation.expense_type_id<>split_row.expense_type_id
                AND NOT EXISTS(
                  SELECT 1 FROM dim.dim_account_entry_expense_type old_relation
                  WHERE old_relation.expense_type_id=relation.expense_type_id
                    AND old_relation.account_entry_id=split_row.account_entry_id
                )
              GROUP BY relation.expense_type_id
              ORDER BY relation.expense_type_id
              LIMIT 1
            ) alternative
            WHERE split_row.expense_type_id IS NOT NULL
              AND split_row.account_entry_id IS NOT NULL
            ORDER BY record.is_submitted,record.created_at DESC,split_row.id
            LIMIT 1
            FOR UPDATE OF split_row,record
            """
        )
        target = cursor.fetchone()
        if not target:
            raise AssertionError("缺少可用于验证一、二级分类的测试数据")
        cursor.execute(
            "UPDATE fund.import_record SET is_submitted=FALSE,submitted_at=NULL WHERE batch_id=%s",
            (target["batch_id"],),
        )

        @contextmanager
        def shared_transaction():
            yield cursor

        database.transaction = shared_transaction  # type: ignore[method-assign]

        result = database.batch_assign(
            target["batch_id"],
            {"split_ids": [target["split_id"]], "field": "expense_type_id", "value": target["new_expense_id"]},
            "分类层级回测",
            "127.0.0.1",
        )
        assert result == {"updated": 1, "cleared_account_count": 1}
        cursor.execute(
            "SELECT expense_type_id,account_entry_id FROM dwd.dwd_statement_split WHERE id=%s",
            (target["split_id"],),
        )
        changed = cursor.fetchone()
        assert changed["expense_type_id"] == target["new_expense_id"]
        assert changed["account_entry_id"] is None

        filtered_accounts = database.account_entries(
            expense_type_id=target["new_expense_id"], active="true"
        )
        filtered_ids = {row["id"] for row in filtered_accounts}
        assert target["compatible_account_id"] in filtered_ids
        assert target["old_account_id"] not in filtered_ids

        try:
            database.batch_assign(
                target["batch_id"],
                {"split_ids": [target["split_id"]], "field": "account_entry_id", "value": target["old_account_id"]},
                "分类层级回测",
                "127.0.0.1",
            )
        except ValueError as error:
            assert "不允许归属" in str(error)
        else:
            raise AssertionError("不属于当前费用类型的入账应被拦截")

        database.batch_assign(
            target["batch_id"],
            {"split_ids": [target["split_id"]], "field": "account_entry_id", "value": target["compatible_account_id"]},
            "分类层级回测",
            "127.0.0.1",
        )
        preserved = database.batch_assign(
            target["batch_id"],
            {"split_ids": [target["split_id"]], "field": "expense_type_id", "value": target["new_expense_id"]},
            "分类层级回测",
            "127.0.0.1",
        )
        assert preserved["cleared_account_count"] == 0
        cursor.execute("SELECT account_entry_id FROM dwd.dwd_statement_split WHERE id=%s", (target["split_id"],))
        assert cursor.fetchone()["account_entry_id"] == target["compatible_account_id"]

        cursor.execute(
            "UPDATE dwd.dwd_statement_split SET expense_type_id=NULL,account_entry_id=NULL WHERE id=%s",
            (target["split_id"],),
        )
        try:
            database.batch_assign(
                target["batch_id"],
                {"split_ids": [target["split_id"]], "field": "account_entry_id", "value": target["compatible_account_id"]},
                "分类层级回测",
                "127.0.0.1",
            )
        except ValueError as error:
            assert "先选择费用类型" in str(error)
        else:
            raise AssertionError("未选费用类型时不应允许直接选择入账")

        print(
            "一、二级分类回测通过：费用类型可直接修改，不匹配入账自动清空，"
            "匹配入账保留，入账按当前费用类型过滤且反向越级被拦截"
        )
    finally:
        connection.rollback()
        connection.close()


if __name__ == "__main__":
    main()
