from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from apps.automation_center.report_config import (
    profile_enabled, profile_reason, report_enabled, update_profile_settings,
)


def config(**overrides):
    base = {
        "version": 3,
        "profile_rules": [{"name": "抖音", "platform": "抖音", "profile_name_prefixes": ["DY-"], "steps": []}],
        "profile_status": {
            "DY-抖音-MOCK冲饮旗舰店": {"enabled": False, "status": "停业整顿", "reason": "店铺停业整顿"},
        },
    }
    base.update(overrides)
    return base


class ReportConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "all_platform_downloads.json"
        self.write(config())

    def tearDown(self):
        self.directory.cleanup()

    def write(self, payload):
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_reads_profile_and_report_switches(self):
        payload = self.read()
        self.assertFalse(profile_enabled(payload, "DY-抖音-MOCK冲饮旗舰店"))
        self.assertEqual("店铺停业整顿", profile_reason(payload, "DY-抖音-MOCK冲饮旗舰店"))
        self.assertTrue(profile_enabled(payload, "DY-抖音-MOCK宁盏冲饮专卖店"))
        self.assertTrue(report_enabled(payload, "DY-抖音-MOCK冲饮旗舰店", "douyin_order"))

    def test_enable_rewrites_status_so_the_controller_does_not_skip(self):
        update_profile_settings("DY-抖音-MOCK冲饮旗舰店", enabled=True, path=self.path)
        payload = self.read()
        entry = payload["profile_status"]["DY-抖音-MOCK冲饮旗舰店"]
        self.assertTrue(entry["enabled"])
        self.assertEqual("active", entry["status"])
        self.assertTrue(profile_enabled(payload, "DY-抖音-MOCK冲饮旗舰店"))

    def test_disable_keeps_the_file_valid_for_the_controller(self):
        update_profile_settings("DY-抖音-MOCK宁盏冲饮专卖店", enabled=False, path=self.path)
        payload = self.read()
        entry = payload["profile_status"]["DY-抖音-MOCK宁盏冲饮专卖店"]
        self.assertFalse(entry["enabled"])
        self.assertEqual("disabled", entry["status"])
        self.assertIsInstance(entry["reason"], str)
        self.assertTrue(payload["profile_rules"])

    def test_report_switches_merge_without_dropping_existing_keys(self):
        update_profile_settings("DY-抖音-MOCK冲饮旗舰店", reports={"douyin_qianchuan": False}, path=self.path)
        update_profile_settings("DY-抖音-MOCK冲饮旗舰店", reports={"douyin_order": True}, path=self.path)
        payload = self.read()
        self.assertEqual({"douyin_qianchuan": False, "douyin_order": True},
                         payload["profile_status"]["DY-抖音-MOCK冲饮旗舰店"]["reports"])
        self.assertFalse(report_enabled(payload, "DY-抖音-MOCK冲饮旗舰店", "douyin_qianchuan"))
        self.assertTrue(report_enabled(payload, "DY-抖音-MOCK冲饮旗舰店", "douyin_fund"))

    def test_invalid_payloads_are_rejected(self):
        with self.assertRaises(ValueError):
            update_profile_settings("", path=self.path)
        with self.assertRaises(ValueError):
            update_profile_settings("DY-抖音-MOCK冲饮旗舰店", reports={"x": "yes"}, path=self.path)
        with self.assertRaises(ValueError):
            update_profile_settings("DY-抖音-MOCK冲饮旗舰店", path=self.path)


if __name__ == "__main__":
    unittest.main()
