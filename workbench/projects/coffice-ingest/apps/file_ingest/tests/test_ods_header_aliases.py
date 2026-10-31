from __future__ import annotations

import unittest
import sys
import tempfile
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[3] / "etl"
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import (
    OdsLoadConfig,
    align_source_map,
    canonicalize_header,
    validate_header,
)


class OdsHeaderAliasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = OdsLoadConfig(
            platform_code="douyin",
            platform_name="抖音",
            data_domain="ad",
            table_name="ods.ods_douyin_qianchuan_finance_raw",
            expected_columns=["日期", "共享赠款消耗(元)"],
            header_row_no=1,
            data_start_row_no=2,
            header_aliases={"共享赠款消耗": "共享赠款消耗(元)"},
        )

    def test_legacy_source_name_is_aligned_to_standard_ods_name(self):
        header, applied = canonicalize_header(
            ["日期", "共享赠款消耗"], self.config.header_aliases
        )
        validate_header(header, self.config.expected_columns, strict_header=False)
        self.assertEqual(["日期", "共享赠款消耗(元)"], header)
        self.assertEqual({"共享赠款消耗": "共享赠款消耗(元)"}, applied)
        self.assertEqual(
            {"日期": "2026-08-24", "共享赠款消耗(元)": "0.00"},
            align_source_map(header, ["2026-08-24", "0.00"], self.config.expected_columns),
        )

    def test_standard_name_still_works_without_alias_application(self):
        header, applied = canonicalize_header(
            ["日期", "共享赠款消耗(元)"], self.config.header_aliases
        )
        validate_header(header, self.config.expected_columns, strict_header=False)
        self.assertEqual({}, applied)

    def test_both_names_are_rejected_as_ambiguous(self):
        with self.assertRaisesRegex(ValueError, "表头字段别名冲突"):
            canonicalize_header(
                ["日期", "共享赠款消耗", "共享赠款消耗(元)"],
                self.config.header_aliases,
            )

    def test_qianchuan_loader_declares_the_platform_alias(self):
        from douyin.load_douyin_qianchuan_finance_ods import CONFIG

        self.assertEqual(
            {"共享赠款消耗": "共享赠款消耗(元)"},
            CONFIG.header_aliases,
        )

    def test_qianchuan_csv_uses_second_row_without_changing_excel_start_row(self):
        from common.ods_file_loader import read_csv_rows
        from douyin.load_douyin_qianchuan_finance_ods import CONFIG

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "qianchuan.csv"
            path.write_text(
                "日期,共享赠款消耗\n2026-08-24,0.00\n",
                encoding="utf-8",
            )
            _, _, _, header, rows = read_csv_rows(CONFIG, path)
        self.assertEqual(3, CONFIG.data_start_row_no)
        self.assertEqual(2, CONFIG.csv_data_start_row_no)
        self.assertEqual(1, len(rows))
        self.assertEqual("2026-08-24", rows[0][1][0])
        self.assertEqual("共享赠款消耗", header[1])

    def test_qianchuan_monthly_excel_skips_total_row(self):
        from openpyxl import Workbook
        from common.ods_file_loader import read_excel_rows
        from douyin.load_douyin_qianchuan_finance_ods import CONFIG

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "qianchuan-month.xlsx"
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = "data"
            worksheet.append(["日期", "共享赠款消耗(元)"])
            worksheet.append(["总计", "100.00"])
            worksheet.append(["2026-08-24", "0.00"])
            workbook.save(path)
            workbook.close()
            _, _, _, header, rows = read_excel_rows(CONFIG, path, None)
        self.assertEqual(["日期", "共享赠款消耗(元)"], header)
        self.assertEqual(1, len(rows))
        self.assertEqual("2026-08-24", rows[0][1][0])


if __name__ == "__main__":
    unittest.main()
