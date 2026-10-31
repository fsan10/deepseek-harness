from __future__ import annotations

import os
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from openpyxl import load_workbook


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from apps.fund_split_adjust.database import ConflictError, Database, RealDictCursor


SOURCE_WORKBOOK = PROJECT_ROOT / "data" / "银行" / "看板数据.xlsx"


def make_variants(directory: Path) -> tuple[Path, Path]:
    marker = f"批次回测-{uuid.uuid4().hex}"
    base_path = directory / "base.xlsx"
    changed_path = directory / "changed.xlsx"

    workbook = load_workbook(SOURCE_WORKBOOK)
    workbook.properties.subject = marker
    workbook.save(base_path)
    workbook.close()

    workbook = load_workbook(base_path)
    source_sheet = workbook["原数据"] if "原数据" in workbook.sheetnames else workbook[workbook.sheetnames[0]]
    headers = {str(cell.value).strip(): cell.column for cell in source_sheet[1] if cell.value not in (None, "")}
    summary_column = headers["摘要"]
    previous_summary = source_sheet.cell(2, summary_column).value or ""
    source_sheet.cell(2, summary_column).value = f"{previous_summary}{marker}"
    workbook.save(changed_path)
    workbook.close()
    return base_path, changed_path


def main() -> None:
    if not SOURCE_WORKBOOK.is_file():
        raise AssertionError(f"找不到回测文件：{SOURCE_WORKBOOK}")

    with tempfile.TemporaryDirectory(prefix="fund_batch_lifecycle_") as temp_name:
        temp_dir = Path(temp_name)
        base_path, changed_path = make_variants(temp_dir)
        database = Database(
            host=os.getenv("PGHOST", "192.168.77.111"),
            port=int(os.getenv("PGPORT", "5432")),
            dbname=os.getenv("PGDATABASE", "mock_coffice"),
            user=os.getenv("PGUSER", "postgres"),
            password=os.getenv("PGPASSWORD"),
            upload_dir=temp_dir / "uploads",
        )
        connection = database.connect()
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)

            @contextmanager
            def shared_transaction():
                yield cursor

            database.transaction = shared_transaction  # type: ignore[method-assign]

            # 验证提交只作用于传入的单个 batch_id。
            cursor.execute(
                """
                SELECT record.batch_id
                FROM fund.import_record record
                WHERE NOT EXISTS(
                  SELECT 1 FROM dwd.dwd_statement_split invalid
                  WHERE invalid.batch_id=record.batch_id
                    AND (invalid.expense_type_id IS NULL OR invalid.account_entry_id IS NULL)
                )
                AND ABS((
                  SELECT COALESCE(SUM(adjusted_diff),0)
                  FROM dwd.dwd_statement_split total WHERE total.batch_id=record.batch_id
                ))<=0.01
                ORDER BY record.created_at DESC
                LIMIT 1
                FOR UPDATE
                """
            )
            submit_target = cursor.fetchone()
            if not submit_target:
                raise AssertionError("没有可用于提交范围验证的已平衡批次")
            cursor.execute("SELECT batch_id,is_submitted FROM fund.import_record ORDER BY batch_id FOR UPDATE")
            before_states = {row["batch_id"]: row["is_submitted"] for row in cursor.fetchall()}
            cursor.execute(
                "UPDATE fund.import_record SET is_submitted=FALSE,submitted_at=NULL WHERE batch_id=%s",
                (submit_target["batch_id"],),
            )
            database.submit(submit_target["batch_id"], "批次生命周期回测", "127.0.0.1")
            cursor.execute("SELECT batch_id,is_submitted FROM fund.import_record ORDER BY batch_id")
            after_states = {row["batch_id"]: row["is_submitted"] for row in cursor.fetchall()}
            assert after_states[submit_target["batch_id"]] is True
            for batch_id, submitted in before_states.items():
                if batch_id != submit_target["batch_id"]:
                    assert after_states[batch_id] is submitted, f"提交误伤及其他批次：{batch_id}"

            # 验证首次导入、完全相同文件拦截、修改文件后全量新建批次。
            first = database.import_workbook(base_path, original_name="回测银行流水.xlsx", operator="批次生命周期回测")
            try:
                database.import_workbook(base_path, original_name="回测银行流水.xlsx", operator="批次生命周期回测")
            except ConflictError as error:
                assert first["batch_id"] in str(error)
            else:
                raise AssertionError("完全相同文件应被重复导入校验拦截")

            cursor.execute(
                "SELECT summary FROM ods.ods_bank_statement WHERE batch_id=%s AND original_row_order=1",
                (first["batch_id"],),
            )
            first_summary = cursor.fetchone()["summary"]
            changed = database.import_workbook(
                changed_path, original_name="回测银行流水.xlsx", operator="批次生命周期回测"
            )
            assert changed["batch_id"] != first["batch_id"]
            assert changed["record_count"] == first["record_count"] > 1
            assert changed["dwd_record_count"] == first["dwd_record_count"]

            cursor.execute(
                "SELECT COUNT(*) AS row_count,MIN(summary) FILTER (WHERE original_row_order=1) AS first_summary "
                "FROM ods.ods_bank_statement WHERE batch_id=%s",
                (first["batch_id"],),
            )
            original_snapshot = cursor.fetchone()
            assert original_snapshot["row_count"] == first["record_count"]
            assert original_snapshot["first_summary"] == first_summary

            cursor.execute(
                "SELECT is_submitted FROM fund.import_record WHERE batch_id=%s",
                (changed["batch_id"],),
            )
            assert cursor.fetchone()["is_submitted"] is False
            cursor.execute(
                "SELECT summary FROM ods.ods_bank_statement WHERE batch_id=%s AND original_row_order=1",
                (changed["batch_id"],),
            )
            assert cursor.fetchone()["summary"] != first_summary

            print(
                "批次生命周期回测通过：单批次提交、其他批次隔离、重复文件拦截、"
                "变更文件全量新建批次且不覆盖旧批次、新批次默认未提交"
            )
        finally:
            connection.rollback()
            connection.close()


if __name__ == "__main__":
    main()
