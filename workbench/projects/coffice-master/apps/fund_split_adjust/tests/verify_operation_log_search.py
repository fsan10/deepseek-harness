from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from apps.fund_split_adjust.database import Database, OPERATION_TYPE_LABELS, RealDictCursor


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
            INSERT INTO fund.operation_log
              (log_no,operation_type,operator,target_type,target_id,target_description,
               change_detail,change_amount,ip_address,created_at)
            VALUES
              ('TESTSEARCH001','child_adjust','日志测试人','statement',987654,'流水测试对象',
               '{}'::jsonb,1234.56,'10.99.88.77','2026-07-21 09:08:07+08')
            RETURNING id
            """
        )
        log_id = cursor.fetchone()["id"]

        @contextmanager
        def shared_transaction():
            yield cursor

        database.transaction = shared_transaction  # type: ignore[method-assign]
        cases = {
            "日志编号": "TESTSEARCH001",
            "操作时间": "2026-07-21 09:08",
            "操作人": "日志测试",
            "操作类型": "子项调账",
            "操作对象": "测试对象",
            "变更金额": "1,234.56",
            "IP地址": "10.99.88",
        }
        for label, keyword in cases.items():
            result = database.operation_logs({"page_size": "200", "keyword": keyword})
            if log_id not in {row["id"] for row in result["items"]}:
                raise AssertionError(f"{label}模糊搜索失败：{keyword!r}")

        filtered = database.operation_logs(
            {"page_size": "200", "operation_type": "child_adjust", "operator": "日志测试人"}
        )
        assert log_id in {row["id"] for row in filtered["items"]}
        assert {item["value"] for item in filtered["operation_types"]}.issuperset(OPERATION_TYPE_LABELS)
        assert "日志测试人" in filtered["operators"]
        print("操作日志筛选测试通过：完整操作类型、操作人下拉及七类字段模糊搜索")
    finally:
        connection.rollback()
        connection.close()


if __name__ == "__main__":
    main()
