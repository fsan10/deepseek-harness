import unittest
from pathlib import Path
from types import SimpleNamespace

from apps.identity_access.navigation import build_navigation


STATIC = Path(__file__).resolve().parents[1] / "static"
ROOT = Path(__file__).resolve().parents[3]


class FinanceBudgetUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.css = (STATIC / "ingest.css").read_text(encoding="utf-8")
        cls.javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        cls.navigation = (ROOT / "apps/identity_access/navigation.py").read_text(encoding="utf-8")
        cls.shell = (ROOT / "apps/identity_access/static/shell.js").read_text(encoding="utf-8")

    def test_eight_finance_pages_and_routes_exist(self):
        self.assertIn('id="financeBudgetPage"', self.html)
        for page, view in (
            ("financeOverview", "financeOverviewView"),
            ("financeGsv", "financeGsvView"),
            ("financePromotion", "financePromotionView"),
            ("financeAdjustments", "financeAdjustmentsView"),
            ("financeRecharges", "financeRechargesView"),
            ("financeSpend", "financeSpendView"),
            ("financeMarketing", "financeMarketingView"),
            ("financeExpenseTypes", "financeExpenseTypesView"),
        ):
            self.assertIn(f'data-page="{page}"', self.html)
            self.assertIn(f'id="{view}"', self.html)
        self.assertIn("activateFinanceView", self.javascript)

    def test_eight_pages_are_registered_in_shared_navigation(self):
        expected = (
            ("overview", "finance_budget.overview.view", "经营指标总览", "financeOverview"),
            ("gsv", "finance_budget.gsv.view", "GSV目标管理", "financeGsv"),
            ("promotion", "finance_budget.promotion.view", "推广预算管理", "financePromotion"),
            ("adjustment", "finance_budget.adjustment.view", "预算调整记录", "financeAdjustments"),
            ("recharge", "finance_budget.recharge.view", "充值流水", "financeRecharges"),
            ("spend", "finance_budget.spend.view", "推广消耗", "financeSpend"),
            ("marketing", "finance_budget.marketing.view", "营销预算管理", "financeMarketing"),
            ("expense_type", "finance_budget.expense_type.view", "营销费用类型管理", "financeExpenseTypes"),
        )
        for key, permission, label, route in expected:
            self.assertIn(f'(FINANCE_PAGE_PERMISSIONS["{key}"], "{label}", "/ingest/#{route}")', self.navigation)
            self.assertIn(f"{route}:'{permission}'", self.shell)
        self.assertNotIn('"预算与目标管理", "/ingest/#financeBudget"', self.navigation)

    def test_verification_relay_page_is_registered_in_shared_navigation(self):
        self.assertIn('(\"ai.feishu_app.manage\", \"验证码转发机器人\", \"/ai-admin/#verificationRelays\")', self.navigation)
        self.assertIn("verificationRelays:'ai.feishu_app.manage'", self.shell)
        context = SimpleNamespace(
            permissions={"ai.feishu_app.manage"},
            can=lambda permission: permission == "ai.feishu_app.manage",
            public_user=lambda: {"display_name": "测试用户"},
        )
        dashboards = SimpleNamespace(permitted=lambda _context: {"items": []})
        navigation = build_navigation(context, dashboards)
        group = next(item for item in navigation["groups"] if item["code"] == "ai")
        self.assertIn(
            ("验证码转发机器人", "/ai-admin/#verificationRelays"),
            [(item["name"], item["href"]) for item in group["items"]],
        )

    def test_authorized_user_receives_all_eight_runtime_navigation_items(self):
        context = SimpleNamespace(
            permissions={
                "finance_budget.overview.view", "finance_budget.gsv.view",
                "finance_budget.promotion.view",
                "finance_budget.adjustment.view", "finance_budget.recharge.view",
                "finance_budget.spend.view", "finance_budget.marketing.view",
                "finance_budget.expense_type.view",
            },
            can=lambda permission: permission in {
                "finance_budget.overview.view", "finance_budget.gsv.view",
                "finance_budget.promotion.view",
                "finance_budget.adjustment.view", "finance_budget.recharge.view",
                "finance_budget.spend.view", "finance_budget.marketing.view",
                "finance_budget.expense_type.view",
            },
            public_user=lambda: {"display_name": "测试用户"},
        )
        dashboards = SimpleNamespace(permitted=lambda _context: {"items": []})
        navigation = build_navigation(context, dashboards)
        group = next(item for item in navigation["groups"] if item["code"] == "operating_config")
        self.assertEqual(
            [(item["name"], item["href"]) for item in group["items"]],
            [
                ("经营指标总览", "/ingest/#financeOverview"),
                ("GSV目标管理", "/ingest/#financeGsv"),
                ("推广预算管理", "/ingest/#financePromotion"),
                ("预算调整记录", "/ingest/#financeAdjustments"),
                ("充值流水", "/ingest/#financeRecharges"),
                ("推广消耗", "/ingest/#financeSpend"),
                ("营销预算管理", "/ingest/#financeMarketing"),
                ("营销费用类型管理", "/ingest/#financeExpenseTypes"),
            ],
        )

    def test_figma_page_sections_and_actions_exist(self):
        for element_id in (
            "financeSummaryCards",
            "financeExecutionCards",
            "financeAlertList",
            "financeManagementPanel",
            "financeGsvStats",
            "financePromotionFlow",
            "financePromotionStats",
            "financeMarketingStats",
            "financeMarketingProgressBar",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        for button_id in (
            "importGsvTargets",
            "addGsvTotalTarget",
            "addMarketingExpense",
            "editMarketingBudgetTop",
            "editMarketingBudget",
        ):
            self.assertIn(f'id="{button_id}"', self.html)
        self.assertIn('id="setPromotionTotalBudget"', self.javascript)
        self.assertIn("renderFinanceOverview", self.javascript)
        self.assertIn("finance-quick-actions [data-finance-total]", self.javascript)
        self.assertIn("removeAttribute('data-finance-route')", self.javascript)
        self.assertIn("renderFinanceViewSummaries", self.javascript)
        self.assertIn("renderFinanceConsoleTable", self.javascript)
        self.assertIn("marketing-budget-history", self.javascript)
        self.assertIn("bindFinanceConsole", self.javascript)
        self.assertIn("exportFinanceConfig", self.javascript)
        self.assertIn("importGsvTargets", self.javascript)
        self.assertNotIn("financeTabs", self.html)
        self.assertIn('aria-label="预算调整记录子页面"', self.html)
        self.assertIn('data-finance-adjustment-tab="marketing"', self.html)

    def test_category_page_components_are_reused(self):
        self.assertIn('class="data-table category-table finance-data-table"', self.html)
        self.assertIn('id="financeConfigPageSize" class="select-chevron pagination-size"', self.html)
        self.assertIn('class="pagination-nav"', self.html)
        self.assertIn("finance-detail-manage-action", self.javascript)
        self.assertIn("finance-total-manage-action", self.javascript)
        self.assertIn("renderPagination('financeConfigPageNumbers'", self.javascript)

    def test_each_recharge_shop_can_open_all_history(self):
        for element_id in (
            "financeRechargeHistoryDialog",
            "financeRechargeHistoryBody",
            "financeRechargeHistoryPageNumbers",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn("历史记录", self.javascript)
        self.assertIn("openFinanceRechargeHistory", self.javascript)
        self.assertIn("console:'false'", self.javascript)
        self.assertIn("shop_code:shopCode", self.javascript)
        self.assertIn("financeRechargeHistoryPageSize", self.javascript)
        self.assertIn("financeRechargeHistoryDialog", self.css + self.javascript)

    def test_finance_interactions_and_motion_have_accessible_fallbacks(self):
        self.assertIn('aria-label="经营配置月份"', self.html)
        self.assertIn('id="financeDialogSubmit"', self.html)
        self.assertIn('id="financeDialogNotice"', self.html)
        self.assertIn("prefers-reduced-motion:reduce", self.css)
        self.assertIn("financeDialogIn", self.css)
        self.assertIn("financeViewIn", self.css)
        self.assertIn("finance-progress-fill.is-ready", self.css)
        self.assertIn("bindNativePicker", self.javascript)
        self.assertIn("showPicker", self.javascript)
        self.assertIn("currentMonthValue", self.javascript)
        self.assertIn('id="financeAssignDropdown"', self.html)
        self.assertIn("不会创建新数据", self.javascript)
        self.assertIn("types.join(',')", self.javascript)
        self.assertIn("ensureFinanceExpenseTypes", self.javascript)
        self.assertIn("financeAssignDropdownHost", self.javascript)
        self.assertIn("drop.closest('#financeConfigDialog')", self.javascript)
        self.assertIn("finance-dialog-dropdown", self.javascript)
        self.assertIn(".finance-assign-dropdown.finance-dialog-dropdown { position:absolute; }", self.css)
        self.assertIn("financeContextDialogBase", self.javascript)
        self.assertIn("hiddenFields=mode==='gsv'||mode==='promotion-allocation'", self.javascript)
        self.assertIn("mode==='recharges'?['platform_context','company_context','shop_code']", self.javascript)
        self.assertIn("deleteFinanceExpenseType", self.javascript)
        self.assertIn("data-finance-type-delete", self.javascript)
        self.assertIn("financeConfigBody').addEventListener('click'", self.javascript)
        self.assertIn('class="finance-form-field" data-finance-field="platform_context"', self.html)
        self.assertIn('class="finance-form-field" data-finance-field="company_context"', self.html)
        self.assertIn('class="finance-form-field" data-finance-field="shop_code"', self.html)

    def test_business_definitions_are_visible_in_page_copy(self):
        self.assertIn("待充值", self.javascript)
        self.assertIn("待充值：</strong>店铺分配预算 - 店铺累计充值", self.javascript)
        self.assertIn("理论余额：</strong>累计充值 - 实际推广消耗", self.javascript)
        self.assertIn("不拆分平台、店铺和部门维度", self.html)
        self.assertIn("GSV目标", self.html)
        self.assertIn("DIM 当前月份全部有效店铺", self.html)
        self.assertIn("总预算", self.html)
        self.assertIn("不再存在待审批", self.html)
        self.assertNotIn('data-finance-total="gsv-total" data-finance-route=', self.html)
        self.assertNotIn('data-finance-total="promotion-total" data-finance-route=', self.html)
        self.assertNotIn('data-finance-total="marketing-budget" data-finance-route=', self.html)
        self.assertIn('id="financeMethodologyCard"', self.html)
        self.assertNotIn("finance-calculation-note", self.html)
        self.assertNotIn("finance-dialog-kicker", self.html)
        self.assertIn("财务月度总目标", self.javascript)
        self.assertNotIn('id="financeShopBudgetStats"', self.html)
        self.assertNotIn('id="financeMarketingHistoryBody"', self.html)

    def test_dialog_modes_and_batch_import_are_implemented(self):
        for mode in (
            "gsv-total",
            "promotion-total",
            "promotion-allocation",
            "recharges",
            "marketing-expenses",
            "marketing-budget",
        ):
            self.assertIn(mode, self.javascript)
        self.assertIn("parseCsvRows", self.javascript)
        self.assertIn('id="financeBatchFile"', self.html)
        self.assertNotIn('name="financeAdjustmentKind"', self.html)

    def test_operating_configuration_icon_and_split_permissions(self):
        self.assertIn('("operating_config", "经营配置", "target"', self.navigation)
        self.assertIn("🎯", self.html)
        for permission in (
            "finance_budget.gsv_total.manage", "finance_budget.gsv_detail.manage",
            "finance_budget.promotion_total.manage", "finance_budget.shop_budget.manage",
            "finance_budget.promotion_recharge.manage",
            "finance_budget.marketing_budget.manage", "finance_budget.marketing_expense.manage",
            "finance_budget.expense_type.manage",
        ):
            self.assertIn(permission, self.shell + self.javascript + self.html)


if __name__ == "__main__":
    unittest.main()
