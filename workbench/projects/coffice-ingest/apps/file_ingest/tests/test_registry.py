from __future__ import annotations

import ast
import unittest
from collections import Counter

from apps.file_ingest.registry import (
    ACTIVE_REPORTS,
    DEPRECATED_LOADERS,
    ETL_SPECS,
    PROJECT_ROOT,
    full_refresh_etl_keys,
    plan_etls,
)


class RegistryTests(unittest.TestCase):
    def test_27_active_and_four_explicit_legacy_loaders(self):
        self.assertEqual(27, len(ACTIVE_REPORTS))
        self.assertEqual(
            {
                "etl/tmall/load_tmall_fund_ods.py",
                "etl/xhs/load_xhs_fund_ods.py",
                "etl/xhs/load_xhs_settlement_income_ods.py",
                "etl/xhs/load_xhs_settlement_expense_ods.py",
            },
            set(DEPRECATED_LOADERS),
        )
        self.assertNotIn("etl/tmall/load_tmall_fund_ods.py", {item.loader for item in ACTIVE_REPORTS})

    def test_registry_matches_all_ecommerce_loader_files(self):
        disk_loaders = {
            path.relative_to(PROJECT_ROOT).as_posix()
            for path in (PROJECT_ROOT / "etl").glob("*/load_*_ods.py")
            if path.parent.name != "bank"
        }
        self.assertEqual(disk_loaders, {item.loader for item in ACTIVE_REPORTS} | set(DEPRECATED_LOADERS))

    def test_platform_counts_and_tmall_funds(self):
        self.assertEqual(
            {"douyin": 4, "jd": 5, "tmall": 7, "ks": 3, "pdd": 3, "wechat_channels": 2, "xhs": 3},
            Counter(item.platform_code for item in ACTIVE_REPORTS),
        )
        tmall = {item.report_type: item.loader for item in ACTIVE_REPORTS if item.platform_code == "tmall"}
        self.assertEqual("etl/tmall/load_tmall_alipay_fund_ods.py", tmall["tmall_alipay_fund"])
        self.assertEqual("etl/tmall/load_tmall_aggregate_fund_ods.py", tmall["tmall_aggregate_fund"])
        self.assertNotIn("tmall_fund", tmall)

    def test_xhs_fund_uses_the_new_fund_ledger_loader(self):
        reports = {item.report_type: item for item in ACTIVE_REPORTS}
        fund = reports["xhs_fund"]
        self.assertEqual("etl/xhs/load_xhs_fund_ledger_ods.py", fund.loader)
        self.assertEqual("ods.ods_xhs_fund_ledger_raw", fund.target_table)
        self.assertEqual("资金账单明细", fund.default_sheet_name)

    def test_tmall_funds_feed_settlement_metrics(self):
        reports = {item.report_type: item for item in ACTIVE_REPORTS}
        self.assertIn("tmall_settlement_from_funds", reports["tmall_alipay_fund"].etl_keys)
        self.assertIn("tmall_settlement_from_funds", reports["tmall_aggregate_fund"].etl_keys)
        self.assertIn("tmall_settlement_from_funds", reports["tmall_settlement_income"].etl_keys)
        self.assertIn("tmall_settlement_from_funds", reports["tmall_settlement_expense"].etl_keys)
        planned = {item.key for item in plan_etls({"tmall_settlement_from_funds"})}
        self.assertIn("settlement_shared_ads", planned)

    def test_legacy_tmall_settlement_etl_is_retired(self):
        # 天猫旧结算单 ODS 已停止导入，结算指标统一由两张资金单链路
        # （tmall_settlement_from_funds）产出；旧 ODS 链路 ETL 已移除，
        # 不再进入全量刷新、七平台共享结算 ADS 前置或上传触发。
        self.assertNotIn("tmall_settlement", ETL_SPECS)
        self.assertNotIn("tmall_settlement", full_refresh_etl_keys())
        for report in ACTIVE_REPORTS:
            self.assertNotIn("tmall_settlement", report.etl_keys)
        from apps.file_ingest.registry import ETL_DEPENDENCIES, ETL_TASK_PREREQUISITES
        self.assertNotIn("tmall_settlement", ETL_DEPENDENCIES)
        for prerequisites in ETL_TASK_PREREQUISITES.values():
            self.assertNotIn("tmall_settlement", prerequisites)

    def test_wechat_channels_order_refreshes_gsv_promotion_expense_monthly_ads(self):
        from apps.file_ingest.registry import ETL_TASK_PREREQUISITES

        reports = {item.report_type: item for item in ACTIVE_REPORTS}
        self.assertIn("wechat_channels_gsv", reports["wechat_channels_order"].etl_keys)
        self.assertIn("promotion_expense", reports["wechat_channels_order"].etl_keys)
        self.assertIn(
            "wechat_channels_gsv",
            ETL_TASK_PREREQUISITES["promotion_expense"],
        )
        self.assertEqual(
            ["wechat_channels_gsv", "promotion_expense", "platform_bank_summary"],
            [item.key for item in plan_etls({"wechat_channels_gsv", "promotion_expense"})],
        )

    def test_settlement_shared_ads_waits_for_selected_settlement_tasks(self):
        planned = plan_etls({"jd_settlement", "pdd_settlement"})
        self.assertEqual(
            ["jd_settlement", "pdd_settlement", "settlement_shared_ads"],
            [item.key for item in planned],
        )

    def test_full_refresh_includes_all_settlement_closing_tasks(self):
        planned = {item.key for item in plan_etls(full_refresh_etl_keys())}
        self.assertIn("tmall_settlement_from_funds", planned)
        self.assertIn("settlement_shared_ads", planned)

    def test_registry_values_are_unique_and_paths_exist(self):
        self.assertEqual(len(ACTIVE_REPORTS), len({item.report_type for item in ACTIVE_REPORTS}))
        self.assertEqual(len(ACTIVE_REPORTS), len({(item.platform_code, item.report_name) for item in ACTIVE_REPORTS}))
        for item in ACTIVE_REPORTS:
            self.assertTrue((PROJECT_ROOT / item.loader).is_file(), item.loader)
            self.assertTrue(item.target_table.startswith("ods.ods_"), item.target_table)
            if item.target_tables:
                self.assertEqual(item.target_table, item.target_tables[0])
                self.assertGreater(len(item.target_tables), 1)
            self.assertLess(item.header_row_no, item.data_start_row_no)
            for key in item.etl_keys:
                self.assertIn(key, ETL_SPECS)
        for item in ETL_SPECS.values():
            self.assertTrue(item.command_path.is_file(), item.script)

    def test_sheet_and_header_parameters_match_loader_source(self):
        for item in ACTIVE_REPORTS:
            if item.target_tables:
                self.assertEqual("xhs_settlement", item.report_type)
                continue
            tree = ast.parse((PROJECT_ROOT / item.loader).read_text(encoding="utf-8"))
            values = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "OdsLoadConfig":
                    for keyword in node.keywords:
                        if keyword.arg in {"default_sheet_name", "header_row_no", "data_start_row_no"}:
                            values[keyword.arg] = ast.literal_eval(keyword.value)
            self.assertEqual(values.get("default_sheet_name"), item.default_sheet_name, item.loader)
            self.assertEqual(values.get("header_row_no", 1), item.header_row_no, item.loader)
            self.assertEqual(values.get("data_start_row_no", 2), item.data_start_row_no, item.loader)

    def test_full_refresh_reuses_submitted_bank_snapshot(self):
        keys = full_refresh_etl_keys()
        self.assertNotIn("bank_management", keys)
        self.assertNotIn("platform_bank_summary", keys)
        self.assertNotIn("finance_operating_config", keys)
        planned = plan_etls(keys)
        self.assertIn("platform_bank_summary", {item.key for item in planned})
        self.assertNotIn("bank_management", {item.key for item in planned})

    def test_bank_submit_plans_bank_then_summary(self):
        planned = plan_etls({"bank_management"})
        self.assertEqual(
            ["bank_management", "platform_bank_summary"],
            [item.key for item in planned],
        )

    def test_legacy_influencer_commission_is_disabled_but_retained(self):
        spec = ETL_SPECS["influencer_commission"]
        self.assertFalse(spec.enabled)
        self.assertTrue(spec.command_path.is_file())
        self.assertNotIn("influencer_commission", full_refresh_etl_keys())
        self.assertEqual([], plan_etls({"influencer_commission"}))
        for report in ACTIVE_REPORTS:
            self.assertNotIn("influencer_commission", report.etl_keys)

    def test_main_business_income_is_split_into_three_etls(self):
        self.assertTrue(ETL_SPECS["douyin_ks_main_business_income"].enabled)
        self.assertEqual(
            "etl/platform_finance/run_douyin_main_business_income_etl.py",
            ETL_SPECS["douyin_main_business_income"].script,
        )
        self.assertEqual(
            "etl/platform_finance/run_ks_main_business_income_etl.py",
            ETL_SPECS["ks_main_business_income"].script,
        )
        self.assertEqual(
            "etl/platform_finance/run_platform_main_business_income_shared_ads_etl.py",
            ETL_SPECS["platform_main_business_income_shared_ads"].script,
        )
        self.assertIn(
            "platform_main_business_income_shared_ads",
            {item.key for item in plan_etls({"douyin_main_business_income"})},
        )
        self.assertIn(
            "platform_bank_summary",
            {item.key for item in plan_etls({"ks_main_business_income"})},
        )
        reports = {item.report_type: item for item in ACTIVE_REPORTS}
        self.assertIn("douyin_main_business_income", reports["douyin_settlement"].etl_keys)
        self.assertIn("ks_main_business_income", reports["ks_settlement"].etl_keys)
        self.assertNotIn("douyin_ks_main_business_income", full_refresh_etl_keys())

    def test_shared_ads_waits_for_selected_platform_finance_feeders(self):
        from apps.file_ingest.registry import ETL_TASK_PREREQUISITES

        self.assertIn(
            "douyin_main_business_income",
            ETL_TASK_PREREQUISITES["platform_main_business_income_shared_ads"],
        )
        self.assertIn(
            "pdd_main_business_finance",
            ETL_TASK_PREREQUISITES["platform_main_business_income_shared_ads"],
        )
        self.assertIn(
            "wechat_channels_main_business_finance",
            ETL_TASK_PREREQUISITES["platform_main_business_income_shared_ads"],
        )
        self.assertIn(
            "xhs_main_business_finance",
            ETL_TASK_PREREQUISITES["platform_main_business_income_shared_ads"],
        )
        self.assertIn(
            "platform_main_business_income_shared_ads",
            {item.key for item in plan_etls({"jd_main_business_finance"})},
        )

    def test_pdd_wechat_xhs_main_business_finance_is_split(self):
        expected = {
            "pdd_main_business_finance": "etl/platform_finance/run_pdd_main_business_finance_etl.py",
            "wechat_channels_main_business_finance": "etl/platform_finance/run_wechat_channels_main_business_finance_etl.py",
            "xhs_main_business_finance": "etl/platform_finance/run_xhs_main_business_finance_etl.py",
        }
        for key, script in expected.items():
            with self.subTest(etl_key=key):
                self.assertEqual(script, ETL_SPECS[key].script)
                self.assertTrue(ETL_SPECS[key].command_path.is_file())
                self.assertIn(
                    "platform_main_business_income_shared_ads",
                    {item.key for item in plan_etls({key})},
                )
                self.assertIn(
                    "platform_bank_summary",
                    {item.key for item in plan_etls({key})},
                )

        self.assertTrue(ETL_SPECS["pdd_wechat_xhs_main_business_finance"].enabled)
        self.assertNotIn("pdd_wechat_xhs_main_business_finance", full_refresh_etl_keys())
        reports = {item.report_type: item for item in ACTIVE_REPORTS}
        self.assertIn("pdd_main_business_finance", reports["pdd_settlement"].etl_keys)
        self.assertIn(
            "wechat_channels_main_business_finance",
            reports["wechat_channels_settlement"].etl_keys,
        )
        self.assertIn("xhs_main_business_finance", reports["xhs_settlement"].etl_keys)
        self.assertNotIn(
            "pdd_wechat_xhs_main_business_finance",
            reports["pdd_settlement"].etl_keys
            + reports["wechat_channels_settlement"].etl_keys
            + reports["xhs_settlement"].etl_keys,
        )

    def test_each_platform_or_bank_feeder_plans_summary(self):
        feeders = {
            key for key, spec in ETL_SPECS.items()
            if spec.feeds_platform_bank_summary
        }
        self.assertTrue(feeders)
        for key in feeders:
            with self.subTest(etl_key=key):
                self.assertIn(
                    "platform_bank_summary",
                    {item.key for item in plan_etls({key})},
                )


if __name__ == "__main__":
    unittest.main()
