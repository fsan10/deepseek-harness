from __future__ import annotations

import unittest
import sys
from pathlib import Path


ETL_ROOT = Path(__file__).resolve().parents[3] / "etl"
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import align_source_map, canonicalize_header, validate_header
from wechat_channels.load_wechat_channels_order_ods import CONFIG, EXPECTED_COLUMNS


class WechatChannelsOrderLoaderTests(unittest.TestCase):
    def test_split_discount_header_is_the_current_ods_contract(self):
        header, applied = canonicalize_header(EXPECTED_COLUMNS, CONFIG.header_aliases)
        validate_header(
            header,
            CONFIG.expected_columns,
            strict_header=False,
            optional_columns=CONFIG.optional_columns,
        )

        self.assertEqual({}, applied)
        self.assertIn("商家优惠", header)
        self.assertIn("平台优惠", header)
        self.assertNotIn("商品优惠", header)

    def test_legacy_discount_header_maps_without_creating_a_second_ods_table(self):
        legacy_header = [
            "商品优惠" if column == "商家优惠" else column
            for column in EXPECTED_COLUMNS
            if column != "平台优惠"
        ]
        header, applied = canonicalize_header(legacy_header, CONFIG.header_aliases)
        validate_header(
            header,
            CONFIG.expected_columns,
            strict_header=False,
            optional_columns=CONFIG.optional_columns,
        )

        self.assertEqual({"商品优惠": "商家优惠"}, applied)
        self.assertNotIn("商品优惠", header)
        mapped = align_source_map(
            header,
            ["legacy-value" if column == "商家优惠" else None for column in header],
            CONFIG.expected_columns,
        )
        self.assertEqual("legacy-value", mapped["商家优惠"])
        self.assertIsNone(mapped["平台优惠"])

    def test_old_and_new_discount_headers_are_rejected_as_ambiguous(self):
        with self.assertRaisesRegex(ValueError, "表头字段别名冲突"):
            canonicalize_header(
                [*EXPECTED_COLUMNS, "商品优惠"],
                CONFIG.header_aliases,
            )


if __name__ == "__main__":
    unittest.main()
