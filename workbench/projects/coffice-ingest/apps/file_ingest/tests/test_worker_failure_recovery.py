from __future__ import annotations

import unittest
from contextlib import contextmanager

from apps.file_ingest.service import FileIngestWorker


class _Cursor:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple]] = []
        self._row = None

    def execute(self, sql, params=()):
        self.statements.append((str(sql), tuple(params)))
        if "SELECT COUNT(*) FILTER" in str(sql):
            self._row = {"success_count": 0, "duplicate_count": 0, "failed_count": 1}

    def fetchone(self):
        return self._row


class _Service:
    def __init__(self, cursor: _Cursor) -> None:
        self.cursor = cursor

    @contextmanager
    def transaction(self):
        yield self.cursor


class WorkerFailureRecoveryTests(unittest.TestCase):
    def test_diagnostic_schema_check_supports_real_dict_cursor(self):
        class DiagnosticCursor:
            def execute(self, sql):
                self.sql = str(sql)

            def fetchone(self):
                return {"diagnostic_column_count": 2}

        self.assertTrue(FileIngestWorker._has_file_loader_diagnostics(DiagnosticCursor()))

    def test_unexpected_ingest_error_closes_run_and_pending_files(self):
        cursor = _Cursor()
        worker = object.__new__(FileIngestWorker)
        worker.service = _Service(cursor)

        worker._fail_claimed_ingest_run("run-1", RuntimeError("ETL创建失败"))

        statements = "\n".join(sql for sql, _ in cursor.statements)
        self.assertIn("UPDATE ops.ingest_file_task", statements)
        self.assertIn("status='failed'", statements)
        self.assertIn("UPDATE ops.ingest_run", statements)
        self.assertIn("status='failed'", statements)

    def test_retired_etl_key_completes_as_noop_success(self):
        # 历史运行中滞留的已下线 ETL 任务（如旧天猫结算链路）不得抛出
        # KeyError 击穿运行循环，应按无操作成功收口，让下游共享任务继续。
        cursor = _Cursor()
        worker = object.__new__(FileIngestWorker)
        worker.service = _Service(cursor)

        status = worker._run_etl_task({"etl_key": "tmall_settlement", "etl_task_id": "task-1"})

        self.assertEqual("success", status)
        statements = "\n".join(sql for sql, _ in cursor.statements)
        self.assertIn("UPDATE ops.etl_task", statements)
        self.assertIn("status='success'", statements)
        params_text = "\n".join(str(params) for _, params in cursor.statements)
        self.assertIn("ETL未登记或已下线", params_text)


if __name__ == "__main__":
    unittest.main()
