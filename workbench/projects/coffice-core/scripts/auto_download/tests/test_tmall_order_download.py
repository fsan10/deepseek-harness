from __future__ import annotations

import datetime as dt
import unittest

from scripts.auto_download.playwright.tmall_order_download import (
    REQUIRED_FIELDS,
    history_range,
    history_range_matches,
    parse_history_datetime,
    recent_month_range,
    resolve_date_range,
)


class TmallOrderDownloadTests(unittest.TestCase):
    def test_recent_month_range_uses_thirty_days(self) -> None:
        self.assertEqual(
            ("2026-07-28", "2026-08-27"),
            recent_month_range(dt.date(2026, 8, 27)),
        )

    def test_resolves_partial_and_explicit_ranges(self) -> None:
        self.assertEqual(
            ("2026-07-28", "2026-08-27"),
            resolve_date_range(None, "2026-08-27"),
        )
        self.assertEqual(
            ("2026-07-28", "2026-08-27"),
            resolve_date_range("2026-07-28", "2026-08-27"),
        )

    def test_rejects_reversed_range(self) -> None:
        with self.assertRaises(ValueError):
            resolve_date_range("2026-08-28", "2026-08-27")

    def test_requires_the_ods_thirteen_fields(self) -> None:
        self.assertEqual(13, len(REQUIRED_FIELDS))
        self.assertEqual(13, len(set(REQUIRED_FIELDS)))
        self.assertIn("买家实付金额", REQUIRED_FIELDS)
        self.assertIn("订单付款时间", REQUIRED_FIELDS)

    def test_parses_history_application_time_and_range(self) -> None:
        text = (
            "报表申请时间：2026-08-27 16:18:58 报表类型：宝贝销售明细报表 "
            "创建时间：2026-07-27 00:00:00 到 2026-08-27 00:00:00"
        )
        self.assertEqual(
            dt.datetime(2026, 8, 27, 16, 18, 58),
            parse_history_datetime("2026-08-27 16:18:58"),
        )
        self.assertEqual(
            ("2026-07-27", "2026-08-27"),
            history_range(text),
        )
        self.assertTrue(history_range_matches(text, "2026-07-28", "2026-08-27"))

    def test_history_range_requires_matching_end_date(self) -> None:
        text = "创建时间：2026-07-27 00:00:00 到 2026-08-26 00:00:00"
        self.assertFalse(history_range_matches(text, "2026-07-28", "2026-08-27"))


if __name__ == "__main__":
    unittest.main()
