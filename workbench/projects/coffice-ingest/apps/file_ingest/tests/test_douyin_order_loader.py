from __future__ import annotations

import sys
import unittest
from pathlib import Path


ETL_ROOT = Path(__file__).resolve().parents[3] / "etl"
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import validate_header  # noqa: E402
from douyin.load_douyin_order_ods import (  # noqa: E402
    CONFIG,
    EXPECTED_COLUMNS,
    OPTIONAL_COLUMNS,
    SENSITIVE_ORDER_COLUMNS,
    mask_sensitive_order_fields,
)


class DouyinOrderLoaderTests(unittest.TestCase):
    def test_legacy_export_without_fudai_columns_is_accepted(self):
        legacy_header = [
            column for column in EXPECTED_COLUMNS if column not in OPTIONAL_COLUMNS
        ]

        validate_header(
            legacy_header,
            CONFIG.expected_columns,
            strict_header=False,
            optional_columns=CONFIG.optional_columns,
        )

    def test_fudai_columns_are_declared_optional(self):
        self.assertEqual(OPTIONAL_COLUMNS, CONFIG.optional_columns)
        self.assertEqual(16, len(CONFIG.optional_columns))

    def test_unused_recipient_fields_are_masked(self):
        source_map = {
            "收件人": "真实收件人",
            "收件人手机号": "13800000000",
            "详细地址": "真实收货地址",
            "订单状态": "已发货",
        }

        masked = mask_sensitive_order_fields(source_map, None, Path("orders.csv"))

        for column_name in SENSITIVE_ORDER_COLUMNS:
            self.assertEqual(masked[column_name], "***")
        self.assertEqual(masked["订单状态"], "已发货")

    def test_empty_recipient_fields_remain_null(self):
        source_map = {
            "收件人": None,
            "收件人手机号": None,
            "详细地址": None,
        }

        masked = mask_sensitive_order_fields(source_map, None, Path("orders.csv"))

        self.assertEqual(masked, source_map)


if __name__ == "__main__":
    unittest.main()
