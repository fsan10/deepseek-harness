from __future__ import annotations

import tempfile
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts.auto_download.playwright.kuaishou_download_common import extract_unique_report
from scripts.auto_download.playwright.kuaishou_fund_download import (
    extract_export_record_business_date,
    extract_business_date,
    extract_sub_mch_id_from_url,
)
from scripts.auto_download.playwright.kuaishou_settlement_download import (
    default_business_date,
    parse_record_count,
    validate_business_date,
)


class KuaishouDownloadTests(unittest.TestCase):
    def test_fund_day_and_month_dates(self):
        self.assertEqual("20260816", extract_business_date("20260816\t19\t1886.34", "day"))
        self.assertEqual("202607", extract_business_date("202607\t800\t81870.68", "month"))

    def test_fund_export_record_date_formats(self):
        self.assertEqual(
            "20260917",
            extract_export_record_business_date("账单日期：2026/09/17\n完成时间"),
        )
        self.assertEqual(
            "20260917",
            extract_export_record_business_date("账单日期: 2026-09-17\n完成时间"),
        )
        self.assertEqual(
            "20260917",
            extract_export_record_business_date("账单日期：20260917\n完成时间"),
        )
        self.assertEqual(
            "202609",
            extract_export_record_business_date("账单日期：2026/09\n完成时间"),
        )

    def test_fund_sub_mch_id_from_current_profile_url(self):
        self.assertEqual(
            "5504000473733984",
            extract_sub_mch_id_from_url(
                "https://s.kwaixiaodian.com/zone/fund/accounting/export-list"
                "?isNew=true&subMchId=5504000473733984"
            ),
        )
        self.assertIsNone(
            extract_sub_mch_id_from_url("https://s.kwaixiaodian.com/zone/fund/accounting")
        )

    def test_settlement_date_validation(self):
        self.assertEqual("2026-08-16", validate_business_date("2026-08-16"))
        with self.assertRaises(ValueError):
            validate_business_date("20260816")

    def test_default_settlement_date_is_yesterday(self):
        with patch("scripts.auto_download.playwright.kuaishou_settlement_download.date") as mocked:
            mocked.today.return_value = date(2026, 8, 17)
            self.assertEqual("2026-08-16", default_business_date())
            mocked.today.assert_called_once()

    def test_settlement_record_count(self):
        self.assertEqual(0, parse_record_count("共计0条"))
        self.assertEqual(1234, parse_record_count("共计1,234条"))
        self.assertIsNone(parse_record_count("暂无数据"))

    def test_extract_unique_xlsx_and_delete_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "settlement.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("订单流水导出.xlsx_1.xlsx", b"xlsx-data")
                bundle.writestr("说明.txt", b"readme")
            target = extract_unique_report(archive, root / "out", (".xlsx", ".csv"))
            self.assertEqual(b"xlsx-data", target.read_bytes())
            self.assertFalse(archive.exists())


if __name__ == "__main__":
    unittest.main()
