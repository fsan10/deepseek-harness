from __future__ import annotations

import sys
import unittest
from pathlib import Path


ETL_ROOT = Path(__file__).resolve().parents[3] / "etl"
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import read_excel_rows, validate_header  # noqa: E402
from xhs.load_xhs_fund_ledger_ods import CONFIG, EXPECTED_COLUMNS  # noqa: E402


SAMPLE_FILE = Path(
    r"C:\Users\win\Desktop\data\小红书\资金\202608_小红书_墨客咖时(南京)生物科技有限公司_MOCK旗舰店_资金.xlsx"
)


class XhsFundLedgerLoaderTests(unittest.TestCase):
    def test_loader_targets_the_new_ods_table_and_sheet(self):
        self.assertEqual("ods.ods_xhs_fund_ledger_raw", CONFIG.table_name)
        self.assertEqual("资金账单明细", CONFIG.default_sheet_name)
        self.assertEqual(
            [
                "动账时间",
                "业务单号",
                "动账场景",
                "动账方向",
                "动账金额",
                "动账账户",
                "动账后余额",
            ],
            EXPECTED_COLUMNS,
        )

    def test_provided_fund_ledger_sample_header_is_accepted(self):
        if not SAMPLE_FILE.is_file():
            self.skipTest(f"未找到用户提供的样本文件：{SAMPLE_FILE}")

        _, sheet_name, row_count, header, rows = read_excel_rows(
            CONFIG,
            SAMPLE_FILE,
            None,
        )
        validate_header(
            header,
            CONFIG.expected_columns,
            strict_header=False,
            optional_columns=CONFIG.optional_columns,
        )
        self.assertEqual("资金账单明细", sheet_name)
        self.assertEqual(84, row_count)
        self.assertEqual(83, len(rows))


if __name__ == "__main__":
    unittest.main()
