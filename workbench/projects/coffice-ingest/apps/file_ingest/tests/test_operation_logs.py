import unittest
from contextlib import contextmanager

from apps.file_ingest.service import FileIngestService


class FakeCursor:
    def __init__(self):
        self.calls = []
        self.fetchall_results = [
            [{"operation_type": "file_upload"}, {"operation_type": "run_create"}],
            [{"operator": "日志测试人"}],
            [{"operation_id": 7, "operation_type": "file_upload", "operator": "日志测试人", "description": "上传文件"}],
        ]
        self.fetchone_results = [{"total": 1}]

    def execute(self, statement, params=None):
        self.calls.append((str(statement), tuple(params or ())))

    def fetchall(self):
        return self.fetchall_results.pop(0)

    def fetchone(self):
        return self.fetchone_results.pop(0)


class StubFileIngestService(FileIngestService):
    def __init__(self, cursor):
        self.cursor = cursor

    @contextmanager
    def transaction(self):
        yield self.cursor


class OperationLogTests(unittest.TestCase):
    def test_list_operation_logs_applies_filters_and_returns_filter_options(self):
        cursor = FakeCursor()
        service = StubFileIngestService(cursor)

        result = service.list_operation_logs(
            page=2,
            page_size=20,
            query={
                "date_from": "2026-08-01",
                "date_to": "2026-08-31",
                "operation_type": "file_upload",
                "operator": "日志测试人",
                "keyword": "上传",
            },
        )

        self.assertEqual(result["pagination"], {"total": 1, "page": 2, "page_size": 20})
        self.assertEqual(result["items"][0]["operation_id"], 7)
        self.assertIn({"value": "file_upload", "label": "文件上传"}, result["operation_types"])
        self.assertIn("日志测试人", result["operators"])
        statements = "\n".join(statement for statement, _ in cursor.calls)
        self.assertIn("AT TIME ZONE 'Asia/Shanghai'", statements)
        self.assertIn("operation_type=%s", statements)
        self.assertIn("operator=%s", statements)
        self.assertIn("operator ILIKE %s", statements)
        self.assertIn("operation_type ILIKE %s", statements)
        self.assertIn("description ILIKE %s", statements)
        self.assertEqual(cursor.calls[-1][1][-2:], (20, 20))

    def test_list_operation_logs_rejects_invalid_dates_before_query(self):
        service = StubFileIngestService(FakeCursor())

        with self.assertRaisesRegex(ValueError, "开始日期格式必须为YYYY-MM-DD"):
            service.list_operation_logs(query={"date_from": "2026/08/01"})


if __name__ == "__main__":
    unittest.main()
