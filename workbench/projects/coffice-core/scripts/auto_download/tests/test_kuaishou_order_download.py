from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from openpyxl import Workbook, load_workbook

from scripts.auto_download.playwright.kuaishou_order_download import (
    _RATE_LIMIT_RE,
    _date_range_matches,
    _is_pending_order_export_text,
    _parse_created,
    decrypt_xlsx,
    parse_order_record_count,
    recent_month_range,
    validate_xlsx,
)


class KuaishouOrderDownloadTests(unittest.TestCase):
    def test_recent_month_is_thirty_calendar_days_including_end(self):
        self.assertEqual(
            ("2026-07-28", "2026-08-26"),
            recent_month_range(today=date(2026, 8, 26)),
        )

    def test_history_range_matches_end_date_when_platform_changes_start_boundary(self):
        text = "标准报表\n下单时间\n2026-07-29 00:00:00~2026-08-26 23:59:59"
        self.assertTrue(_date_range_matches(text, "2026-07-28", "2026-08-26"))
        self.assertFalse(_date_range_matches(text, "2026-07-28", "2026-08-27"))
        self.assertFalse(_date_range_matches(text, "2026-07-28", "2026-08-26", require_start=True))

    def test_created_time_is_sortable(self):
        self.assertEqual((2026, 8, 26, 13, 52, 7), _parse_created("生成时间 2026/08/26 13:52:07"))

    def test_export_constraints_are_not_treated_as_rate_limit(self):
        self.assertFalse(_RATE_LIMIT_RE.search("两次导出的时间间隔请保持在5分钟以上"))
        self.assertTrue(_RATE_LIMIT_RE.search("操作过于频繁，请5分钟后再试"))

    def test_pending_order_export_requires_sms_dialog_and_submit_action(self):
        self.assertTrue(
            _is_pending_order_export_text(
                "批量导出订单 标准报表 短信验证码 验证码已发送 生成报表"
            )
        )
        self.assertFalse(_is_pending_order_export_text("请输入验证码 确认"))
        self.assertFalse(_is_pending_order_export_text("批量导出订单 标准报表 导出"))

    def test_order_record_count_supports_zero_and_full_width_digits(self):
        self.assertEqual(0, parse_order_record_count("共计0条"))
        self.assertEqual(1234, parse_order_record_count("共计1，２３４条"))
        self.assertIsNone(parse_order_record_count("暂无符合条件的订单"))

    def test_plain_xlsx_is_copied_and_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.xlsx"
            target = root / "decrypted.xlsx"
            workbook = Workbook()
            workbook.active.append(["订单号", "金额"])
            workbook.active.append(["A-1", 99])
            workbook.save(source)
            decrypt_xlsx(source, "ignored-for-plain-file", target)
            validate_xlsx(target)
            loaded = load_workbook(target, read_only=True)
            try:
                self.assertEqual(("订单号", "金额"), list(loaded.active.values)[0])
            finally:
                loaded.close()


if __name__ == "__main__":
    unittest.main()
