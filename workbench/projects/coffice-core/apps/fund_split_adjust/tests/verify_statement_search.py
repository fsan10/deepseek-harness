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
        upload_dir=PROJECT_ROOT / "apps" / "fund_split_adjust" / "uploads",
    )
    with database.transaction() as cursor:
        cursor.execute(
            "SELECT batch_id FROM fund.import_record WHERE status='success' ORDER BY created_at DESC LIMIT 1"
        )
        record = cursor.fetchone()
    if not record:
        raise AssertionError("没有可用于搜索测试的成功导入批次")

    batch_id = record["batch_id"]
    statement = database.statement(batch_id, {"page_size": "200"})
    rows = [row for parent in statement["rows"] for row in parent["split_rows"]]

    def first(field: str):
        return next(row for row in rows if row.get(field) not in (None, ""))

    debit = next(row for row in rows if row.get("debit_amount") not in (None, 0))
    credit = next(row for row in rows if row.get("credit_amount") not in (None, 0))
    cases = {
        "交易时间": (first("transaction_time"), str(first("transaction_time")["transaction_time"])[:5]),
        "交易日": (first("transaction_date"), str(first("transaction_date")["transaction_date"])[5:]),
        "交易类型": (first("transaction_type"), str(first("transaction_type")["transaction_type"])[:4]),
        "账号名称": (first("account_name"), str(first("account_name")["account_name"])[:4]),
        "借方金额": (debit, str(debit["debit_amount"])),
        "贷方金额": (credit, str(credit["credit_amount"])),
        "余额": (first("balance"), str(first("balance")["balance"])),
        "费用类型": (first("expense_type_name"), str(first("expense_type_name")["expense_type_name"])[:4]),
        "入账": (first("account_entry_name"), str(first("account_entry_name")["account_entry_name"])[:4]),
        "摘要": (first("summary"), str(first("summary")["summary"])[:5]),
    }
    for label, (expected, keyword) in cases.items():
        result = database.statement(batch_id, {"page_size": "200", "keyword": keyword})
        matched_ids = {parent["ods_id"] for parent in result["rows"]}
        if expected["ods_id"] not in matched_ids:
            raise AssertionError(f"{label}模糊搜索失败：{keyword!r}")
    print("主编辑表统一搜索测试通过：交易时间、交易日、交易类型、账号名称、借贷金额、余额、费用类型、入账、摘要")


if __name__ == "__main__":
    main()
