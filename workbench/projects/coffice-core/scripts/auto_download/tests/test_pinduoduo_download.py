from __future__ import annotations

import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scripts.auto_download.playwright.pinduoduo_settlement_download import (
    default_business_date,
    expected_range,
    extract_pdd_report,
    resolve_date_range,
)
from scripts.auto_download.playwright.pinduoduo_order_download import (
    default_business_date as order_default_business_date,
    expected_range as order_expected_range,
    parse_displayed_range,
    resolve_date_range as order_resolve_date_range,
)


PDD_CSV = (
    "拼多多商家账务明细查询\n\n"
    "开始时间：2026-08-16 00:00:00  截止时间：2026-08-16 23:59:59\n"
    "----------交易记录明细列表---------\n"
    "商户订单号,发生时间,收入金额（+元）,支出金额（-元）,账务类型,备注,业务描述\n"
    "1,2026-08-16 12:00:00,1.00,0,交易收入,-,收入\n"
).encode("gb18030")


class PinduoduoDownloadTests(unittest.TestCase):
    def test_default_date_and_range(self):
        with patch(
            "scripts.auto_download.playwright.pinduoduo_settlement_download.date"
        ) as mocked:
            mocked.today.return_value = date(2026, 8, 17)
            self.assertEqual("2026-08-16", default_business_date())
        self.assertEqual(
            "2026-08-16 00:00:00 ~ 2026-08-16 23:59:59",
            expected_range("2026-08-16"),
        )

    def test_extract_unique_csv_validates_header_and_deletes_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "bill.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("pdd-bill.csv", PDD_CSV)
            target = extract_pdd_report(archive, root / "out")
            self.assertEqual(PDD_CSV, target.read_bytes())
            self.assertFalse(archive.exists())

    def test_multiple_csv_members_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "bill.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("a.csv", PDD_CSV)
                bundle.writestr("b.csv", PDD_CSV)
            with self.assertRaisesRegex(RuntimeError, "未找到唯一 CSV"):
                extract_pdd_report(archive, root / "out")

    def test_order_date_helpers_use_yesterday(self):
        with patch(
            "scripts.auto_download.playwright.pinduoduo_order_download.date"
        ) as mocked:
            mocked.today.return_value = date(2026, 8, 24)
            self.assertEqual("2026-08-23", order_default_business_date())
        self.assertEqual(
            "2026-08-23 00:00:00 ~ 2026-08-23 23:59:59",
            order_expected_range("2026-08-23"),
        )

    def test_parse_displayed_quick_range_dates(self):
        self.assertEqual(
            ("2026-08-09", "2026-09-08"),
            parse_displayed_range(
                "2026-08-09 14:58:23 ~ 2026-09-08 14:58:23"
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "无法解析"):
            parse_displayed_range("近30日")

    def test_custom_date_range_is_normalized_and_validated(self):
        expected = ("2026-08-01", "2026-08-31")
        self.assertEqual(expected, resolve_date_range(*expected))
        self.assertEqual(expected, order_resolve_date_range(*expected))
        with self.assertRaisesRegex(ValueError, "必须同时提供"):
            resolve_date_range("2026-08-01", None)
        with self.assertRaisesRegex(ValueError, "不能晚于"):
            order_resolve_date_range("2026-08-31", "2026-08-01")


if __name__ == "__main__":
    unittest.main()
