from __future__ import annotations

import unittest

from etl.platform_finance.run_pdd_wechat_xhs_main_business_finance_etl import (
    CREATE_SQL_FILES,
    REFRESH_SQL_FILES,
    files_for_scope,
    platforms_for_scope,
)


class PddWechatXhsMainBusinessFinanceEtlTests(unittest.TestCase):
    def test_each_platform_scope_excludes_other_platform_sql(self):
        platform_paths = {
            "pdd": ("pdd/", ("wechat_channels/", "xhs/")),
            "wechat_channels": ("wechat_channels/", ("pdd/", "xhs/")),
            "xhs": ("xhs/", ("pdd/", "wechat_channels/")),
        }
        for scope, (included, excluded) in platform_paths.items():
            with self.subTest(scope=scope):
                create_files, refresh_files = files_for_scope(scope)
                selected_files = (*create_files, *refresh_files)
                self.assertTrue(any(included in path for path in selected_files))
                self.assertIn(
                    "ads/platform_expense/311_ads_platform_expense_company_shop_daily_category_postgres.sql",
                    create_files,
                )
                self.assertIn(
                    "ads/platform_expense/312_refresh_ads_platform_expense_company_shop_daily_category_postgres.sql",
                    refresh_files,
                )
                for path in selected_files:
                    for forbidden in excluded:
                        self.assertNotIn(forbidden, path)

    def test_legacy_scope_keeps_all_sql(self):
        self.assertEqual((tuple(CREATE_SQL_FILES), tuple(REFRESH_SQL_FILES)), files_for_scope("legacy"))
        self.assertEqual(("pdd", "wechat_channels", "xhs"), platforms_for_scope("legacy"))

    def test_unknown_scope_is_rejected(self):
        with self.assertRaises(ValueError):
            files_for_scope("all")

    def test_xhs_scope_keeps_policy_shared_refresh_before_xhs_refresh(self):
        _create_files, refresh_files = files_for_scope("xhs")

        self.assertEqual(
            (
                "dim/340_seed_pdd_wechat_xhs_platform_fee_mapping_postgres.sql",
                "dim/425_xhs_appeal_adjustment_income_policy_postgres.sql",
                "dim/373_dim_platform_finance_source_policy_postgres.sql",
                "xhs/main_business_finance/351_refresh_dwd_xhs_main_business_finance_source_detail_postgres.sql",
                "xhs/main_business_finance/352_refresh_dws_xhs_main_business_finance_shop_daily_category_postgres.sql",
                "ads/platform_expense/312_refresh_ads_platform_expense_company_shop_daily_category_postgres.sql",
            ),
            refresh_files,
        )


if __name__ == "__main__":
    unittest.main()
