from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook

from scripts.auto_download.playwright.pinduoduo_promotion_fee_download import (
    EXPECTED_COLUMNS,
    archive_path_from_log,
    parse_amount,
    parse_date_value,
    validate_download,
)


class PinduoduoPromotionFeeDownloadTests(unittest.TestCase):
    def _write_workbook(self, root: Path, rows: list[list[object]]) -> Path:
        path = root / "promotion.xlsx"
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Sheet0"
        for row in rows:
            worksheet.append(row)
        workbook.save(path)
        workbook.close()
        return path

    def test_validate_download_reads_expected_sheet_and_derives_latest_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_workbook(
                Path(directory),
                [
                    list(EXPECTED_COLUMNS),
                    [
                        datetime(2026, 8, 30, 23, 59, 59),
                        "现金",
                        "支出",
                        "养颜轻食",
                        "-2,518.10",
                        "2911.22",
                        "推广支出： 商品营销2518.10元；",
                    ],
                    [
                        "2026/08/31 23:59:59",
                        "现金",
                        "支出",
                        "养颜轻食",
                        "-2,579.74",
                        "20331.48",
                        "推广支出： 商品营销2579.74元；",
                    ],
                ],
            )

            summary = validate_download(path, "养颜轻食")
            strict_summary = validate_download(
                path,
                "养颜轻食",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 31),
            )

        self.assertEqual("Sheet0", summary["sheet_name"])
        self.assertEqual(2, summary["row_count"])
        self.assertEqual("2026-08-30", summary["min_date"])
        self.assertEqual("2026-08-31", summary["max_date"])
        self.assertEqual("5097.84", str(summary["total_amount"]))
        self.assertEqual(2, strict_summary["row_count"])

    def test_validate_download_rejects_missing_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_workbook(Path(directory), [["时间", "资金类型"]])
            with self.assertRaisesRegex(RuntimeError, "表头不匹配"):
                validate_download(path, "养颜轻食")

    def test_validate_download_rejects_non_cash_or_non_expense_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_workbook(
                Path(directory),
                [
                    list(EXPECTED_COLUMNS),
                    [
                        "2026/08/31 23:59:59",
                        "红包",
                        "支出",
                        "养颜轻食",
                        "-1.00",
                        "0.00",
                        "推广支出",
                    ],
                ],
            )
            with self.assertRaisesRegex(RuntimeError, "资金类型不是现金"):
                validate_download(path, "养颜轻食")

    def test_validate_download_rejects_shop_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_workbook(
                Path(directory),
                [
                    list(EXPECTED_COLUMNS),
                    [
                        "2026/08/31 23:59:59",
                        "现金",
                        "支出",
                        "其他店铺",
                        "-1.00",
                        "0.00",
                        "推广支出",
                    ],
                ],
            )
            with self.assertRaisesRegex(RuntimeError, "店铺与 profile 不一致"):
                validate_download(path, "养颜轻食")

    def test_validate_download_rejects_rows_outside_requested_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_workbook(
                Path(directory),
                [
                    list(EXPECTED_COLUMNS),
                    [
                        "2026/09/01 00:00:00",
                        "现金",
                        "支出",
                        "养颜轻食",
                        "-1.00",
                        "0.00",
                        "推广支出",
                    ],
                ],
            )
            with self.assertRaisesRegex(RuntimeError, "日期晚于请求结束日期"):
                validate_download(
                    path,
                    "养颜轻食",
                    start_date=date(2026, 8, 1),
                    end_date=date(2026, 8, 31),
                )

    def test_parse_helpers_and_archive_log(self) -> None:
        self.assertEqual("-2579.74", str(parse_amount("-2,579.74")))
        self.assertEqual("2026-08-31", parse_date_value("2026/08/31 23:59:59").isoformat())
        self.assertEqual(
            Path(r"C:\Users\win\Desktop\data\拼多多\推广费\file.xlsx"),
            archive_path_from_log(
                "已移动：promotion.xlsx\n  -> C:\\Users\\win\\Desktop\\data\\拼多多\\推广费\\file.xlsx"
            ),
        )


if __name__ == "__main__":
    unittest.main()
