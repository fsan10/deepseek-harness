from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from apps.fund_split_adjust.database import Database


def main() -> None:
    database = Database(
        host=os.getenv("PGHOST", "192.168.77.111"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "mock_coffice"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD"),
        upload_dir=Path("apps/fund_split_adjust/uploads"),
    )
    with database.transaction() as cursor:
        cursor.execute(
            """
            SELECT record.batch_id,record.record_count,record.dwd_record_count,
                   (SELECT COUNT(*) FROM ods.ods_bank_statement ods WHERE ods.batch_id=record.batch_id) AS ods_rows,
                   (SELECT COUNT(*) FROM dwd.dwd_statement_split split WHERE split.batch_id=record.batch_id) AS dwd_rows,
                   (SELECT COUNT(*) FROM dwd.dwd_statement_split split WHERE split.batch_id=record.batch_id AND split.is_adjusted) AS adjusted_rows,
                   (SELECT COALESCE(SUM(adjusted_diff),0) FROM dwd.dwd_statement_split split WHERE split.batch_id=record.batch_id) AS adjustment_balance,
                   (SELECT COUNT(*) FROM (SELECT ods_id FROM dwd.dwd_statement_split split WHERE split.batch_id=record.batch_id GROUP BY ods_id HAVING COUNT(*)>1) grouped) AS split_parents,
                   (SELECT COUNT(*) FROM dwd.dwd_statement_split split WHERE split.batch_id=record.batch_id AND (expense_type_id IS NULL OR account_entry_id IS NULL)) AS unassigned_rows
            FROM fund.import_record record
            WHERE record.file_name='看板数据.xlsx' AND record.status='success'
            ORDER BY record.created_at DESC LIMIT 1
            """
        )
        result = dict(cursor.fetchone())
        assert result["record_count"] == result["ods_rows"] == 58, result
        assert result["dwd_record_count"] == 63, result  # 导入完成时的DWD快照数
        assert result["dwd_rows"] >= result["ods_rows"], result  # 拆分/取消拆分后当前行数可变
        assert result["adjustment_balance"] is not None, result  # 编辑中允许存在待调配差额
        assert result["unassigned_rows"] == 0, result

        cursor.execute(
            """
            SELECT COUNT(*) AS bad_groups FROM (
              SELECT ods.id
              FROM ods.ods_bank_statement ods
              JOIN dwd.dwd_statement_split split ON split.ods_id=ods.id
              WHERE ods.batch_id=%s
              GROUP BY ods.id,ods.debit_amount,ods.credit_amount
              HAVING ABS(SUM(split.split_amount)-COALESCE(ABS(ods.debit_amount),ABS(ods.credit_amount)))>0.01
            ) bad
            """,
            (result["batch_id"],),
        )
        assert cursor.fetchone()["bad_groups"] == 0

        cursor.execute(
            """
            WITH targets(schema_name,table_name) AS (
              VALUES ('ods','ods_bank_statement'),('dwd','dwd_statement_split'),
                     ('dim','dim_expense_type'),('dim','dim_account_entry'),
                     ('dim','dim_account_entry_expense_type'),('fund','import_record'),('fund','operation_log')
            )
            SELECT COUNT(*) AS missing_comments
            FROM targets
            JOIN pg_namespace namespace ON namespace.nspname=targets.schema_name
            JOIN pg_class class ON class.relnamespace=namespace.oid AND class.relname=targets.table_name
            JOIN pg_attribute attribute ON attribute.attrelid=class.oid AND attribute.attnum>0 AND NOT attribute.attisdropped
            LEFT JOIN pg_description description ON description.objoid=class.oid AND description.objsubid=attribute.attnum
            WHERE description.description IS NULL OR description.description=''
            """
        )
        assert cursor.fetchone()["missing_comments"] == 0
    print(result)
    print("数据库验收通过：行数、拆分金额完整性、分类完整性和字段注释均符合预期。")


if __name__ == "__main__":
    main()
