from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class SharedFrontendContractTests(unittest.TestCase):
    def test_health_fetch_exists_only_in_shared_shell(self):
        shell = (ROOT / "apps/identity_access/static/shell.js").read_text(encoding="utf-8")
        self.assertEqual(shell.count("nativeFetch('/api/health'"), 1)
        for relative in (
            "apps/fund_split_adjust/static/app.js",
            "apps/influencer_config/static/app.js",
            "apps/file_ingest/static/app.js",
        ):
            content = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("/api/health", content)
            self.assertNotIn("/api/ingest/health", content)
        ingest = (ROOT / "apps/file_ingest/static/app.js").read_text(encoding="utf-8")
        self.assertIn("health:change", ingest)

    def test_dashboard_uses_embed_proxy_without_layout_replacement(self):
        script = (ROOT / "apps/dashboard_center/static/dashboard.js").read_text(encoding="utf-8")
        page = (ROOT / "apps/dashboard_center/static/index.html").read_text(encoding="utf-8")
        self.assertIn("embedUrl(current.embed)", script)
        self.assertIn('id="dashboardFrame"', page)
        self.assertIn('id="fullscreenDashboard"', page)

    def test_system_management_actions_and_save_feedback_are_wired(self):
        core = (ROOT / "apps/identity_access/static/system-core.js").read_text(encoding="utf-8")
        iam = (ROOT / "apps/identity_access/static/system-iam.js").read_text(encoding="utf-8")
        dashboards = (ROOT / "apps/identity_access/static/system-dashboards.js").read_text(encoding="utf-8")
        styles = (ROOT / "apps/identity_access/static/system.css").read_text(encoding="utf-8")
        self.assertIn("parseAction(value)", core)
        self.assertIn("compound.indexOf('-')", core)
        self.assertGreaterEqual(iam.count("A.parseAction(button.dataset.action)"), 3)
        self.assertIn("权限已保存并立即生效", iam)
        self.assertIn("保存中…", iam)
        self.assertIn("system.user.password.view", iam)
        self.assertIn("user-view-password", iam)
        self.assertIn("toggleInitialPassword", iam)
        self.assertIn("不填写则使用系统默认初始密码", iam)
        self.assertIn("'#i-eye'", iam)
        self.assertIn('href="#i-eye-off"', iam)
        self.assertIn("is-visible", iam)
        self.assertIn("aria-pressed", iam)
        self.assertIn("看板已保存", dashboards)
        self.assertIn("switch-control", dashboards)
        self.assertNotIn("系统编码", dashboards)
        self.assertNotIn('name="dashboard_code"', dashboards)
        self.assertIn("text-overflow:ellipsis", styles)

    def test_platform_shop_company_management_contract(self):
        page = (ROOT / "apps/identity_access/static/system.html").read_text(encoding="utf-8")
        script = (ROOT / "apps/identity_access/static/system-platform-shop-company.js").read_text(encoding="utf-8")
        shell = (ROOT / "apps/identity_access/static/shell.js").read_text(encoding="utf-8")
        self.assertIn('data-page="platformShopCompany"', page)
        self.assertIn('data-permission="system.platform_shop_company.manage"', page)
        self.assertIn("/api/system/platform-shop-companies", script)
        self.assertIn("create_version:true", script)
        self.assertIn("不自动刷新ADS或看板", page)
        self.assertIn("platformShopCompany:'system.platform_shop_company.view'", shell)

    def test_edit_modal_enable_controls_use_dashboard_switch_contract(self):
        dashboard = (ROOT / "apps/identity_access/static/system-dashboards.js").read_text(encoding="utf-8")
        expected_tokens = ('class="switch-field"', 'class="switch-control"', 'class="switch-track"')
        for token in expected_tokens:
            self.assertIn(token, dashboard)

        forms = {
            "bank expense type": (ROOT / "apps/fund_split_adjust/static/app.js").read_text(encoding="utf-8"),
            "ingest category and expense type": (ROOT / "apps/file_ingest/static/index.html").read_text(encoding="utf-8"),
        }
        for name, content in forms.items():
            with self.subTest(name=name):
                for token in expected_tokens:
                    self.assertIn(token, content)
        bank = forms["bank expense type"]
        ingest = forms["ingest category and expense type"]
        ingest_script = (ROOT / "apps/file_ingest/static/app.js").read_text(encoding="utf-8")
        self.assertNotIn("modal-radio-group", bank)
        self.assertNotIn('id="categoryFormActive"><option', ingest)
        self.assertNotIn('id="financeExpenseTypeActive"><option', ingest)
        self.assertIn('$("#typeActive").checked', bank)
        self.assertIn("$('categoryFormActive').checked", ingest_script)
        self.assertIn("$('financeExpenseTypeActive').checked", ingest_script)

    def test_no_permission_welcome_and_login_cooldown_contract(self):
        welcome = (ROOT / "apps/identity_access/static/welcome.html").read_text(encoding="utf-8")
        login = (ROOT / "apps/identity_access/static/login.js").read_text(encoding="utf-8")
        shell = (ROOT / "apps/identity_access/static/shell.js").read_text(encoding="utf-8")
        self.assertIn("当前没有分配业务页面权限", welcome)
        self.assertIn("/welcome/", login)
        self.assertIn("Retry-After", login)
        self.assertIn("if (submitting || readNumber('cooldown') > Date.now())", login)
        self.assertIn("sessionStorage.removeItem('mocc_navigation_cache_v1')", login)
        self.assertIn("sessionStorage.removeItem(NAV_CACHE_KEY)", shell)

    def test_product_configuration_reports_before_background_refresh(self):
        script = (ROOT / "apps/influencer_config/static/product-category.js").read_text(encoding="utf-8")
        self.assertIn("if (message) notifyMutation(message, refresh);", script)
        self.assertIn("Promise.all([refreshMetadata(), activeViewRequest()])", script)
        self.assertIn('app().api("/api/refresh-status")', script)
        self.assertIn("看板数据刷新完成", script)

    def test_ai_audit_subnav_uses_shared_segmented_style(self):
        page = (ROOT / "apps/ai_admin/static/index.html").read_text(encoding="utf-8")
        stylesheet = (ROOT / "apps/ai_admin/static/admin.css").read_text(encoding="utf-8")
        self.assertIn('aria-label="AI 会话与审计子页面"', page)
        self.assertIn('data-audit-view="conversations"', page)
        self.assertIn("width:max-content", stylesheet)
        self.assertIn("gap:4px", stylesheet)
        self.assertIn(".catalog-subtab.is-active::after{display:none}", stylesheet)

    def test_ai_audit_layout_matches_master_subnav_order(self):
        page = (ROOT / "apps/ai_admin/static/index.html").read_text(encoding="utf-8")
        audit = page[page.index('<section data-page="audit"'):]
        self.assertLess(audit.index('<nav class="catalog-subnav"'), audit.index('<div class="toolbar">'))
        for heading in ("会话", "只读查询", "飞书消息事件与每日报告"):
            self.assertNotIn(f"<h3>{heading}</h3>", audit)


if __name__ == "__main__":
    unittest.main()
