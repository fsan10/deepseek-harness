from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

VENDOR_DIR = Path(__file__).resolve().parent / ".vendor"
if VENDOR_DIR.is_dir():
    sys.path.insert(0, str(VENDOR_DIR))

try:
    import psycopg2
    from psycopg2.extras import Json, RealDictCursor
except ImportError:  # The domain tests intentionally run without a database driver.
    psycopg2 = None
    Json = RealDictCursor = None

from .domain import CENT, allocate_adjustment_diffs, allocate_split_amounts, money, parse_workbook


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_FILES = [
    PROJECT_ROOT / "sql/bank/ods/177_ods_bank_statement_postgres.sql",
    PROJECT_ROOT / "sql/dim/178_dim_bank_fund_classification_postgres.sql",
    PROJECT_ROOT / "sql/bank/fund_split/179_dwd_bank_statement_split_postgres.sql",
    PROJECT_ROOT / "sql/common/180_fund_split_operational_tables_postgres.sql",
    PROJECT_ROOT / "sql/dim/181_seed_bank_fund_classification_postgres.sql",
    PROJECT_ROOT / "sql/bank/fund_split/182_extend_statement_detail_editable_summary_postgres.sql",
]

OPERATION_TYPE_LABELS = {
    "import": "导入",
    "split": "拆分",
    "cancel_split": "取消拆分",
    "adjust": "母行调账",
    "child_adjust": "子项调账",
    "restore": "金额复原",
    "one_click_allocate": "一键调配",
    "batch_assign": "批量修改",
    "summary": "摘要修改",
    "remark": "摘要修改（历史）",
    "submit": "提交",
    "withdraw_submit": "撤回提交",
    "type_create": "新增费用类型",
    "type_update": "编辑费用类型",
    "type_toggle": "启停费用类型",
    "type_delete": "删除费用类型",
    "account_create": "新增入账",
    "account_update": "编辑入账",
    "account_toggle": "启停入账",
    "account_delete": "删除入账",
}


class NotFoundError(ValueError):
    pass


class ConflictError(ValueError):
    pass


def row_dict(row) -> dict[str, Any]:
    return dict(row) if row is not None else {}


class Database:
    def __init__(self, *, host: str, port: int, dbname: str, user: str, password: str | None, upload_dir: Path):
        self.connect_kwargs = {"host": host, "port": port, "dbname": dbname, "user": user, "password": password}
        self.upload_dir = upload_dir
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.bank_refresh_enqueuer = None

    def connect(self):
        if psycopg2 is None:
            raise RuntimeError("缺少依赖psycopg2-binary，请先安装requirements.txt")
        return psycopg2.connect(**self.connect_kwargs)

    @contextmanager
    def transaction(self):
        connection = self.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> list[str]:
        applied = []
        with self.transaction() as cursor:
            for path in SQL_FILES:
                cursor.execute(path.read_text(encoding="utf-8"))
                applied.append(str(path.relative_to(PROJECT_ROOT)))
        return applied

    def health(self) -> dict[str, Any]:
        with self.transaction() as cursor:
            cursor.execute(
                """
                SELECT current_database() AS database_name,
                       to_regclass('ods.ods_bank_statement') IS NOT NULL AS ods_ready,
                       to_regclass('dwd.dwd_statement_split') IS NOT NULL AS dwd_ready,
                       to_regclass('fund.import_record') IS NOT NULL AS operation_ready
                """
            )
            result = row_dict(cursor.fetchone())
            if all(result.get(key) for key in ("ods_ready", "dwd_ready", "operation_ready")):
                cursor.execute(
                    """
                    SELECT (SELECT COUNT(*) FROM fund.import_record WHERE status='success') AS import_batches,
                           (SELECT COUNT(*) FROM ods.ods_bank_statement) AS ods_rows,
                           (SELECT COUNT(*) FROM dwd.dwd_statement_split) AS dwd_rows
                    """
                )
                result.update(row_dict(cursor.fetchone()))
            return result

    @staticmethod
    def _next_code(cursor, table: str, prefix: str) -> str:
        cursor.execute(f"SELECT COALESCE(MAX(SUBSTRING(code FROM '[0-9]+')::INT), 0) + 1 AS seq FROM {table}")
        return f"{prefix}{int(cursor.fetchone()['seq']):03d}"

    @staticmethod
    def _next_batch_id(cursor) -> str:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('fund.import_record.batch_id'))")
        prefix = datetime.now().strftime("IMP%Y%m%d")
        cursor.execute("SELECT COALESCE(MAX(RIGHT(batch_id, 3)::INT), 0) + 1 AS seq FROM fund.import_record WHERE batch_id LIKE %s", (prefix + "%",))
        return f"{prefix}{int(cursor.fetchone()['seq']):03d}"

    @staticmethod
    def _write_log(
        cursor,
        operation_type: str,
        operator: str,
        target_type: str,
        target_id: int | None,
        description: str,
        detail: dict | None,
        amount: Decimal | None,
        ip_address: str | None,
    ) -> None:
        cursor.execute("SAVEPOINT fund_log_savepoint")
        try:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('fund.operation_log.log_no'))")
            cursor.execute("SELECT COALESCE(MAX(SUBSTRING(log_no FROM '[0-9]+')::INT), 0) + 1 AS seq FROM fund.operation_log")
            log_no = f"LOG{int(cursor.fetchone()['seq']):06d}"
            cursor.execute(
                """
                INSERT INTO fund.operation_log
                    (log_no, operation_type, operator, target_type, target_id, target_description,
                     change_detail, change_amount, ip_address)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (log_no, operation_type, operator, target_type, target_id, description, Json(detail) if detail else None, amount, ip_address),
            )
            cursor.execute("RELEASE SAVEPOINT fund_log_savepoint")
        except Exception:
            cursor.execute("ROLLBACK TO SAVEPOINT fund_log_savepoint")
            cursor.execute("RELEASE SAVEPOINT fund_log_savepoint")

    @staticmethod
    def _ensure_editable(cursor, batch_id: str) -> None:
        cursor.execute("SELECT is_submitted FROM fund.import_record WHERE batch_id=%s FOR UPDATE", (batch_id,))
        row = cursor.fetchone()
        if not row:
            raise NotFoundError("导入批次不存在")
        if row["is_submitted"]:
            raise ConflictError("该批次已提交，不能继续修改")

    @staticmethod
    def _validate_pair(cursor, expense_type_id: int | None, account_entry_id: int | None) -> None:
        if account_entry_id is None:
            return
        if expense_type_id is None:
            raise ValueError("请先选择费用类型，再选择对应的入账科目")
        cursor.execute(
            """
            SELECT 1 FROM dim.dim_account_entry_expense_type
            WHERE expense_type_id=%s AND account_entry_id=%s
            """,
            (expense_type_id, account_entry_id),
        )
        if not cursor.fetchone():
            raise ValueError("所选入账科目不允许归属于该费用类型")

    def import_workbook(self, path: str | Path, *, original_name: str | None = None, operator: str = "系统", ip_address: str | None = None) -> dict:
        source_path = Path(path)
        if source_path.suffix.lower() != ".xlsx":
            raise ValueError("仅支持.xlsx格式的银行流水文件")
        parsed = parse_workbook(source_path)
        file_bytes = source_path.read_bytes()
        file_sha = hashlib.sha256(file_bytes).hexdigest()
        safe_name = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", original_name or source_path.name)
        stored_name = f"{file_sha[:16]}_{safe_name}"
        stored_path = self.upload_dir / stored_name
        if not stored_path.exists():
            shutil.copy2(source_path, stored_path)

        with self.transaction() as cursor:
            cursor.execute("SELECT batch_id FROM fund.import_record WHERE file_sha256=%s AND status='success'", (file_sha,))
            duplicate = cursor.fetchone()
            if duplicate:
                raise ConflictError(f"该文件已成功导入，批次号：{duplicate['batch_id']}")
            batch_id = self._next_batch_id(cursor)
            cursor.execute(
                """
                INSERT INTO fund.import_record
                  (batch_id,file_name,file_size,file_path,file_sha256,record_count,dwd_record_count,
                   total_debit,total_credit,date_from,date_to,status,operator,ip_address)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'processing',%s,%s)
                RETURNING id
                """,
                (
                    batch_id,
                    original_name or source_path.name,
                    len(file_bytes),
                    stored_name,
                    file_sha,
                    len(parsed.source_rows),
                    len(parsed.split_specs),
                    parsed.total_debit,
                    parsed.total_credit,
                    parsed.date_from,
                    parsed.date_to,
                    operator,
                    ip_address,
                ),
            )
            import_id = cursor.fetchone()["id"]

            expense_ids: dict[str, int] = {}
            for sort_order, name in enumerate(parsed.expense_types, start=1):
                cursor.execute("SELECT id FROM dim.dim_expense_type WHERE name=%s", (name,))
                row = cursor.fetchone()
                if row:
                    expense_ids[name] = row["id"]
                else:
                    code = self._next_code(cursor, "dim.dim_expense_type", "EXP")
                    cursor.execute(
                        "INSERT INTO dim.dim_expense_type(code,name,sort_order) VALUES(%s,%s,%s) RETURNING id",
                        (code, name, sort_order),
                    )
                    expense_ids[name] = cursor.fetchone()["id"]

            account_ids: dict[str, int] = {}
            for sort_order, account_name in enumerate(sorted({pair[0] for pair in parsed.account_pairs}), start=1):
                cursor.execute("SELECT id FROM dim.dim_account_entry WHERE name=%s", (account_name,))
                row = cursor.fetchone()
                if row:
                    account_ids[account_name] = row["id"]
                else:
                    code = self._next_code(cursor, "dim.dim_account_entry", "ACC")
                    cursor.execute(
                        "INSERT INTO dim.dim_account_entry(code,name,sort_order) VALUES(%s,%s,%s) RETURNING id",
                        (code, account_name, sort_order),
                    )
                    account_ids[account_name] = cursor.fetchone()["id"]
            for account_name, expense_name in parsed.account_pairs:
                cursor.execute(
                    """
                    INSERT INTO dim.dim_account_entry_expense_type(account_entry_id,expense_type_id,is_default)
                    VALUES(%s,%s,NOT EXISTS(SELECT 1 FROM dim.dim_account_entry_expense_type WHERE account_entry_id=%s))
                    ON CONFLICT(account_entry_id,expense_type_id) DO NOTHING
                    """,
                    (account_ids[account_name], expense_ids[expense_name], account_ids[account_name]),
                )

            ods_ids: dict[int, int] = {}
            for source in parsed.source_rows:
                cursor.execute(
                    """
                    INSERT INTO ods.ods_bank_statement
                      (batch_id,original_row_order,account_no,account_name,currency,transaction_date,
                       transaction_time,value_date,transaction_type,debit_amount,credit_amount,balance,
                       summary,transaction_no,raw_data)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                    """,
                    (
                        batch_id, source.row_order, source.account_no, source.account_name, source.currency,
                        source.transaction_date, source.transaction_time, source.value_date, source.transaction_type,
                        source.debit_amount, source.credit_amount, source.balance, source.summary, source.transaction_no,
                        Json(source.raw_data),
                    ),
                )
                ods_ids[source.row_order] = cursor.fetchone()["id"]

            for split in parsed.split_specs:
                cursor.execute(
                    """
                    INSERT INTO dwd.dwd_statement_split
                      (ods_id,batch_id,split_index,split_amount,expense_type_id,account_entry_id,
                       remark,is_adjusted,original_amount,adjusted_diff)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        ods_ids[split.source_row_order], batch_id, split.split_index, split.split_amount,
                        expense_ids.get(split.expense_type_name), account_ids.get(split.account_entry_name),
                        split.remark, split.is_adjusted, split.original_amount, split.adjusted_diff,
                    ),
                )
            cursor.execute("UPDATE fund.import_record SET status='success' WHERE id=%s", (import_id,))
            self._write_log(
                cursor, "import", operator, "import_record", import_id, original_name or source_path.name,
                {
                    "batch_id": batch_id,
                    "source_sheet": parsed.source_sheet,
                    "organized_sheet": parsed.organized_sheet,
                    "ods_rows": len(parsed.source_rows),
                    "dwd_rows": len(parsed.split_specs),
                    "adjustment_balance": str(parsed.adjustment_balance),
                },
                parsed.total_debit + parsed.total_credit,
                ip_address,
            )
        return {
            "batch_id": batch_id,
            "record_count": len(parsed.source_rows),
            "dwd_record_count": len(parsed.split_specs),
            "total_debit": parsed.total_debit,
            "total_credit": parsed.total_credit,
            "date_from": parsed.date_from,
            "date_to": parsed.date_to,
            "status": "success",
            "organized_sheet_imported": parsed.organized_sheet is not None,
            "adjustment_balance": parsed.adjustment_balance,
        }

    def list_imports(self, *, page: int = 1, page_size: int = 20, date_from: str | None = None, date_to: str | None = None, keyword: str | None = None, status: str | None = None) -> dict:
        filters, params = [], []
        if date_from:
            filters.append("created_at::date >= %s")
            params.append(date_from)
        if date_to:
            filters.append("created_at::date <= %s")
            params.append(date_to)
        if keyword:
            filters.append("(batch_id ILIKE %s OR file_name ILIKE %s OR operator ILIKE %s)")
            pattern = f"%{keyword.strip()}%"
            params.extend([pattern, pattern, pattern])
        if status:
            filters.append("status=%s")
            params.append(status)
        where = "WHERE " + " AND ".join(filters) if filters else ""
        with self.transaction() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM fund.import_record {where}", params)
            total = cursor.fetchone()["total"]
            cursor.execute(
                f"""
                SELECT id,batch_id,file_name,file_size,record_count,dwd_record_count,total_debit,total_credit,
                       date_from,date_to,status,error_message,operator,ip_address,is_submitted,submitted_at,created_at
                FROM fund.import_record {where}
                ORDER BY created_at DESC LIMIT %s OFFSET %s
                """,
                params + [page_size, (page - 1) * page_size],
            )
            return {"items": [row_dict(row) for row in cursor.fetchall()], "pagination": {"page": page, "page_size": page_size, "total": total}}

    def import_file_path(self, batch_id: str) -> tuple[Path, str]:
        with self.transaction() as cursor:
            cursor.execute("SELECT file_path,file_name FROM fund.import_record WHERE batch_id=%s", (batch_id,))
            row = cursor.fetchone()
            if not row:
                raise NotFoundError("导入批次不存在")
            path = (self.upload_dir / row["file_path"]).resolve()
            if self.upload_dir.resolve() not in path.parents or not path.is_file():
                raise NotFoundError("原始导入文件不存在")
            return path, row["file_name"]

    def retry_import(self, batch_id: str, *, operator: str, ip_address: str | None) -> dict:
        with self.transaction() as cursor:
            cursor.execute("SELECT status,file_path,file_name FROM fund.import_record WHERE batch_id=%s", (batch_id,))
            row = cursor.fetchone()
            if not row:
                raise NotFoundError("导入批次不存在")
            if row["status"] != "failed":
                raise ConflictError("仅失败批次允许重新导入")
            stored_path = (self.upload_dir / row["file_path"]).resolve()
            if self.upload_dir.resolve() not in stored_path.parents or not stored_path.is_file():
                raise NotFoundError("失败批次的原始文件不存在")
            original_name = row["file_name"]
        return self.import_workbook(stored_path, original_name=original_name, operator=operator, ip_address=ip_address)

    def statement(self, batch_id: str, query: dict[str, str]) -> dict:
        page = max(1, int(query.get("page", 1)))
        page_size = min(200, max(1, int(query.get("page_size", 50))))
        filters = ["ods.batch_id=%s"]
        params: list[Any] = [batch_id]
        for key, column in (("date_from", "ods.transaction_date >="), ("date_to", "ods.transaction_date <=")):
            if query.get(key):
                filters.append(f"{column} %s")
                params.append(query[key])
        if query.get("transaction_type"):
            filters.append("ods.transaction_type=%s")
            params.append(query["transaction_type"])
        if query.get("expense_type_id"):
            expense_filter = query["expense_type_id"].strip()
            if expense_filter == "unassigned":
                filters.append(
                    "EXISTS(SELECT 1 FROM dwd.dwd_statement_split expense_split WHERE expense_split.ods_id=ods.id AND expense_split.expense_type_id IS NULL)"
                )
            else:
                try:
                    expense_type_id = int(expense_filter)
                except ValueError as exc:
                    raise ValueError("费用类型筛选参数无效") from exc
                filters.append(
                    "EXISTS(SELECT 1 FROM dwd.dwd_statement_split expense_split WHERE expense_split.ods_id=ods.id AND expense_split.expense_type_id=%s)"
                )
                params.append(expense_type_id)
        if query.get("account_name"):
            filters.append("ods.account_name ILIKE %s")
            params.append(f"%{query['account_name'].strip()}%")
        if query.get("keyword"):
            keyword = query["keyword"].strip()
            pattern = f"%{keyword}%"
            numeric_pattern = f"%{keyword.replace(',', '')}%"
            filters.append(
                """
                (
                  CONCAT_WS(' ',ods.transaction_time::text,ods.transaction_date::text,ods.transaction_type,
                            ods.account_name,ods.summary) ILIKE %s
                  OR CONCAT_WS(' ',ods.debit_amount::text,ods.credit_amount::text,ods.balance::text) ILIKE %s
                  OR EXISTS(
                    SELECT 1
                    FROM dwd.dwd_statement_split editable
                    LEFT JOIN dim.dim_expense_type expense ON expense.id=editable.expense_type_id
                    LEFT JOIN dim.dim_account_entry account_entry ON account_entry.id=editable.account_entry_id
                    WHERE editable.ods_id=ods.id
                      AND CONCAT_WS(' ',expense.name,account_entry.name,editable.remark) ILIKE %s
                  )
                )
                """
            )
            params.extend([pattern, numeric_pattern, pattern])
        where = " AND ".join(filters)
        with self.transaction() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM ods.ods_bank_statement ods WHERE {where}", params)
            total = cursor.fetchone()["total"]
            cursor.execute(
                f"""
                SELECT COALESCE(SUM(ods.debit_amount),0) AS total_debit,
                       COALESCE(SUM(ods.credit_amount),0) AS total_credit
                FROM ods.ods_bank_statement ods WHERE {where}
                """,
                params,
            )
            summary = row_dict(cursor.fetchone())
            cursor.execute(
                """
                SELECT -COALESCE(SUM(adjusted_diff),0) AS pending_amount,
                       COALESCE(SUM(ABS(adjusted_diff)),0) AS adjusted_volume,
                       COUNT(*) FILTER (WHERE expense_type_id IS NULL OR account_entry_id IS NULL) AS unassigned_count
                FROM dwd.dwd_statement_split WHERE batch_id=%s
                """,
                (batch_id,),
            )
            summary.update(row_dict(cursor.fetchone()))
            summary.update({"total_count": total, "is_balanced": abs(summary["pending_amount"]) <= CENT})
            cursor.execute("SELECT is_submitted FROM fund.import_record WHERE batch_id=%s", (batch_id,))
            record = cursor.fetchone()
            if not record:
                raise NotFoundError("导入批次不存在")
            summary["is_submitted"] = record["is_submitted"]
            cursor.execute(
                f"""
                WITH selected AS (
                    SELECT ods.id FROM ods.ods_bank_statement ods WHERE {where}
                    ORDER BY ods.transaction_date, ods.transaction_time NULLS LAST, ods.original_row_order
                    LIMIT %s OFFSET %s
                )
                SELECT detail.* FROM dwd.v_statement_split_detail detail
                JOIN selected ON selected.id=detail.ods_id
                ORDER BY detail.transaction_date,detail.transaction_time NULLS LAST,detail.ods_id,detail.split_index
                """,
                params + [page_size, (page - 1) * page_size],
            )
            flat = [row_dict(row) for row in cursor.fetchall()]
            rows: list[dict] = []
            by_id: dict[int, dict] = {}
            for item in flat:
                parent = by_id.get(item["ods_id"])
                if parent is None:
                    parent = {"ods_id": item["ods_id"], "split_rows": [], "has_unassigned": False}
                    by_id[item["ods_id"]] = parent
                    rows.append(parent)
                parent["split_rows"].append(item)
                parent["has_unassigned"] = parent["has_unassigned"] or item["expense_type_id"] is None or item["account_entry_id"] is None
            cursor.execute(
                "SELECT DISTINCT transaction_type FROM ods.ods_bank_statement WHERE batch_id=%s AND transaction_type IS NOT NULL ORDER BY 1",
                (batch_id,),
            )
            return {
                "summary": summary,
                "rows": rows,
                "transaction_types": [row["transaction_type"] for row in cursor.fetchall()],
                "pagination": {"page": page, "page_size": page_size, "total": total},
            }

    def split(self, batch_id: str, payload: dict, operator: str, ip_address: str | None) -> dict:
        ods_id = int(payload.get("ods_id"))
        split_rows = payload.get("splits") or []
        if len(split_rows) < 2:
            raise ValueError("拆分至少需要2个子行")
        with self.transaction() as cursor:
            self._ensure_editable(cursor, batch_id)
            cursor.execute(
                "SELECT id,COALESCE(ABS(debit_amount),ABS(credit_amount)) AS amount FROM ods.ods_bank_statement WHERE id=%s AND batch_id=%s FOR UPDATE",
                (ods_id, batch_id),
            )
            source = cursor.fetchone()
            if not source:
                raise NotFoundError("流水不存在或不属于当前批次")
            amounts = allocate_split_amounts(source["amount"], [row.get("amount") for row in split_rows])
            cursor.execute(
                "SELECT adjusted_diff FROM dwd.dwd_statement_split WHERE ods_id=%s AND batch_id=%s ORDER BY split_index FOR UPDATE",
                (ods_id, batch_id),
            )
            total_adjustment = sum((row["adjusted_diff"] for row in cursor.fetchall()), Decimal("0.00")).quantize(CENT)
            adjustment_diffs = allocate_adjustment_diffs(total_adjustment, len(amounts))
            if any(amount + diff <= 0 for amount, diff in zip(amounts, adjustment_diffs)):
                raise ValueError("调账差额等分后存在金额小于或等于0的子行，请调整拆分金额")
            cursor.execute("DELETE FROM dwd.dwd_statement_split WHERE ods_id=%s", (ods_id,))
            for index, (item, amount, adjustment_diff) in enumerate(zip(split_rows, amounts, adjustment_diffs), start=1):
                expense_id = int(item["expense_type_id"]) if item.get("expense_type_id") else None
                account_id = int(item["account_entry_id"]) if item.get("account_entry_id") else None
                self._validate_pair(cursor, expense_id, account_id)
                cursor.execute(
                    """
                    INSERT INTO dwd.dwd_statement_split
                      (ods_id,batch_id,split_index,split_amount,expense_type_id,account_entry_id,remark,
                       is_adjusted,original_amount,adjusted_diff)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        ods_id, batch_id, index, amount, expense_id, account_id,
                        str(item.get("remark") or "")[:500], adjustment_diff != 0, amount, adjustment_diff,
                    ),
                )
            self._write_log(
                cursor, "split", operator, "statement", ods_id, f"流水拆分为{len(amounts)}行",
                {"amounts": [str(v) for v in amounts], "adjustment_diffs": [str(v) for v in adjustment_diffs]},
                None, ip_address,
            )
        return self.statement(batch_id, {"page_size": "200"})

    def cancel_split(self, batch_id: str, ods_id: int, operator: str, ip_address: str | None) -> dict:
        with self.transaction() as cursor:
            self._ensure_editable(cursor, batch_id)
            cursor.execute(
                """
                SELECT ods.id,COALESCE(ABS(ods.debit_amount),ABS(ods.credit_amount)) AS amount,
                       split.expense_type_id,split.account_entry_id,split.remark
                FROM ods.ods_bank_statement ods
                JOIN dwd.dwd_statement_split split ON split.ods_id=ods.id
                WHERE ods.id=%s AND ods.batch_id=%s ORDER BY split.split_index LIMIT 1 FOR UPDATE OF ods
                """,
                (ods_id, batch_id),
            )
            row = cursor.fetchone()
            if not row:
                raise NotFoundError("流水不存在")
            cursor.execute(
                "SELECT adjusted_diff FROM dwd.dwd_statement_split WHERE ods_id=%s AND batch_id=%s ORDER BY split_index FOR UPDATE",
                (ods_id, batch_id),
            )
            total_adjustment = sum((item["adjusted_diff"] for item in cursor.fetchall()), Decimal("0.00")).quantize(CENT)
            if row["amount"] + total_adjustment <= 0:
                raise ValueError("取消拆分后的调账金额必须大于0")
            cursor.execute("DELETE FROM dwd.dwd_statement_split WHERE ods_id=%s", (ods_id,))
            cursor.execute(
                """
                INSERT INTO dwd.dwd_statement_split
                  (ods_id,batch_id,split_index,split_amount,expense_type_id,account_entry_id,remark,
                   is_adjusted,original_amount,adjusted_diff)
                VALUES(%s,%s,1,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    ods_id, batch_id, row["amount"], row["expense_type_id"], row["account_entry_id"], row["remark"],
                    total_adjustment != 0, row["amount"], total_adjustment,
                ),
            )
            self._write_log(
                cursor, "cancel_split", operator, "statement", ods_id, "取消拆分并恢复单行",
                {"adjustment_diff": str(total_adjustment)}, None, ip_address,
            )
        return self.statement(batch_id, {"page_size": "200"})

    def add_split_row(self, batch_id: str, ods_id: int, operator: str, ip_address: str | None) -> dict:
        """新增子行时平分最后一行，保证数据库内任何时刻都满足金额完整性。"""
        with self.transaction() as cursor:
            self._ensure_editable(cursor, batch_id)
            cursor.execute(
                """
                SELECT * FROM dwd.dwd_statement_split
                WHERE ods_id=%s AND batch_id=%s ORDER BY split_index DESC FOR UPDATE
                """,
                (ods_id, batch_id),
            )
            rows = cursor.fetchall()
            if not rows:
                raise NotFoundError("流水不存在")
            existing = list(reversed(rows))
            last = existing[-1]
            if last["split_amount"] < Decimal("0.02"):
                raise ValueError("最后一条拆分金额不足0.02，无法继续增加子行")
            first_half = (last["split_amount"] / 2).quantize(CENT)
            second_half = (last["split_amount"] - first_half).quantize(CENT)
            total_adjustment = sum((row["adjusted_diff"] for row in existing), Decimal("0.00")).quantize(CENT)
            amounts = [row["split_amount"] for row in existing[:-1]] + [first_half, second_half]
            adjustment_diffs = allocate_adjustment_diffs(total_adjustment, len(amounts))
            if any(amount + diff <= 0 for amount, diff in zip(amounts, adjustment_diffs)):
                raise ValueError("调账差额等分后存在金额小于或等于0的子行，无法增加拆分行")
            for row, amount, adjustment_diff in zip(existing, amounts[:-1], adjustment_diffs[:-1]):
                cursor.execute(
                    """
                    UPDATE dwd.dwd_statement_split
                    SET split_amount=%s,original_amount=%s,adjusted_diff=%s,is_adjusted=(%s<>0),updated_at=NOW()
                    WHERE id=%s
                    """,
                    (amount, amount, adjustment_diff, adjustment_diff, row["id"]),
                )
            cursor.execute(
                """
                INSERT INTO dwd.dwd_statement_split
                  (ods_id,batch_id,split_index,split_amount,expense_type_id,account_entry_id,remark,
                   is_adjusted,original_amount,adjusted_diff)
                VALUES(%s,%s,%s,%s,%s,%s,'',%s,%s,%s)
                RETURNING id
                """,
                (
                    ods_id, batch_id, last["split_index"] + 1, second_half, last["expense_type_id"], last["account_entry_id"],
                    adjustment_diffs[-1] != 0, second_half, adjustment_diffs[-1],
                ),
            )
            new_id = cursor.fetchone()["id"]
            self._write_log(
                cursor, "split", operator, "statement", ods_id, "增加拆分行",
                {
                    "new_split_id": new_id, "amount": str(second_half),
                    "adjustment_diffs": [str(v) for v in adjustment_diffs],
                },
                None, ip_address,
            )
        return self.statement(batch_id, {"page_size": "200"})

    def adjust(
        self, batch_id: str, split_id: int, new_amount: Any, operator: str, ip_address: str | None,
        *, operation_type: str = "adjust", description: str = "手工调账",
    ) -> dict:
        adjusted = money(new_amount, allow_none=False)
        if adjusted <= 0:
            raise ValueError("调账后金额必须大于0")
        with self.transaction() as cursor:
            self._ensure_editable(cursor, batch_id)
            cursor.execute(
                """
                SELECT split_row.id,split_row.ods_id,split_row.original_amount,split_row.adjusted_diff,
                       (SELECT COUNT(*) FROM dwd.dwd_statement_split sibling WHERE sibling.ods_id=split_row.ods_id) AS sibling_count
                FROM dwd.dwd_statement_split split_row
                WHERE split_row.id=%s AND split_row.batch_id=%s FOR UPDATE
                """,
                (split_id, batch_id),
            )
            row = cursor.fetchone()
            if not row:
                raise NotFoundError("拆分行不存在")
            if row["sibling_count"] > 1:
                raise ConflictError("拆分子项不能直接改变母行总额，请使用子项调账")
            new_diff = (adjusted - row["original_amount"]).quantize(CENT)
            cursor.execute(
                "UPDATE dwd.dwd_statement_split SET adjusted_diff=%s,is_adjusted=(%s<>0),updated_at=NOW() WHERE id=%s",
                (new_diff, new_diff, split_id),
            )
            self._write_log(
                cursor, operation_type, operator, "split_row", split_id, description,
                {"fields": [{"field_key": "adjusted_amount", "old_value": str(row["original_amount"] + row["adjusted_diff"]), "new_value": str(adjusted)}]},
                new_diff - row["adjusted_diff"], ip_address,
            )
            cursor.execute("SELECT -COALESCE(SUM(adjusted_diff),0) AS pending FROM dwd.dwd_statement_split WHERE batch_id=%s", (batch_id,))
            pending = cursor.fetchone()["pending"]
        return {"split_id": split_id, "original_amount": row["original_amount"], "new_amount": adjusted, "diff": new_diff, "pending_amount": pending, "is_balanced": abs(pending) <= CENT}

    def adjust_child(
        self, batch_id: str, split_id: int, new_amount: Any, operator: str, ip_address: str | None,
        *, operation_type: str = "child_adjust", description: str = "子项调账，自动分配项同步补足",
    ) -> dict:
        """修改一个非自动子项，并由最后一个自动分配子项反向补足，母行总额保持不变。"""
        adjusted = money(new_amount, allow_none=False)
        if adjusted <= 0:
            raise ValueError("子项调账后金额必须大于0")
        with self.transaction() as cursor:
            self._ensure_editable(cursor, batch_id)
            cursor.execute(
                "SELECT ods_id FROM dwd.dwd_statement_split WHERE id=%s AND batch_id=%s FOR UPDATE",
                (split_id, batch_id),
            )
            target_ref = cursor.fetchone()
            if not target_ref:
                raise NotFoundError("拆分子项不存在")
            cursor.execute(
                """
                SELECT id,split_index,original_amount,adjusted_diff
                FROM dwd.dwd_statement_split
                WHERE ods_id=%s AND batch_id=%s ORDER BY split_index FOR UPDATE
                """,
                (target_ref["ods_id"], batch_id),
            )
            rows = cursor.fetchall()
            if len(rows) < 2:
                raise ConflictError("当前流水未拆分，请使用母行调账")
            target = next((row for row in rows if row["id"] == split_id), None)
            auto = rows[-1]
            if target is None:
                raise NotFoundError("拆分子项不存在")
            if target["id"] == auto["id"]:
                raise ConflictError("自动分配子项不能调账，它会根据其他子项自动变化")
            parent_amount = sum((row["original_amount"] + row["adjusted_diff"] for row in rows), Decimal("0.00")).quantize(CENT)
            fixed_amount = sum(
                (row["original_amount"] + row["adjusted_diff"] for row in rows if row["id"] not in {target["id"], auto["id"]}),
                Decimal("0.00"),
            ).quantize(CENT)
            auto_amount = (parent_amount - fixed_amount - adjusted).quantize(CENT)
            if auto_amount <= 0:
                raise ValueError(f"子项金额过大，自动分配子项至少需要保留0.01，当前最多可填写{parent_amount - fixed_amount - CENT}")
            old_target_amount = (target["original_amount"] + target["adjusted_diff"]).quantize(CENT)
            old_auto_amount = (auto["original_amount"] + auto["adjusted_diff"]).quantize(CENT)
            target_diff = (adjusted - target["original_amount"]).quantize(CENT)
            auto_diff = (auto_amount - auto["original_amount"]).quantize(CENT)
            for row_id, diff in ((target["id"], target_diff), (auto["id"], auto_diff)):
                cursor.execute(
                    """
                    UPDATE dwd.dwd_statement_split
                    SET adjusted_diff=%s,is_adjusted=(%s<>0),updated_at=NOW() WHERE id=%s
                    """,
                    (diff, diff, row_id),
                )
            self._write_log(
                cursor, operation_type, operator, "split_row", split_id, description,
                {
                    "fields": [
                        {"field_key": "child_amount", "old_value": str(old_target_amount), "new_value": str(adjusted)},
                        {"field_key": "auto_amount", "old_value": str(old_auto_amount), "new_value": str(auto_amount)},
                    ],
                    "auto_split_id": auto["id"],
                    "parent_amount": str(parent_amount),
                },
                None, ip_address,
            )
        return {
            "split_id": split_id,
            "new_amount": adjusted,
            "auto_split_id": auto["id"],
            "auto_amount": auto_amount,
            "parent_amount": parent_amount,
        }

    def adjust_parent(
        self, batch_id: str, ods_id: int, new_amount: Any, operator: str, ip_address: str | None,
        *, operation_type: str = "adjust", description: str = "母行手工调账并均分子项",
    ) -> dict:
        """调整母行总金额，并将调账后的主金额平均分配到全部子行。"""
        adjusted = money(new_amount, allow_none=False)
        if adjusted <= 0:
            raise ValueError("母行调账后金额必须大于0")
        with self.transaction() as cursor:
            self._ensure_editable(cursor, batch_id)
            cursor.execute(
                """
                SELECT id,COALESCE(ABS(debit_amount),ABS(credit_amount)) AS source_amount
                FROM ods.ods_bank_statement WHERE id=%s AND batch_id=%s FOR UPDATE
                """,
                (ods_id, batch_id),
            )
            source = cursor.fetchone()
            if not source:
                raise NotFoundError("母行不存在或不属于当前批次")
            cursor.execute(
                """
                SELECT id,original_amount,adjusted_diff
                FROM dwd.dwd_statement_split
                WHERE ods_id=%s AND batch_id=%s ORDER BY split_index FOR UPDATE
                """,
                (ods_id, batch_id),
            )
            rows = cursor.fetchall()
            if not rows:
                raise NotFoundError("母行没有可调账的拆分明细")
            old_amount = sum((row["original_amount"] + row["adjusted_diff"] for row in rows), Decimal("0.00")).quantize(CENT)
            child_amounts = allocate_split_amounts(adjusted, [None] * len(rows))
            child_changes = []
            for row, child_amount in zip(rows, child_amounts):
                child_diff = (child_amount - row["original_amount"]).quantize(CENT)
                cursor.execute(
                    """
                    UPDATE dwd.dwd_statement_split
                    SET adjusted_diff=%s,is_adjusted=(%s<>0),updated_at=NOW()
                    WHERE id=%s
                    """,
                    (child_diff, child_diff, row["id"]),
                )
                child_changes.append({"split_id": row["id"], "amount": str(child_amount)})
            self._write_log(
                cursor, operation_type, operator, "statement", ods_id, description,
                {
                    "fields": [{"field_key": "adjusted_amount", "old_value": str(old_amount), "new_value": str(adjusted)}],
                    "child_amounts": child_changes,
                },
                adjusted - old_amount, ip_address,
            )
            cursor.execute("SELECT -COALESCE(SUM(adjusted_diff),0) AS pending FROM dwd.dwd_statement_split WHERE batch_id=%s", (batch_id,))
            pending = cursor.fetchone()["pending"]
        return {
            "ods_id": ods_id,
            "source_amount": source["source_amount"],
            "new_amount": adjusted,
            "child_amounts": child_changes,
            "pending_amount": pending,
            "is_balanced": abs(pending) <= CENT,
        }

    def restore_amount(self, batch_id: str, payload: dict, operator: str, ip_address: str | None) -> dict:
        """将普通行、拆分母行或非自动子项恢复到其数据库中的原始金额基准。"""
        split_id = int(payload["split_id"]) if payload.get("split_id") not in (None, "") else None
        ods_id = int(payload["ods_id"]) if payload.get("ods_id") not in (None, "") else None
        if (split_id is None) == (ods_id is None):
            raise ValueError("复原参数必须且只能指定一个流水行或拆分母行")

        if ods_id is not None:
            with self.transaction() as cursor:
                self._ensure_editable(cursor, batch_id)
                cursor.execute(
                    """
                    SELECT COALESCE(ABS(debit_amount),ABS(credit_amount)) AS source_amount
                    FROM ods.ods_bank_statement WHERE id=%s AND batch_id=%s
                    """,
                    (ods_id, batch_id),
                )
                source = cursor.fetchone()
                if not source:
                    raise NotFoundError("母行不存在或不属于当前批次")
                original_amount = source["source_amount"]
            result = self.adjust_parent(
                batch_id, ods_id, original_amount, operator, ip_address,
                operation_type="restore", description="复原母行金额并重新均分子项",
            )
            result["restored"] = True
            return result

        with self.transaction() as cursor:
            self._ensure_editable(cursor, batch_id)
            cursor.execute(
                """
                SELECT split_row.original_amount,split_row.split_index,
                       (SELECT COUNT(*) FROM dwd.dwd_statement_split sibling
                        WHERE sibling.ods_id=split_row.ods_id AND sibling.batch_id=split_row.batch_id) AS sibling_count,
                       (SELECT MAX(sibling.split_index) FROM dwd.dwd_statement_split sibling
                        WHERE sibling.ods_id=split_row.ods_id AND sibling.batch_id=split_row.batch_id) AS max_split_index
                FROM dwd.dwd_statement_split split_row
                WHERE split_row.id=%s AND split_row.batch_id=%s
                """,
                (split_id, batch_id),
            )
            row = cursor.fetchone()
            if not row:
                raise NotFoundError("拆分行不存在")
            original_amount = row["original_amount"]
            is_child = row["sibling_count"] > 1
            if is_child and row["split_index"] == row["max_split_index"]:
                raise ConflictError("自动分配子项不能手工复原，它会跟随其他子项自动变化")

        if is_child:
            result = self.adjust_child(
                batch_id, split_id, original_amount, operator, ip_address,
                operation_type="restore", description="复原子项金额，自动分配项同步补足",
            )
        else:
            result = self.adjust(
                batch_id, split_id, original_amount, operator, ip_address,
                operation_type="restore", description="复原流水原始金额",
            )
        result["restored"] = True
        return result

    def allocate_one_click(self, batch_id: str, split_id: int, operator: str, ip_address: str | None) -> dict:
        with self.transaction() as cursor:
            self._ensure_editable(cursor, batch_id)
            cursor.execute(
                "SELECT id FROM dwd.dwd_statement_split WHERE batch_id=%s ORDER BY id FOR UPDATE",
                (batch_id,),
            )
            if not cursor.fetchall():
                raise NotFoundError("当前批次没有可调配明细")
            cursor.execute("SELECT -COALESCE(SUM(adjusted_diff),0) AS pending FROM dwd.dwd_statement_split WHERE batch_id=%s", (batch_id,))
            pending = cursor.fetchone()["pending"].quantize(CENT)
            cursor.execute("SELECT id,adjusted_diff,original_amount FROM dwd.dwd_statement_split WHERE id=%s AND batch_id=%s FOR UPDATE", (split_id, batch_id))
            target = cursor.fetchone()
            if not target:
                raise NotFoundError("目标拆分行不存在")
            if abs(pending) <= CENT:
                raise ValueError("当前待调配金额已平衡")
            new_diff = (target["adjusted_diff"] + pending).quantize(CENT)
            if target["original_amount"] + new_diff <= 0:
                raise ValueError("一键调配会使目标金额小于等于0")
            cursor.execute("UPDATE dwd.dwd_statement_split SET adjusted_diff=%s,is_adjusted=(%s<>0),updated_at=NOW() WHERE id=%s", (new_diff, new_diff, split_id))
            self._write_log(cursor, "one_click_allocate", operator, "split_row", split_id, "一键调配待分配金额", {"old_balance": str(pending), "new_diff": str(new_diff)}, pending, ip_address)
        return self.statement(batch_id, {"page_size": "200"})

    def batch_assign(self, batch_id: str, payload: dict, operator: str, ip_address: str | None) -> dict:
        split_ids = [int(value) for value in payload.get("split_ids") or []]
        field = payload.get("field")
        if not split_ids or field not in {"expense_type_id", "account_entry_id"}:
            raise ValueError("批量修改参数不完整")
        value = int(payload["value"]) if payload.get("value") not in (None, "") else None
        with self.transaction() as cursor:
            self._ensure_editable(cursor, batch_id)
            cursor.execute(
                "SELECT id,expense_type_id,account_entry_id FROM dwd.dwd_statement_split WHERE batch_id=%s AND id=ANY(%s) FOR UPDATE",
                (batch_id, split_ids),
            )
            rows = cursor.fetchall()
            if len(rows) != len(set(split_ids)):
                raise ValueError("部分选中行不存在或不属于当前批次")
            cleared_account_count = 0
            if field == "expense_type_id":
                if value is not None:
                    cursor.execute("SELECT 1 FROM dim.dim_expense_type WHERE id=%s", (value,))
                    if not cursor.fetchone():
                        raise NotFoundError("费用类型不存在")
                account_ids = [row["account_entry_id"] for row in rows if row["account_entry_id"] is not None]
                compatible_accounts: set[int] = set()
                if value is not None and account_ids:
                    cursor.execute(
                        """
                        SELECT account_entry_id
                        FROM dim.dim_account_entry_expense_type
                        WHERE expense_type_id=%s AND account_entry_id=ANY(%s)
                        """,
                        (value, account_ids),
                    )
                    compatible_accounts = {row["account_entry_id"] for row in cursor.fetchall()}
                cleared_account_count = sum(
                    1 for row in rows
                    if row["account_entry_id"] is not None and row["account_entry_id"] not in compatible_accounts
                )
                cursor.execute(
                    """
                    UPDATE dwd.dwd_statement_split AS split_row
                    SET expense_type_id=%s,
                        account_entry_id=CASE
                          WHEN %s IS NULL THEN NULL
                          WHEN split_row.account_entry_id IS NULL THEN NULL
                          WHEN EXISTS(
                            SELECT 1 FROM dim.dim_account_entry_expense_type relation
                            WHERE relation.expense_type_id=%s
                              AND relation.account_entry_id=split_row.account_entry_id
                          ) THEN split_row.account_entry_id
                          ELSE NULL
                        END,
                        updated_at=NOW()
                    WHERE split_row.batch_id=%s AND split_row.id=ANY(%s)
                    """,
                    (value, value, value, batch_id, split_ids),
                )
            else:
                for row in rows:
                    self._validate_pair(cursor, row["expense_type_id"], value)
                cursor.execute(
                    "UPDATE dwd.dwd_statement_split SET account_entry_id=%s,updated_at=NOW() WHERE batch_id=%s AND id=ANY(%s)",
                    (value, batch_id, split_ids),
                )
            self._write_log(
                cursor, "batch_assign", operator, "split_row", None, f"批量修改{len(split_ids)}行",
                {
                    "field": field,
                    "value": value,
                    "split_ids": split_ids,
                    "cleared_account_count": cleared_account_count,
                },
                None, ip_address,
            )
        return {"updated": len(split_ids), "cleared_account_count": cleared_account_count}

    def update_remark(self, batch_id: str, split_id: int, remark: str, operator: str, ip_address: str | None) -> dict:
        return self.update_summary(batch_id, split_id, remark, operator, ip_address)

    def update_summary(self, batch_id: str, split_id: int, summary: str, operator: str, ip_address: str | None) -> dict:
        with self.transaction() as cursor:
            self._ensure_editable(cursor, batch_id)
            cursor.execute("UPDATE dwd.dwd_statement_split SET remark=%s,updated_at=NOW() WHERE id=%s AND batch_id=%s RETURNING id", (summary[:500], split_id, batch_id))
            if not cursor.fetchone():
                raise NotFoundError("拆分行不存在")
            self._write_log(cursor, "summary", operator, "split_row", split_id, "修改摘要", {"summary": summary[:500]}, None, ip_address)
        return {"split_id": split_id, "summary": summary[:500]}

    def submit(self, batch_id: str, operator: str, ip_address: str | None) -> dict:
        with self.transaction() as cursor:
            self._ensure_editable(cursor, batch_id)
            cursor.execute(
                """
                SELECT -COALESCE(SUM(adjusted_diff),0) AS pending,
                       COUNT(*) FILTER(WHERE expense_type_id IS NULL OR account_entry_id IS NULL) AS unassigned
                FROM dwd.dwd_statement_split WHERE batch_id=%s
                """,
                (batch_id,),
            )
            check = cursor.fetchone()
            if abs(check["pending"]) > CENT:
                raise ValueError(f"待分配金额不为0（¥{check['pending']:.2f}），无法提交")
            if check["unassigned"]:
                raise ValueError(f"仍有{check['unassigned']}条明细未设置费用类型或入账")
            cursor.execute(
                """
                SELECT COUNT(*) AS bad_count FROM (
                    SELECT ods.id
                    FROM ods.ods_bank_statement ods
                    JOIN dwd.dwd_statement_split split ON split.ods_id=ods.id
                    WHERE ods.batch_id=%s
                    GROUP BY ods.id,ods.debit_amount,ods.credit_amount
                    HAVING ABS(SUM(split.split_amount)-COALESCE(ABS(ods.debit_amount),ABS(ods.credit_amount)))>0.01
                ) bad
                """,
                (batch_id,),
            )
            if cursor.fetchone()["bad_count"]:
                raise ValueError("存在拆分合计与ODS原金额不一致的流水")
            cursor.execute("UPDATE fund.import_record SET is_submitted=TRUE,submitted_at=NOW() WHERE batch_id=%s RETURNING id,dwd_record_count", (batch_id,))
            record = cursor.fetchone()
            self._write_log(cursor, "submit", operator, "import_record", record["id"], f"提交批次{batch_id}", {"dwd_rows": record["dwd_record_count"]}, None, ip_address)
            etl_run = self.bank_refresh_enqueuer(cursor, operator) if self.bank_refresh_enqueuer else None
        return {"batch_id": batch_id, "is_submitted": True, "dwd_record_count": record["dwd_record_count"], "etl_run": etl_run}

    def withdraw_submit(self, batch_id: str, reason: str, operator: str, ip_address: str | None) -> dict:
        normalized_reason = str(reason or "").strip()
        if not normalized_reason:
            raise ValueError("请填写撤回原因")
        if len(normalized_reason) > 500:
            raise ValueError("撤回原因不能超过500个字符")
        with self.transaction() as cursor:
            cursor.execute(
                """
                SELECT id,is_submitted,submitted_at
                FROM fund.import_record WHERE batch_id=%s FOR UPDATE
                """,
                (batch_id,),
            )
            record = cursor.fetchone()
            if not record:
                raise NotFoundError("导入批次不存在")
            if not record["is_submitted"]:
                raise ConflictError("该批次尚未提交，无需撤回")
            cursor.execute(
                "UPDATE fund.import_record SET is_submitted=FALSE,submitted_at=NULL WHERE batch_id=%s",
                (batch_id,),
            )
            self._write_log(
                cursor, "withdraw_submit", operator, "import_record", record["id"], f"撤回批次{batch_id}",
                {"reason": normalized_reason, "previous_submitted_at": record["submitted_at"].isoformat() if record["submitted_at"] else None},
                None, ip_address,
            )
        return {"batch_id": batch_id, "is_submitted": False, "reason": normalized_reason}

    def expense_types(self, *, keyword: str | None = None, active: str | None = None, page: int | None = None, page_size: int = 20) -> list[dict] | dict:
        filters, params = [], []
        if keyword:
            filters.append("expense.name ILIKE %s")
            params.append(f"%{keyword.strip()}%")
        if active in {"true", "false"}:
            filters.append("expense.is_active=%s")
            params.append(active == "true")
        where = "WHERE " + " AND ".join(filters) if filters else ""
        with self.transaction() as cursor:
            total = None
            limit_sql = ""
            final_params = params
            if page is not None:
                page = max(1, page)
                page_size = min(200, max(1, page_size))
                cursor.execute(f"SELECT COUNT(*) AS total FROM dim.dim_expense_type expense {where}", params)
                total = cursor.fetchone()["total"]
                limit_sql = "LIMIT %s OFFSET %s"
                final_params = params + [page_size, (page - 1) * page_size]
            cursor.execute(
                f"""
                SELECT expense.*,COUNT(link.account_entry_id) AS account_count
                FROM dim.dim_expense_type expense
                LEFT JOIN dim.dim_account_entry_expense_type link ON link.expense_type_id=expense.id
                {where} GROUP BY expense.id ORDER BY expense.sort_order,expense.name {limit_sql}
                """,
                final_params,
            )
            items = [row_dict(row) for row in cursor.fetchall()]
            return {"items": items, "pagination": {"page": page, "page_size": page_size, "total": total}} if page is not None else items

    def create_expense(self, payload: dict, operator: str, ip_address: str | None) -> dict:
        name = str(payload.get("name") or "").strip()
        if not name or len(name) > 100:
            raise ValueError("费用类型名称不能为空且不能超过100字")
        with self.transaction() as cursor:
            code = self._next_code(cursor, "dim.dim_expense_type", "EXP")
            try:
                cursor.execute(
                    """
                    INSERT INTO dim.dim_expense_type(code,name,description,sort_order,is_active)
                    VALUES(%s,%s,%s,COALESCE(%s,(SELECT COALESCE(MAX(sort_order),0)+1 FROM dim.dim_expense_type)),%s)
                    RETURNING *
                    """,
                    (code, name, str(payload.get("description") or "")[:500], payload.get("sort_order"), bool(payload.get("is_active", True))),
                )
            except Exception as exc:
                if getattr(exc, "pgcode", None) == "23505":
                    raise ConflictError("费用类型名称已存在") from exc
                raise
            row = row_dict(cursor.fetchone())
            self._write_log(cursor, "type_create", operator, "expense_type", row["id"], name, {"new": row}, None, ip_address)
            return row

    def update_expense(self, expense_id: int, payload: dict, operator: str, ip_address: str | None) -> dict:
        fields = {key: payload[key] for key in ("name", "description", "sort_order") if key in payload}
        if not fields:
            raise ValueError("没有可更新字段")
        assignments = ",".join(f"{key}=%s" for key in fields)
        with self.transaction() as cursor:
            cursor.execute(f"UPDATE dim.dim_expense_type SET {assignments},updated_at=NOW() WHERE id=%s RETURNING *", list(fields.values()) + [expense_id])
            row = cursor.fetchone()
            if not row:
                raise NotFoundError("费用类型不存在")
            result = row_dict(row)
            self._write_log(cursor, "type_update", operator, "expense_type", expense_id, result["name"], {"new": result}, None, ip_address)
            return result

    def toggle_expense(self, expense_id: int, operator: str, ip_address: str | None) -> dict:
        with self.transaction() as cursor:
            cursor.execute("UPDATE dim.dim_expense_type SET is_active=NOT is_active,updated_at=NOW() WHERE id=%s RETURNING *", (expense_id,))
            row = cursor.fetchone()
            if not row:
                raise NotFoundError("费用类型不存在")
            result = row_dict(row)
            self._write_log(cursor, "type_toggle", operator, "expense_type", expense_id, result["name"], {"is_active": result["is_active"]}, None, ip_address)
            return result

    def delete_expense(self, expense_id: int, operator: str, ip_address: str | None) -> dict:
        with self.transaction() as cursor:
            cursor.execute("SELECT name FROM dim.dim_expense_type WHERE id=%s FOR UPDATE", (expense_id,))
            row = cursor.fetchone()
            if not row:
                raise NotFoundError("费用类型不存在")
            cursor.execute("SELECT COUNT(*) AS count FROM dim.dim_account_entry_expense_type WHERE expense_type_id=%s", (expense_id,))
            count = cursor.fetchone()["count"]
            if count:
                raise ConflictError(f"该费用类型下有{count}个入账科目，无法删除")
            cursor.execute("SELECT COUNT(*) AS count FROM dwd.dwd_statement_split WHERE expense_type_id=%s", (expense_id,))
            if cursor.fetchone()["count"]:
                raise ConflictError("该费用类型已被流水使用，无法删除")
            cursor.execute("DELETE FROM dim.dim_expense_type WHERE id=%s", (expense_id,))
            self._write_log(cursor, "type_delete", operator, "expense_type", expense_id, row["name"], None, None, ip_address)
            return {"deleted": expense_id}

    def account_entries(self, *, keyword: str | None = None, expense_type_id: int | None = None, active: str | None = None, page: int | None = None, page_size: int = 20) -> list[dict] | dict:
        filters, params = [], []
        if keyword:
            filters.append("account.name ILIKE %s")
            params.append(f"%{keyword.strip()}%")
        if expense_type_id:
            filters.append("EXISTS(SELECT 1 FROM dim.dim_account_entry_expense_type f WHERE f.account_entry_id=account.id AND f.expense_type_id=%s)")
            params.append(expense_type_id)
        if active in {"true", "false"}:
            filters.append("account.is_active=%s")
            params.append(active == "true")
        where = "WHERE " + " AND ".join(filters) if filters else ""
        with self.transaction() as cursor:
            total = None
            limit_sql = ""
            final_params = params
            if page is not None:
                page = max(1, page)
                page_size = min(200, max(1, page_size))
                cursor.execute(f"SELECT COUNT(*) AS total FROM dim.dim_account_entry account {where}", params)
                total = cursor.fetchone()["total"]
                limit_sql = "LIMIT %s OFFSET %s"
                final_params = params + [page_size, (page - 1) * page_size]
            cursor.execute(
                f"""
                SELECT account.*,
                       COALESCE(JSONB_AGG(JSONB_BUILD_OBJECT('id',expense.id,'name',expense.name,'is_default',link.is_default)
                         ORDER BY link.is_default DESC,expense.sort_order) FILTER(WHERE expense.id IS NOT NULL),'[]'::jsonb) AS expense_types
                FROM dim.dim_account_entry account
                LEFT JOIN dim.dim_account_entry_expense_type link ON link.account_entry_id=account.id
                LEFT JOIN dim.dim_expense_type expense ON expense.id=link.expense_type_id
                {where} GROUP BY account.id ORDER BY account.sort_order,account.name {limit_sql}
                """,
                final_params,
            )
            items = [row_dict(row) for row in cursor.fetchall()]
            return {"items": items, "pagination": {"page": page, "page_size": page_size, "total": total}} if page is not None else items

    def create_account(self, payload: dict, operator: str, ip_address: str | None) -> dict:
        name = str(payload.get("name") or "").strip()
        expense_ids = [int(value) for value in payload.get("expense_type_ids") or ([payload["expense_type_id"]] if payload.get("expense_type_id") else [])]
        if not name or not expense_ids:
            raise ValueError("入账名称和至少一个费用类型不能为空")
        with self.transaction() as cursor:
            code = self._next_code(cursor, "dim.dim_account_entry", "ACC")
            try:
                cursor.execute(
                    """
                    INSERT INTO dim.dim_account_entry(code,name,description,sort_order,is_active)
                    VALUES(%s,%s,%s,COALESCE(%s,(SELECT COALESCE(MAX(sort_order),0)+1 FROM dim.dim_account_entry)),%s)
                    RETURNING *
                    """,
                    (code, name, str(payload.get("description") or "")[:500], payload.get("sort_order"), bool(payload.get("is_active", True))),
                )
            except Exception as exc:
                if getattr(exc, "pgcode", None) == "23505":
                    raise ConflictError("入账科目名称已存在") from exc
                raise
            account = row_dict(cursor.fetchone())
            for index, expense_id in enumerate(dict.fromkeys(expense_ids)):
                cursor.execute("INSERT INTO dim.dim_account_entry_expense_type(account_entry_id,expense_type_id,is_default) VALUES(%s,%s,%s)", (account["id"], expense_id, index == 0))
            self._write_log(cursor, "account_create", operator, "account_entry", account["id"], name, {"expense_type_ids": expense_ids}, None, ip_address)
        return next(row for row in self.account_entries(keyword=name) if row["id"] == account["id"])

    def update_account(self, account_id: int, payload: dict, operator: str, ip_address: str | None) -> dict:
        fields = {key: payload[key] for key in ("name", "description", "sort_order") if key in payload}
        expense_ids = payload.get("expense_type_ids")
        with self.transaction() as cursor:
            cursor.execute("SELECT id FROM dim.dim_account_entry WHERE id=%s FOR UPDATE", (account_id,))
            if not cursor.fetchone():
                raise NotFoundError("入账科目不存在")
            if fields:
                assignments = ",".join(f"{key}=%s" for key in fields)
                cursor.execute(f"UPDATE dim.dim_account_entry SET {assignments},updated_at=NOW() WHERE id=%s", list(fields.values()) + [account_id])
            if expense_ids is not None:
                normalized = list(dict.fromkeys(int(value) for value in expense_ids))
                if not normalized:
                    raise ValueError("入账科目至少需要一个费用类型")
                cursor.execute("DELETE FROM dim.dim_account_entry_expense_type WHERE account_entry_id=%s", (account_id,))
                for index, expense_id in enumerate(normalized):
                    cursor.execute("INSERT INTO dim.dim_account_entry_expense_type(account_entry_id,expense_type_id,is_default) VALUES(%s,%s,%s)", (account_id, expense_id, index == 0))
            self._write_log(cursor, "account_update", operator, "account_entry", account_id, "编辑入账科目", payload, None, ip_address)
        return next(row for row in self.account_entries() if row["id"] == account_id)

    def toggle_account(self, account_id: int, operator: str, ip_address: str | None) -> dict:
        with self.transaction() as cursor:
            cursor.execute("UPDATE dim.dim_account_entry SET is_active=NOT is_active,updated_at=NOW() WHERE id=%s RETURNING *", (account_id,))
            row = cursor.fetchone()
            if not row:
                raise NotFoundError("入账科目不存在")
            result = row_dict(row)
            self._write_log(cursor, "account_toggle", operator, "account_entry", account_id, result["name"], {"is_active": result["is_active"]}, None, ip_address)
            return result

    def delete_account(self, account_id: int, operator: str, ip_address: str | None) -> dict:
        with self.transaction() as cursor:
            cursor.execute("SELECT name FROM dim.dim_account_entry WHERE id=%s FOR UPDATE", (account_id,))
            row = cursor.fetchone()
            if not row:
                raise NotFoundError("入账科目不存在")
            cursor.execute("SELECT COUNT(*) AS count FROM dwd.dwd_statement_split WHERE account_entry_id=%s", (account_id,))
            if cursor.fetchone()["count"]:
                raise ConflictError("该入账科目已被流水使用，无法删除")
            cursor.execute("DELETE FROM dim.dim_account_entry WHERE id=%s", (account_id,))
            self._write_log(cursor, "account_delete", operator, "account_entry", account_id, row["name"], None, None, ip_address)
            return {"deleted": account_id}

    def operation_logs(self, query: dict[str, str], *, export_all: bool = False) -> dict:
        page = max(1, int(query.get("page", 1)))
        page_size = min(200, max(1, int(query.get("page_size", 20))))
        filters, params = [], []
        for key, expression in (("date_from", "created_at::date >= %s"), ("date_to", "created_at::date <= %s"), ("operation_type", "operation_type=%s")):
            if query.get(key):
                filters.append(expression)
                params.append(query[key])
        if query.get("operator"):
            selected_operators = [unquote(value.strip()) for value in query["operator"].replace("，", ",").split(",") if value.strip()]
            if selected_operators:
                encoded_operators = [quote(value, safe="") for value in selected_operators]
                filters.append("(operator=ANY(%s) OR operator=ANY(%s))")
                params.extend([selected_operators, encoded_operators])
        if query.get("keyword"):
            keyword = query["keyword"].strip()
            pattern = f"%{keyword}%"
            encoded_pattern = f"%{quote(keyword, safe='')}%"
            numeric_pattern = f"%{keyword.replace(',', '')}%"
            filters.append(
                """
                (
                  log_no ILIKE %s
                  OR TO_CHAR(created_at AT TIME ZONE 'Asia/Shanghai','YYYY-MM-DD HH24:MI:SS') ILIKE %s
                  OR operator ILIKE %s OR operator ILIKE %s
                  OR operation_type ILIKE %s
                  OR CASE operation_type
                       WHEN 'import' THEN '导入' WHEN 'split' THEN '拆分' WHEN 'cancel_split' THEN '取消拆分'
                       WHEN 'adjust' THEN '母行调账' WHEN 'child_adjust' THEN '子项调账'
                       WHEN 'restore' THEN '金额复原'
                       WHEN 'one_click_allocate' THEN '一键调配' WHEN 'batch_assign' THEN '批量修改'
                       WHEN 'summary' THEN '摘要修改' WHEN 'remark' THEN '摘要修改（历史）' WHEN 'submit' THEN '提交'
                       WHEN 'withdraw_submit' THEN '撤回提交'
                       WHEN 'type_create' THEN '新增费用类型' WHEN 'type_update' THEN '编辑费用类型'
                       WHEN 'type_toggle' THEN '启停费用类型' WHEN 'type_delete' THEN '删除费用类型'
                       WHEN 'account_create' THEN '新增入账' WHEN 'account_update' THEN '编辑入账'
                       WHEN 'account_toggle' THEN '启停入账' WHEN 'account_delete' THEN '删除入账'
                       ELSE operation_type END ILIKE %s
                  OR CONCAT_WS(' ',target_description,target_type,target_id::text,
                       CASE target_type WHEN 'split_row' THEN '流水 子项' WHEN 'statement' THEN '流水 母行'
                         WHEN 'expense_type' THEN '费用类型' WHEN 'account_entry' THEN '入账'
                         WHEN 'import_record' THEN '导入批次' ELSE target_type END) ILIKE %s
                  OR COALESCE(change_amount::text,'') ILIKE %s
                  OR COALESCE(ip_address,'') ILIKE %s
                )
                """
            )
            params.extend([pattern, pattern, pattern, encoded_pattern, pattern, pattern, pattern, numeric_pattern, pattern])
        where = "WHERE " + " AND ".join(filters) if filters else ""
        with self.transaction() as cursor:
            cursor.execute("SELECT DISTINCT operation_type FROM fund.operation_log ORDER BY operation_type")
            stored_types = [row["operation_type"] for row in cursor.fetchall()]
            type_codes = list(OPERATION_TYPE_LABELS)
            type_codes.extend(code for code in stored_types if code not in OPERATION_TYPE_LABELS)
            operation_types = [{"value": code, "label": OPERATION_TYPE_LABELS.get(code, code)} for code in type_codes]
            cursor.execute("SELECT DISTINCT operator FROM fund.operation_log WHERE operator<>'' ORDER BY operator")
            operators = sorted({unquote(row["operator"]) for row in cursor.fetchall()})
            cursor.execute(f"SELECT COUNT(*) AS total FROM fund.operation_log {where}", params)
            total = cursor.fetchone()["total"]
            limit_sql = "" if export_all else "LIMIT %s OFFSET %s"
            final_params = params if export_all else params + [page_size, (page - 1) * page_size]
            cursor.execute(
                f"SELECT * FROM fund.operation_log {where} ORDER BY created_at DESC {limit_sql}",
                final_params,
            )
            return {
                "items": [row_dict(row) for row in cursor.fetchall()],
                "operation_types": operation_types,
                "operators": operators,
                "pagination": {"page": page, "page_size": page_size, "total": total},
            }
