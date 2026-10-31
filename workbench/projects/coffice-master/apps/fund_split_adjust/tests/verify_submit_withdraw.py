from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from apps.fund_split_adjust.database import ConflictError, Database, RealDictCursor


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
            SELECT record.batch_id,split.id AS split_id,split.remark
            FROM fund.import_record record
            JOIN dwd.dwd_statement_split split ON split.batch_id=record.batch_id
            WHERE NOT EXISTS(
              SELECT 1 FROM dwd.dwd_statement_split invalid
              WHERE invalid.batch_id=record.batch_id
                AND (invalid.expense_type_id IS NULL OR invalid.account_entry_id IS NULL)
            )
            AND ABS((SELECT COALESCE(SUM(adjusted_diff),0) FROM dwd.dwd_statement_split total WHERE total.batch_id=record.batch_id))<=0.01
            ORDER BY record.created_at DESC,split.id LIMIT 1
            FOR UPDATE OF record,split
            """
        )
        target = cursor.fetchone()
        if not target:
            raise AssertionError("没有满足提交校验的测试批次")
        cursor.execute(
            "UPDATE fund.import_record SET is_submitted=FALSE,submitted_at=NULL WHERE batch_id=%s",
            (target["batch_id"],),
        )

        @contextmanager
        def shared_transaction():
            yield cursor

        database.transaction = shared_transaction  # type: ignore[method-assign]
        database.submit(target["batch_id"], "撤回回测用户", "127.0.0.1")
        cursor.execute(
            "SELECT is_submitted,submitted_at FROM fund.import_record WHERE batch_id=%s",
            (target["batch_id"],),
        )
        submitted = cursor.fetchone()
        assert submitted["is_submitted"] is True
        assert submitted["submitted_at"] is not None

        try:
            database.update_summary(
                target["batch_id"], target["split_id"], target["remark"], "撤回回测用户", "127.0.0.1"
            )
        except ConflictError as error:
            assert "已提交" in str(error)
        else:
            raise AssertionError("提交后应禁止修改")

        try:
            database.withdraw_submit(target["batch_id"], "", "撤回回测用户", "127.0.0.1")
        except ValueError as error:
            assert "撤回原因" in str(error)
        else:
            raise AssertionError("空撤回原因应被拒绝")

        reason = "回测发现费用类型分配错误，需要重新编辑"
        database.withdraw_submit(target["batch_id"], reason, "撤回回测用户", "127.0.0.1")
        cursor.execute(
            "SELECT is_submitted,submitted_at FROM fund.import_record WHERE batch_id=%s",
            (target["batch_id"],),
        )
        withdrawn = cursor.fetchone()
        assert withdrawn["is_submitted"] is False
        assert withdrawn["submitted_at"] is None

        database.update_summary(
            target["batch_id"], target["split_id"], target["remark"], "撤回回测用户", "127.0.0.1"
        )
        cursor.execute(
            """
            SELECT change_detail->>'reason' AS reason
            FROM fund.operation_log
            WHERE operation_type='withdraw_submit' AND target_description=%s
            ORDER BY id DESC LIMIT 1
            """,
            (f"撤回批次{target['batch_id']}",),
        )
        log = cursor.fetchone()
        assert log and log["reason"] == reason

        database.submit(target["batch_id"], "撤回回测用户", "127.0.0.1")
        cursor.execute("SELECT is_submitted FROM fund.import_record WHERE batch_id=%s", (target["batch_id"],))
        assert cursor.fetchone()["is_submitted"] is True
        print("提交撤回完整回测通过：提交锁定、原因校验、撤回解锁、日志记录及重新提交")
    finally:
        connection.rollback()
        connection.close()


if __name__ == "__main__":
    main()
