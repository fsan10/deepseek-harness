import unittest
from contextlib import contextmanager

from apps.file_ingest.service import FileIngestService


class CategoryCursor:
    def __init__(self, next_serial=1, platform_code="pdd"):
        self.calls = []
        self.fetchone_results = [
            None,
            {"next_serial": next_serial},
            {
                "platform_code": platform_code,
                "primary_category_code": f"{platform_code.upper()}_{next_serial:02d}",
                "primary_category_name": "测试分类",
            },
        ]

    def execute(self, statement, params=None):
        self.calls.append((str(statement), tuple(params or ())))

    def fetchone(self):
        return self.fetchone_results.pop(0)


class CategoryListCursor:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), tuple(params or ())))

    def fetchall(self):
        return [
            {
                "platform_code": "pdd",
                "primary_category_code": "PDD_01",
                "primary_category_name": "拼多多分类",
                "display_order": 0,
                "classification_note": "",
                "is_active": True,
                "created_by": "tester",
                "updated_by": "tester",
                "created_at": None,
                "updated_at": None,
                "mapping_count": 0,
                "active_mapping_count": 0,
                "included_mapping_count": 0,
                "platforms": [],
                "platform_codes": [],
                "same_name_code_count": 1,
            },
        ]


class StubCategoryService(FileIngestService):
    def __init__(self, cursor):
        self.cursor = cursor
        self.logs = []

    @contextmanager
    def transaction(self):
        yield self.cursor

    def _write_log(self, cursor, *args):
        self.logs.append(args)


class FeeCategoryManagementTests(unittest.TestCase):
    def test_platform_filter_includes_a_new_category_before_it_has_mappings(self):
        cursor = CategoryListCursor()
        service = StubCategoryService(cursor)

        result = service.list_fee_categories({"platform_code": "PDD"})

        self.assertEqual(["PDD_01"], [item["primary_category_code"] for item in result["items"]])
        self.assertEqual(["拼多多"], result["items"][0]["platforms"])
        self.assertIn("c.platform_code", cursor.calls[0][0])

    def test_category_platforms_use_matching_mapping_name_before_owner_platform(self):
        cursor = CategoryListCursor()
        cursor.fetchall = lambda: [{
            "platform_code": "pdd",
            "primary_category_code": "baiyibutie",
            "primary_category_name": "天猫-百亿补贴",
            "display_order": 0,
            "classification_note": "",
            "is_active": True,
            "created_by": "tester",
            "updated_by": "tester",
            "created_at": None,
            "updated_at": None,
            "mapping_count": 4,
            "active_mapping_count": 4,
            "included_mapping_count": 4,
            "platforms": ["天猫"],
            "platform_codes": ["tmall"],
            "same_name_code_count": 1,
        }]
        service = StubCategoryService(cursor)

        result = service.list_fee_categories({})

        self.assertEqual(["天猫"], result["items"][0]["platforms"])
        self.assertEqual(["tmall"], result["items"][0]["platform_codes"])
        self.assertIn("m.primary_category_name=c.primary_category_name", cursor.calls[0][0])

    def test_create_generates_platform_prefixed_code_and_ignores_manual_code(self):
        cursor = CategoryCursor(next_serial=1)
        service = StubCategoryService(cursor)

        result = service.create_fee_category(
            {
                "platform_code": "pdd",
                "primary_category_code": "manual_code_should_not_be_used",
                "primary_category_name": "测试分类",
            },
            operator="tester",
            ip_address=None,
        )

        self.assertEqual("PDD_01", result["primary_category_code"])
        insert_params = cursor.calls[-1][1]
        self.assertEqual(("pdd", "PDD_01", "测试分类", 0, "", "tester", "tester"), insert_params)
        self.assertIn("pg_advisory_xact_lock", "\n".join(statement for statement, _ in cursor.calls))
        self.assertEqual("PDD_01", service.logs[0][2])

    def test_create_advances_the_global_sequence(self):
        cursor = CategoryCursor(next_serial=2, platform_code="jd")
        service = StubCategoryService(cursor)

        result = service.create_fee_category(
            {"platform_code": "jd", "primary_category_name": "第二个分类"},
            operator="tester",
            ip_address=None,
        )

        self.assertEqual("JD_02", result["primary_category_code"])
        self.assertEqual("JD_02", cursor.calls[-1][1][1])

    def test_create_rejects_unknown_platform_before_opening_transaction(self):
        service = FileIngestService.__new__(FileIngestService)

        with self.assertRaisesRegex(ValueError, "请选择有效的平台"):
            service.create_fee_category(
                {"platform_code": "unknown", "primary_category_name": "测试分类"},
                operator="tester",
                ip_address=None,
            )


if __name__ == "__main__":
    unittest.main()
