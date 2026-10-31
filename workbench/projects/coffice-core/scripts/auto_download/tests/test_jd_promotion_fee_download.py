from __future__ import annotations

import unittest
from datetime import date, datetime

from scripts.auto_download.playwright.jd_promotion_fee_download import (
    _is_download_action,
    compact_date,
    month_navigation_direction,
    month_keys_for_range,
    parse_created_at,
    parse_visible_months,
    previous_complete_month,
    report_row_is_current,
    report_row_matches_range,
    requested_range,
)


class JdPromotionFeeDownloadTests(unittest.TestCase):
    def test_default_range_is_thirty_days_including_today(self) -> None:
        selected = requested_range(None, None, today=date(2026, 9, 2))

        self.assertEqual(date(2026, 8, 4), selected.start)
        self.assertEqual(date(2026, 9, 2), selected.end)
        self.assertTrue(selected.from_shortcut)

    def test_custom_previous_month_range_is_exact(self) -> None:
        selected = requested_range("2026-08-01", "20260831")

        self.assertEqual((date(2026, 8, 1), date(2026, 8, 31)), (selected.start, selected.end))
        self.assertFalse(selected.from_shortcut)
        self.assertEqual("20260831", compact_date(selected.end))

    def test_previous_complete_month_crosses_year_boundary(self) -> None:
        self.assertEqual(
            ("2025-12-01", "2025-12-31"),
            previous_complete_month(today=date(2026, 1, 2)),
        )

    def test_rejects_partial_or_reversed_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "必须同时提供"):
            requested_range("2026-08-01", None)
        with self.assertRaisesRegex(ValueError, "不能晚于"):
            requested_range("2026-08-31", "2026-08-01")

    def test_calendar_months_and_navigation(self) -> None:
        target = month_keys_for_range(date(2026, 8, 21), date(2026, 9, 10))

        self.assertEqual(((2026, 8), (2026, 9)), target)
        self.assertIsNone(month_navigation_direction(list(target), target))
        self.assertEqual("right", month_navigation_direction([(2026, 7), (2026, 8)], target))
        self.assertEqual("left", month_navigation_direction([(2026, 9), (2026, 10)], target))

    def test_parses_chinese_and_numeric_calendar_months(self) -> None:
        self.assertEqual(
            [(2026, 8), (2026, 9)],
            parse_visible_months("2026年8月 2026-09"),
        )

    def test_selects_latest_created_time_from_row_text(self) -> None:
        self.assertEqual(
            datetime(2026, 9, 2, 14, 5, 6),
            parse_created_at("创建日期：2026-09-02 14:05:06 状态：成功"),
        )
        self.assertIsNone(parse_created_at("状态：导出中"))

    def test_uses_first_row_range_and_submission_day_as_task_guard(self) -> None:
        selected = requested_range("2026-08-01", "2026-08-31")
        row = "报表已生成 起：2026-08-01 止：2026-08-31 创建日期：2026-09-02 16:48:59"

        self.assertTrue(report_row_matches_range(row, selected))
        self.assertTrue(
            report_row_is_current(
                row, selected, datetime(2026, 9, 2, 16, 48, 58)
            )
        )
        self.assertFalse(
            report_row_is_current(
                row.replace("2026-08-31", "2026-09-02"),
                selected,
                datetime(2026, 9, 2, 16, 48, 58),
            )
        )

    def test_alliance_history_row_can_be_guarded_without_range_columns(self) -> None:
        selected = requested_range("2026-08-04", "2026-09-02")
        row = "结算信息 报表已生成 2026-09-02 17:41:36 下载 删除"

        self.assertTrue(
            report_row_is_current(
                row,
                selected,
                datetime(2026, 9, 2, 17, 41, 36),
                report_name="结算信息",
                require_range=False,
            )
        )
        self.assertFalse(
            report_row_is_current(
                row,
                selected,
                datetime(2026, 9, 2, 17, 41, 36),
                report_name="财务记录_消费记录_现金",
                require_range=False,
            )
        )

    def test_default_tong_range_uses_page_default_without_guessing_dates(self) -> None:
        selected = requested_range(None, None, today=date(2026, 9, 2))
        row = "财务记录_消费记录_现金 报表已生成 起：2026-08-03 止：2026-09-02 创建日期：2026-09-02 17:46:00"

        self.assertTrue(
            report_row_is_current(
                row,
                selected,
                datetime(2026, 9, 2, 17, 46, 0),
                report_name="财务记录_消费记录_现金",
                require_range=False,
            )
        )

    def test_does_not_treat_delete_as_download_fallback(self) -> None:
        self.assertFalse(_is_download_action("删除", index=0))
        self.assertFalse(_is_download_action("", index=0, title="删除"))
        self.assertTrue(_is_download_action("", index=0))
        self.assertTrue(_is_download_action("下载", index=1))


if __name__ == "__main__":
    unittest.main()
