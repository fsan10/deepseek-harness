from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from apps.file_ingest.naming import build_filename, guess_filename
from apps.file_ingest.rename_file import rename_file


SHOP = {
    "platform_code": "tmall",
    "platform_name": "天猫",
    "company_code": "mock",
    "company_name": "墨客咖时（南京）生物科技有限公司",
    "shop_code": "mock_flagship",
    "shop_name": "MOCK_旗舰店",
    "shop_identity_key": "tmall:mock_flagship",
}


class NamingTests(unittest.TestCase):
    def test_single_and_sequence_names(self):
        expected = "天猫_墨客咖时（南京）生物科技有限公司_MOCK_旗舰店_结算支出.xlsx"
        self.assertEqual(expected, build_filename(extension="xlsx", platform_name="天猫", company_name=SHOP["company_name"], shop_name=SHOP["shop_name"], report_name="结算支出"))
        self.assertEqual(expected.removesuffix(".xlsx") + "_002.xlsx", build_filename(extension=".xlsx", platform_name="天猫", company_name=SHOP["company_name"], shop_name=SHOP["shop_name"], report_name="结算支出", sequence=2))

    def test_windows_invalid_characters_are_replaced(self):
        name = build_filename(extension="csv", platform_name="天猫", company_name="甲/乙", shop_name="店:铺", report_name="结算支出")
        self.assertEqual("天猫_甲-乙_店-铺_结算支出.csv", name)

    def test_guess_supports_underscores_and_sequence(self):
        filename = "天猫_墨客咖时（南京）生物科技有限公司_MOCK_旗舰店_结算支出_001.xlsx"
        result = guess_filename(filename, [SHOP])
        self.assertTrue(result["matched"])
        self.assertEqual("tmall_settlement_expense", result["report_type"])
        self.assertEqual(1, result["sequence"])

    def test_guess_ignores_daily_and_monthly_date_prefix(self):
        for prefix in ("20260814_", "202608_", "\ufeff20260814＿"):
            with self.subTest(prefix=prefix):
                filename = (
                    f"{prefix}天猫_墨客咖时（南京）生物科技有限公司_"
                    "MOCK_旗舰店_结算支出_002.xlsx"
                )
                result = guess_filename(filename, [SHOP])
                self.assertTrue(result["matched"])
                self.assertEqual("tmall_settlement_expense", result["report_type"])
                self.assertEqual(2, result["sequence"])

    def test_guess_does_not_treat_invalid_date_length_as_prefix(self):
        filename = "2026081_天猫_墨客咖时（南京）生物科技有限公司_MOCK_旗舰店_结算支出.xlsx"
        self.assertFalse(guess_filename(filename, [SHOP])["matched"])

    def test_guess_date_prefix_with_ascii_parentheses_matches_dim_fullwidth_parentheses(self):
        xhs_shop = {
            "platform_code": "xhs",
            "platform_name": "小红书",
            "company_code": "mock",
            "company_name": "墨客咖时（南京）生物科技有限公司",
            "shop_code": "mock_flagship",
            "shop_name": "MOCK旗舰店",
            "shop_identity_key": "xhs:mock_flagship",
        }
        filename = "20260816_小红书_墨客咖时(南京)生物科技有限公司_MOCK旗舰店_结算.xlsx"
        result = guess_filename(filename, [xhs_shop])
        self.assertTrue(result["matched"])
        self.assertEqual("xhs_settlement", result["report_type"])
        self.assertEqual("墨客咖时（南京）生物科技有限公司", result["company_name"])

    def test_rename_refuses_overwrite_and_does_not_return_original_name(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "download.csv"
            source.write_text("a,b\n1,2\n", encoding="utf-8")
            args = argparse.Namespace(file=str(source), platform_name="天猫", company_name=SHOP["company_name"], shop_name=SHOP["shop_name"], report_name="结算支出", sequence=None)
            result = rename_file(args)
            self.assertNotIn("original_filename", result)
            self.assertTrue(Path(result["path"]).is_file())
            conflict = Path(directory) / "another.csv"
            conflict.write_text("x", encoding="utf-8")
            args.file = str(conflict)
            with self.assertRaises(FileExistsError):
                rename_file(args)


if __name__ == "__main__":
    unittest.main()
