from __future__ import annotations

import unittest
from contextlib import contextmanager

from apps.file_ingest.service import FileIngestService


class _DatabaseError(Exception):
    def __init__(self, pgcode: str) -> None:
        super().__init__(pgcode)
        self.pgcode = pgcode


class _Cursor:
    def __init__(self, *, one=None, many=None, metrics_error: str | None = None) -> None:
        self.one_values = list(one or [])
        self.many_values = list(many or [])
        self.metrics_error = metrics_error
        self.statements: list[str] = []

    def execute(self, sql, params=()) -> None:
        statement = str(sql)
        self.statements.append(statement)
        if self.metrics_error and "FROM ods.ods_file_ingest_log" in statement:
            raise _DatabaseError(self.metrics_error)

    def fetchone(self):
        return self.one_values.pop(0)

    def fetchall(self):
        return self.many_values.pop(0)


class _Service(FileIngestService):
    def __init__(self, cursors: list[_Cursor]) -> None:
        self.cursors = iter(cursors)

    @contextmanager
    def transaction(self):
        yield next(self.cursors)


class IngestDetailReadPathTests(unittest.TestCase):
    def _detail_service(self, metrics_cursor: _Cursor) -> tuple[_Service, _Cursor]:
        core_cursor = _Cursor(
            one=[{"run_id": "run-1", "status": "success"}],
            many=[
                [{"file_task_id": "task-1", "status": "success"}],
                [{"file_task_id": "task-1", "batch_id": 1001, "target_table": "ods_demo"}],
                [{"etl_run_id": "etl-1", "status": "running"}],
            ],
        )
        return _Service([core_cursor, metrics_cursor]), core_cursor

    def test_detail_keeps_core_data_when_ods_log_is_locked(self):
        service, core_cursor = self._detail_service(_Cursor(metrics_error="55P03"))

        detail = service.run_detail("run-1")

        self.assertEqual("success", detail["run"]["status"])
        self.assertEqual("success", detail["files"][0]["status"])
        self.assertEqual(1001, detail["files"][0]["ods_batches"][0]["batch_id"])
        self.assertNotIn("total_rows", detail["files"][0]["ods_batches"][0])
        self.assertFalse(any("ods.ods_file_ingest_log" in statement for statement in core_cursor.statements))

    def test_detail_merges_ods_metrics_when_the_log_is_readable(self):
        metrics_cursor = _Cursor(
            many=[
                [{
                    "batch_id": 1001,
                    "total_rows": 12,
                    "parsed_rows": 12,
                    "success_rows": 11,
                    "failed_rows": 1,
                    "ingest_status": "success",
                    "ods_error_message": None,
                }]
            ]
        )
        service, core_cursor = self._detail_service(metrics_cursor)

        detail = service.run_detail("run-1")

        batch = detail["files"][0]["ods_batches"][0]
        self.assertEqual(12, batch["total_rows"])
        self.assertEqual(11, batch["success_rows"])
        self.assertEqual("success", batch["ingest_status"])

    def test_detail_does_not_hide_unrelated_database_errors(self):
        service, _core_cursor = self._detail_service(_Cursor(metrics_error="42P01"))

        with self.assertRaisesRegex(_DatabaseError, "42P01"):
            service.run_detail("run-1")

    def test_run_list_does_not_read_ods_log_table(self):
        cursor = _Cursor(one=[{"total": 0}], many=[[]])
        service = _Service([cursor])
        service._mark_stale_drafts = lambda *_args, **_kwargs: None

        result = service.list_runs()

        self.assertEqual([], result["items"])
        self.assertTrue(cursor.statements)
        self.assertFalse(any("ods.ods_file_ingest_log" in statement for statement in cursor.statements))
        self.assertIn("ILIKE '%%警告%%'", cursor.statements[-1])
        self.assertIn("ILIKE '%%商品编码未配置%%'", cursor.statements[-1])

    def test_etl_run_list_escapes_literal_like_wildcards(self):
        cursor = _Cursor(one=[{"total": 0}], many=[[]])
        service = _Service([cursor])

        result = service.list_etl_runs()

        self.assertEqual([], result["items"])
        self.assertIn("ILIKE '%%警告%%'", cursor.statements[-1])
        self.assertIn("ILIKE '%%商品编码未配置%%'", cursor.statements[-1])


if __name__ == "__main__":
    unittest.main()
