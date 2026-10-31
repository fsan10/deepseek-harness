from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

from apps.file_ingest.service import ConflictError, FileIngestService
from apps.identity_access.permission_service import PermissionService


@unittest.skipUnless(os.getenv("RUN_DB_INTEGRATION") == "1", "需要显式启用数据库集成测试")
class FinanceBudgetIntegrationTests(unittest.TestCase):
    month = "2099-12-01"
    zero_budget_month = "2099-11-01"
    operator = "finance_budget_integration_test"

    @classmethod
    def setUpClass(cls):
        args = SimpleNamespace(
            host=os.getenv("PGHOST", "192.168.77.111"),
            pg_port=int(os.getenv("PGPORT", "5432")),
            dbname=os.getenv("PGDATABASE", "mock_coffice"),
            user=os.getenv("PGUSER", "postgres"),
            password=os.getenv("PGPASSWORD"),
        )
        cls.service = FileIngestService(args)
        with cls.service.transaction() as cursor:
            cursor.execute(
                """SELECT platform_code,company_code,shop_code,platform_name,company_name,shop_name
                     FROM dim.dim_platform_shop_company
                    WHERE is_active AND valid_from<=%s::date
                      AND (valid_to IS NULL OR valid_to>=%s::date)
                    ORDER BY shop_company_sk LIMIT 1""",
                (cls.month, cls.month),
            )
            row = cursor.fetchone()
            if not row:
                raise unittest.SkipTest("没有可用于2099-12的有效DIM店铺")
            cls.dim_shop = dict(row)
            cursor.execute(
                """SELECT COUNT(*) AS total
                     FROM dim.dim_platform_shop_company
                    WHERE is_active AND valid_from<=%s::date
                      AND (valid_to IS NULL OR valid_to>=%s::date)""",
                (cls.month, cls.month),
            )
            cls.dim_shop_count = int(cursor.fetchone()["total"])
        cls.cleanup()

    @classmethod
    def cleanup(cls):
        with cls.service.transaction() as cursor:
            cursor.execute("DELETE FROM config.finance_marketing_expense_detail WHERE created_by=%s OR updated_by=%s", (cls.operator, cls.operator))
            cursor.execute("DELETE FROM config.finance_promotion_recharge_detail WHERE created_by=%s OR updated_by=%s", (cls.operator, cls.operator))
            cursor.execute("DELETE FROM config.finance_promotion_budget_adjustment WHERE created_by=%s OR updated_by=%s", (cls.operator, cls.operator))
            cursor.execute("DELETE FROM config.finance_marketing_budget_change_history WHERE changed_by=%s", (cls.operator,))
            cursor.execute("DELETE FROM config.finance_marketing_expense_type WHERE created_by=%s OR updated_by=%s", (cls.operator, cls.operator))
            cursor.execute("DELETE FROM config.finance_shop_plan_monthly WHERE created_by=%s OR updated_by=%s", (cls.operator, cls.operator))
            cursor.execute(
                "DELETE FROM config.finance_budget_monthly WHERE budget_month=ANY(%s::date[]) AND (created_by=%s OR updated_by=%s)",
                ([cls.month, cls.zero_budget_month], cls.operator, cls.operator),
            )
            cursor.execute("DELETE FROM ops.operation_log WHERE operator=%s", (cls.operator,))
            cls.service._refresh_finance_configuration(cursor)

    @classmethod
    def tearDownClass(cls):
        cls.cleanup()
        with cls.service.transaction() as cursor:
            cursor.execute(
                """SELECT
                    (SELECT COUNT(*) FROM config.finance_budget_monthly WHERE budget_month=%s AND (created_by=%s OR updated_by=%s)) +
                    (SELECT COUNT(*) FROM config.finance_shop_plan_monthly WHERE budget_month=%s AND (created_by=%s OR updated_by=%s)) +
                    (SELECT COUNT(*) FROM config.finance_promotion_budget_adjustment WHERE budget_month=%s AND (created_by=%s OR updated_by=%s)) +
                    (SELECT COUNT(*) FROM config.finance_marketing_budget_change_history WHERE budget_month=%s AND changed_by=%s) +
                    (SELECT COUNT(*) FROM config.finance_promotion_recharge_detail WHERE created_by=%s OR updated_by=%s) +
                    (SELECT COUNT(*) FROM config.finance_marketing_expense_detail WHERE created_by=%s OR updated_by=%s) +
                    (SELECT COUNT(*) FROM config.finance_marketing_expense_type WHERE created_by=%s OR updated_by=%s) +
                    (SELECT COUNT(*) FROM ops.operation_log WHERE operator=%s) AS residue""",
                (
                    cls.month, cls.operator, cls.operator,
                    cls.month, cls.operator, cls.operator,
                    cls.month, cls.operator, cls.operator,
                    cls.month, cls.operator,
                    cls.operator, cls.operator,
                    cls.operator, cls.operator,
                    cls.operator, cls.operator,
                    cls.operator,
                ),
            )
            if cursor.fetchone()["residue"] != 0:
                raise AssertionError("经营配置集成测试数据未完整清理")

    def test_full_dim_console_and_audited_updates(self):
        initial = self.service.save_finance_configuration(
            "budgets",
            {
                "budget_month": self.month,
                "promotion_budget_amount": 1000,
                "marketing_budget_amount": 400,
                "gsv_target_amount": 2000,
                "remark": "",
            },
            self.operator,
            "127.0.0.1",
        )
        self.service.save_finance_configuration(
            "budgets",
            {
                "budget_month": self.month,
                "promotion_budget_amount": 1200,
                "marketing_budget_amount": 400,
                "gsv_target_amount": 2000,
                "permission_action": "promotion_total",
                "remark": "集成测试",
                "updated_at": initial["updated_at"],
            },
            self.operator,
            "127.0.0.1",
        )
        with self.assertRaisesRegex(ValueError, "必须填写备注"):
            self.service.save_finance_configuration(
                "budgets",
                {
                    "budget_month": self.month,
                    "promotion_budget_amount": 1250,
                    "permission_action": "promotion_total",
                },
                self.operator,
                "127.0.0.1",
            )

        dim = self.dim_shop
        target = self.service.save_finance_configuration(
            "gsv-targets",
            {
                "budget_month": self.month,
                "platform_code": dim["platform_code"],
                "company_code": dim["company_code"],
                "shop_code": dim["shop_code"],
                "gsv_target_amount": 1500,
                "permission_action": "gsv_detail",
            },
            self.operator,
            "127.0.0.1",
        )
        plan = self.service.save_finance_configuration(
            "shop-budgets",
            {
                "budget_month": self.month,
                "platform_code": dim["platform_code"],
                "company_code": dim["company_code"],
                "shop_code": dim["shop_code"],
                "promotion_budget_amount": 800,
                "gsv_target_amount": 1500,
                "permission_action": "shop_budget",
                "updated_at": target["updated_at"],
            },
            self.operator,
            "127.0.0.1",
        )
        recharge = self.service.save_finance_configuration(
            "recharges",
            {
                "recharge_date": "2099-12-05",
                "platform_code": dim["platform_code"],
                "company_code": dim["company_code"],
                "shop_code": dim["shop_code"],
                "recharge_amount": 300,
                "document_no": "TEST-R-1",
                "permission_action": "promotion_recharge",
            },
            self.operator,
            "127.0.0.1",
        )

        with self.service.transaction() as cursor:
            cursor.execute("SELECT expense_type_code FROM config.finance_marketing_expense_type WHERE is_active ORDER BY expense_type_id LIMIT 1")
            expense_type = cursor.fetchone()["expense_type_code"]
        marketing = self.service.save_finance_configuration(
            "marketing-expenses",
            {
                "expense_date": "2099-12-07",
                "expense_amount": 125,
                "expense_type": expense_type,
                "permission_action": "marketing_expense",
            },
            self.operator,
            "127.0.0.1",
        )
        marketing_budget = self.service.save_finance_configuration(
            "budgets",
            {
                "budget_month": self.month,
                "marketing_budget_amount": 500,
                "permission_action": "marketing_budget",
                "remark": "营销预算二次调整",
            },
            self.operator,
            "127.0.0.1",
        )
        self.assertEqual(marketing_budget["budget_month"].isoformat(), self.month)

        summary = self.service.finance_configuration_summary({"budget_month": self.month})
        overall = summary["global"]
        self.assertEqual(float(overall["effective_promotion_budget_amount"]), 1200.0)
        self.assertEqual(float(overall["allocated_promotion_budget_amount"]), 800.0)
        self.assertEqual(float(overall["recharge_amount"]), 300.0)
        self.assertEqual(float(overall["pending_recharge_amount"]), 900.0)
        self.assertEqual(float(overall["marketing_remaining_amount"]), 375.0)
        self.assertEqual(len(summary["shops"]), self.dim_shop_count)
        shop = next(row for row in summary["shops"] if row["shop_code"] == dim["shop_code"])
        self.assertEqual(float(shop["gsv_target_amount"]), 1500.0)
        self.assertEqual(float(shop["pending_recharge_amount"]), 500.0)
        self.assertEqual(float(summary["actuals"]["shop_gsv_target_amount"]), 1500.0)

        gsv_rows = self.service.list_finance_configuration("gsv-targets", {"budget_month": self.month, "page_size": 200})
        shop_budget_rows = self.service.list_finance_configuration("shop-budgets", {"budget_month": self.month, "page_size": 200})
        recharge_rows = self.service.list_finance_configuration("recharges", {"budget_month": self.month, "page_size": 200})
        self.assertEqual(gsv_rows["pagination"]["total"], self.dim_shop_count)
        self.assertEqual(shop_budget_rows["pagination"]["total"], self.dim_shop_count)
        self.assertEqual(recharge_rows["pagination"]["total"], self.dim_shop_count)
        recharge_history = self.service.list_finance_configuration(
            "recharges", {"console": "false", "shop_code": dim["shop_code"], "page_size": 200}
        )
        self.assertGreaterEqual(recharge_history["pagination"]["total"], 1)
        history_item = next(
            item for item in recharge_history["items"] if item["recharge_id"] == recharge["recharge_id"]
        )
        self.assertEqual(float(history_item["recharge_amount"]), 300.0)
        self.assertEqual(next(row for row in shop_budget_rows["items"] if row["shop_code"] == dim["shop_code"])["shop_plan_id"], plan["shop_plan_id"])
        filtered = self.service.list_finance_configuration(
            "gsv-targets",
            {
                "budget_month": self.month,
                "platform_codes": dim["platform_code"],
                "company_codes": dim["company_code"],
                "shop_codes": dim["shop_code"],
            },
        )
        self.assertEqual(filtered["pagination"]["total"], 1)
        self.assertTrue(filtered["items"][0]["target_is_set"])

        adjustments = self.service.list_finance_configuration("adjustments", {"budget_month": self.month, "keyword": "集成测试"})
        self.assertEqual(adjustments["pagination"]["total"], 1)
        self.assertEqual(float(adjustments["items"][0]["before_amount"]), 1000.0)
        self.assertEqual(float(adjustments["items"][0]["after_amount"]), 1200.0)
        self.assertEqual(float(adjustments["items"][0]["adjustment_amount"]), 200.0)
        self.assertEqual(adjustments["items"][0]["change_type"], "budget_update")
        histories = self.service.list_finance_marketing_budget_history({"budget_month": self.month})
        self.assertEqual(histories["pagination"]["total"], 1)
        self.assertEqual(float(histories["items"][0]["change_amount"]), 100.0)

        marketing_filtered = self.service.list_finance_configuration("marketing-expenses", {"budget_month": self.month})
        self.assertEqual(marketing_filtered["items"][0]["marketing_expense_id"], marketing["marketing_expense_id"])
        marketing_multi_filtered = self.service.list_finance_configuration(
            "marketing-expenses", {"budget_month": self.month, "expense_type": [expense_type, "not_a_real_type"]}
        )
        self.assertEqual(marketing_multi_filtered["pagination"]["total"], 1)
        self.service.delete_finance_configuration("recharges", str(recharge["recharge_id"]), self.operator, "127.0.0.1")
        summary = self.service.finance_configuration_summary({"budget_month": self.month})
        self.assertEqual(float(summary["global"]["recharge_amount"]), 0.0)

    def test_expense_type_is_managed_and_inactive_types_are_rejected(self):
        seeded = self.service.list_finance_expense_types({"page": 1, "page_size": 200})
        self.assertTrue(any(item["expense_type_name"] == "达人合作" for item in seeded["items"]))
        created = self.service.save_finance_configuration(
            "expense-types",
            {"expense_type_name": "集成测试费用类型", "remark": "测试类型"},
            self.operator,
            "127.0.0.1",
        )
        listed = self.service.list_finance_expense_types({"keyword": "集成测试费用类型"})
        self.assertEqual(listed["pagination"]["total"], 1)
        self.assertEqual(listed["items"][0]["expense_type_id"], created["expense_type_id"])
        self.service.save_finance_configuration(
            "expense-types",
            {
                "expense_type_name": "集成测试费用类型",
                "is_active": False,
                "updated_at": created["updated_at"],
            },
            self.operator,
            "127.0.0.1",
            str(created["expense_type_id"]),
        )
        with self.assertRaises(ConflictError):
            self.service.save_finance_configuration(
                "marketing-expenses",
                {
                    "expense_date": "2099-12-08",
                    "expense_amount": 10,
                    "expense_type": created["expense_type_code"],
                    "permission_action": "marketing_expense",
                },
                self.operator,
                "127.0.0.1",
            )
        deleted = self.service.delete_finance_configuration(
            "expense-types", str(created["expense_type_id"]), self.operator, "127.0.0.1"
        )
        self.assertTrue(deleted["deleted"])
        self.assertEqual(
            self.service.list_finance_expense_types({"keyword": "集成测试费用类型"})["pagination"]["total"],
            0,
        )

    def test_existing_zero_budget_is_not_treated_as_first_setting(self):
        initial = self.service.save_finance_configuration(
            "budgets",
            {
                "budget_month": self.zero_budget_month,
                "promotion_budget_amount": 0,
                "marketing_budget_amount": 0,
                "gsv_target_amount": 0,
                "remark": "",
            },
            self.operator,
            "127.0.0.1",
        )
        with self.assertRaisesRegex(ValueError, "必须填写备注"):
            self.service.save_finance_configuration(
                "budgets",
                {
                    "budget_month": self.zero_budget_month,
                    "promotion_budget_amount": 100,
                    "permission_action": "promotion_total",
                    "updated_at": initial["updated_at"],
                },
                self.operator,
                "127.0.0.1",
            )
        with self.assertRaisesRegex(ValueError, "必须填写备注"):
            self.service.save_finance_configuration(
                "budgets",
                {
                    "budget_month": self.zero_budget_month,
                    "marketing_budget_amount": 100,
                    "permission_action": "marketing_budget",
                    "updated_at": initial["updated_at"],
                },
                self.operator,
                "127.0.0.1",
            )

    def test_all_metric_table_columns_have_comments(self):
        with self.service.transaction() as cursor:
            cursor.execute(
                """SELECT COUNT(*) AS missing_count
                   FROM information_schema.columns c
                  WHERE c.table_schema IN ('config','dwd','dws','ads')
                    AND c.table_name IN (
                      'finance_budget_monthly','finance_shop_plan_monthly',
                      'finance_promotion_recharge_detail','finance_promotion_budget_adjustment',
                      'finance_marketing_expense_detail','finance_marketing_budget_change_history',
                      'finance_marketing_expense_type',
                      'dwd_finance_operating_configuration_detail',
                      'dws_finance_operating_shop_monthly','dws_finance_operating_global_monthly',
                      'ads_finance_promotion_budget_company_shop_monthly','ads_finance_budget_global_monthly')
                    AND col_description(format('%I.%I',c.table_schema,c.table_name)::regclass::oid,c.ordinal_position) IS NULL"""
            )
            self.assertEqual(cursor.fetchone()["missing_count"], 0)

    def test_finance_permission_catalog_is_final_and_old_resources_are_hidden(self):
        final_pages = {
            "finance_budget.overview.view", "finance_budget.gsv.view", "finance_budget.promotion.view",
            "finance_budget.adjustment.view", "finance_budget.recharge.view",
            "finance_budget.spend.view", "finance_budget.marketing.view", "finance_budget.expense_type.view",
        }
        final_actions = {
            "finance_budget.gsv_total.manage", "finance_budget.gsv_detail.manage",
            "finance_budget.promotion_total.manage", "finance_budget.shop_budget.manage",
            "finance_budget.promotion_recharge.manage", "finance_budget.marketing_budget.manage",
            "finance_budget.marketing_expense.manage", "finance_budget.expense_type.manage",
        }
        legacy = {
            "finance_budget.view", "finance_budget.manage", "finance_budget.total.manage",
            "finance_budget.detail.manage", "finance_budget.promotion_detail.manage",
            "finance_budget.promotion_adjust.manage", "finance_budget.shop_budget.view",
        }
        with self.service.transaction() as cursor:
            cursor.execute(
                "SELECT resource_code,is_active FROM iam.permission_resource WHERE resource_code=ANY(%s)",
                (list(final_pages | final_actions | legacy),),
            )
            resources = {row["resource_code"]: row["is_active"] for row in cursor.fetchall()}
        self.assertTrue(final_pages | final_actions <= resources.keys())
        self.assertTrue(all(resources[code] for code in final_pages | final_actions))
        self.assertTrue(all(not resources.get(code, False) for code in legacy))

        permission_service = PermissionService(self.service, None)
        context = SimpleNamespace(can=lambda _permission: True)
        visible = {item["resource_code"] for item in permission_service.resources(context)["flat_items"]}
        self.assertTrue(final_pages | final_actions <= visible)
        self.assertTrue(legacy.isdisjoint(visible))


if __name__ == "__main__":
    unittest.main()
