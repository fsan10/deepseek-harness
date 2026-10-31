from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from scripts.auto_download.playwright.xiaohongshu_download_common import (
    FUND_HEADERS,
    SETTLEMENT_EXPENSE_HEADERS,
    SETTLEMENT_INCOME_HEADERS,
    extract_business_date,
    validate_fund_report,
    validate_settlement_report,
)
from etl.xhs.load_xhs_settlement_ods import parse_workbook


class XiaohongshuDownloadTests(unittest.TestCase):
    def test_extract_daily_and_monthly_dates(self):
        self.assertEqual(
            "2026-08-16", extract_business_date("2026-08-16\t155.84", "day")
        )
        self.assertEqual(
            "202607", extract_business_date("2026.07.01~2026.07.31", "month")
        )

    def test_validate_fund_workbook(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "fund.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "资金账单明细"
            sheet.append(FUND_HEADERS)
            sheet.append(("2026-08-16 10:00:00", "P1", "结算入账", "收入", 1, "店铺余额", 2))
            workbook.save(report)
            validate_fund_report(report)

    def test_validate_settlement_workbook(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "settlement.xlsx"
            workbook = Workbook()
            overview = workbook.active
            overview.title = "总览"
            income = workbook.create_sheet("订单结算")
            income.append(SETTLEMENT_INCOME_HEADERS)
            income.append(tuple("-" for _ in SETTLEMENT_INCOME_HEADERS))
            expense = workbook.create_sheet("其他服务款")
            expense.append(SETTLEMENT_EXPENSE_HEADERS)
            expense.append(tuple("-" for _ in SETTLEMENT_EXPENSE_HEADERS))
            workbook.save(report)
            validate_settlement_report(report)
            plans = parse_workbook(report, no_strict_header=False)
            self.assertEqual(["订单结算", "其他服务款"], [plan.sheet_name for plan in plans])
            self.assertEqual(
                ["ods.ods_xhs_settlement_income_raw", "ods.ods_xhs_settlement_expense_raw"],
                [plan.config.table_name for plan in plans],
            )


if __name__ == "__main__":
    unittest.main()
