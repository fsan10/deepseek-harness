from __future__ import annotations

import argparse
import unittest

from apps.automation_center.module import AutomationCenterModule
from apps.automation_center.service import AutomationService, bounded_int


def _args() -> argparse.Namespace:
    return argparse.Namespace(host="localhost", pg_port=5432, dbname="db", user="u", password=None)


class Context:
    def __init__(self, *permissions):
        self.permissions = set(permissions)

    def can(self, permission):
        return permission in self.permissions


class BoundedIntTests(unittest.TestCase):
    def test_nan_is_rejected_with_field_label(self):
        with self.assertRaisesRegex(ValueError, "page必须是整数"):
            bounded_int("NaN", default=1, label="page")

    def test_blank_values_fall_back_to_default(self):
        self.assertEqual(20, bounded_int(None, default=20, label="page_size"))
        self.assertEqual(20, bounded_int("   ", default=20, label="page_size"))

    def test_out_of_range_values_are_clamped(self):
        self.assertEqual(1, bounded_int("0", default=1, label="page"))
        self.assertEqual(1, bounded_int("-5", default=1, label="page"))
        self.assertEqual(100, bounded_int("500", default=20, maximum=100, label="page_size"))


class ListRunsQueryTests(unittest.TestCase):
    """非数字查询参数必须在访问数据库前被拦下，转换成 400 而不是 500。"""

    @classmethod
    def setUpClass(cls):
        cls.service = AutomationService(_args())

    def test_nan_page_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "page必须是整数"):
            self.service.list_runs({"page": "NaN"})

    def test_nan_page_size_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "page_size必须是整数"):
            self.service.list_runs({"page_size": "NaN"})

    def test_invalid_date_range_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "开始日期必须为 YYYY-MM-DD"):
            self.service.list_runs({"date_from": "2026-13-01"})


class ModuleQueryStringTests(unittest.TestCase):
    """浏览器把 page=NaN 拼进查询串时，模块层同样要抛中文校验错误。"""

    @classmethod
    def setUpClass(cls):
        module = AutomationCenterModule(_args())
        cls.dispatch = module.dispatch

    def test_query_string_with_nan_page_is_a_client_error(self):
        context = Context("automation.runs.view")
        with self.assertRaisesRegex(ValueError, "page必须是整数"):
            self.dispatch("GET", "/api/automation/runs", "page=NaN&page_size=20", context=context)

    def test_query_string_with_nan_page_size_is_a_client_error(self):
        context = Context("automation.runs.view")
        with self.assertRaisesRegex(ValueError, "page_size必须是整数"):
            self.dispatch("GET", "/api/automation/runs", "page=1&page_size=NaN", context=context)


if __name__ == "__main__":
    unittest.main()
