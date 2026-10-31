from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "static/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "static/app.js").read_text(encoding="utf-8")
        cls.reports = (ROOT / "static/reports.js").read_text(encoding="utf-8")
        cls.runtime = (ROOT / "static/runtime.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "static/styles.css").read_text(encoding="utf-8")
        cls.flow_css = (ROOT / "static/flow-studio.css").read_text(encoding="utf-8")
        cls.navigation = (PROJECT / "apps/identity_access/navigation.py").read_text(encoding="utf-8")

    def test_workbench_is_split_into_five_single_purpose_pages(self):
        for page in ("reportsPage", "runsPage", "schedulesPage", "flow-studioPage", "runtimePage"):
            self.assertIn(f'id="{page}"', self.html)
        for removed in ("workbenchPage", "faultsPage", "resourcesPage", "resultsPage"):
            self.assertNotIn(f'id="{removed}"', self.html)
        for label in ("报表任务", "运行中心", "任务调度", "流程编排", "系统运行"):
            self.assertIn(f'"{label}"', self.navigation)
        self.assertNotIn('"故障中心"', self.navigation)
        self.assertNotIn('"资源与队列"', self.navigation)

    def test_report_rows_toggle_expansion_and_refresh_entry_is_gone(self):
        self.assertNotIn('id="reportViewHint"', self.html)
        self.assertNotIn('id="refreshTargets"', self.html)
        self.assertNotIn("refreshTargets", self.reports)
        self.assertNotIn("refresh=1", self.reports)
        self.assertIn("if (block?.dataset.shop) toggleShop(block.dataset.shop);", self.reports)
        self.assertNotIn("if (block?.dataset.shop) openDrawer(block.dataset.shop);", self.reports)

    def test_report_page_has_list_and_calendar_views(self):
        for markup in ('data-report-view="list"', 'data-report-view="calendar"',
                       'id="reportShopRows"', 'id="calendarGrid"', 'id="calendarDayDetail"',
                       'id="reportDrawer"', 'id="reportDate"', 'id="calendarMonth"'):
            self.assertIn(markup, self.html, markup)
        for fragment in ("/api/automation/report-day", "/api/automation/report-calendar",
                         "/api/automation/report-settings", "data-shop-toggle", "data-shop-enable",
                         "data-report-backfill", "data-drawer-report", "data-report-page",
                         "reportPageSize", "renderReportPagination"):
            self.assertIn(fragment, self.reports, fragment)
        for markup in ('id="reportPagination"', 'id="reportPageSize"', 'id="reportPageNumbers"',
                       'id="reportPageInfo"', 'id="reportPrevPage"', 'id="reportNextPage"'):
            self.assertIn(markup, self.html, markup)

    def test_mutating_actions_are_permission_gated(self):
        for permission in ("automation.runs.execute", "automation.runs.retry", "automation.jobs.manage", "automation.flows.manage"):
            self.assertIn(permission, self.script + self.reports)
        self.assertIn("can('automation.jobs.manage')", self.reports)

    def test_needs_human_and_no_data_are_first_class_statuses(self):
        common = (ROOT / "static/common.js").read_text(encoding="utf-8")
        self.assertIn("needs_human: '等待人工'", common)
        self.assertIn("no_data: '无数据'", common)
        self.assertIn("statusTag", common)

    def test_pagination_never_reuses_sidebar_navigation_attribute(self):
        self.assertNotIn("dataset.page", self.script)
        self.assertNotIn("data-page=", self.script)
        self.assertNotIn("data-page=", self.html)
        self.assertIn("data-run-page=", self.script)
        self.assertIn("Number.isFinite(state.runPage)", self.script)

    def test_navigation_clicks_are_not_treated_as_pagination(self):
        self.assertIn("event.target.closest('main button')", self.script)
        self.assertNotIn("button.dataset.page", self.script)

    def test_toolbar_matches_ingest_records_page(self):
        for markup in (
            '<div class="toolbar', 'class="toolbar-group"', 'class="inline-field"',
            'class="date-range" data-date-range="runDateFrom,runDateTo"', 'class="date-range-trigger"',
            'class="button primary query-button"', 'class="button reset-button"',
            '<symbol id="i-left"', '<symbol id="i-right"', '<symbol id="i-down"',
        ):
            self.assertIn(markup, self.html, markup)
        self.assertIn("/identity-assets/date-range.js", self.html)

    def test_pagination_bar_uses_shared_component(self):
        for markup in ('class="pagination-bar"', 'class="pagination-summary"', 'class="pagination-controls"',
                       'class="select-chevron pagination-size"', 'class="pagination-nav"', 'class="pagination-pages"',
                       'class="pagination-page"', 'id="runPageSize"'):
            self.assertIn(markup, self.html, markup)
        for style in (".pagination-nav", ".pagination-page-btn", ".select-chevron"):
            self.assertIn(style, self.css, style)

    def test_panel_headings_keep_their_padding(self):
        """回归：重写样式时漏掉 .panel-heading，导致所有卡片标题贴边。"""

        self.assertIn(".panel-heading { display: flex", self.css)
        self.assertIn("padding: 16px 18px 12px", self.css)
        self.assertIn(".panel-heading h2 { margin: 0", self.css)

    def test_report_visual_language_matches_the_approved_draft(self):
        for style in (".report-grid", "--report-cols", ".report-head", ".shop-row", ".report-row",
                      ".mapping-tag", ".rc-day", ".rc-chip", ".drawer", ".report-summary"):
            self.assertIn(style, self.css, style)
        self.assertIn("--auto-blue: #1677ff", self.css)

    def test_run_center_toolbar_has_search_and_inline_stats(self):
        for markup in ("runRows", "detailDialog", "detailContent", "runToolbarStats",
                       'id="runKeyword"', 'id="runSearchField"'):
            self.assertIn(markup if markup.startswith("id=") else f'id="{markup}"', self.html, markup)
        self.assertNotIn("runTopMetrics", self.html)
        for removed in ("runQuickFilters", "runFaultPanel", "runFaultToggle"):
            self.assertNotIn(removed, self.html)
        for fragment in ("data-resume", "needs_human", "AI Repair Context"):
            self.assertIn(fragment, self.script + self.runtime)
        self.assertIn("共 0 条执行记录 · 保留每次重试与恢复", self.html)
        self.assertIn("<th>触发 · lane</th>", self.html)
        self.assertIn("['keyword', 'runKeyword']", self.script)
        self.assertNotIn("date_field", self.script)
        self.assertIn("全部 <b>", self.script)
        self.assertNotIn("长时间运行 <b>", self.script)

    def test_reports_query_has_no_periodic_auto_refresh(self):
        self.assertNotIn("refreshProgress", self.reports)
        self.assertNotIn("setInterval(refreshProgress", self.reports)

    def test_action_columns_use_icons_and_schedule_toggle_colors(self):
        for symbol in ('id="i-eye"', 'id="i-sliders"', 'id="i-list"', 'id="i-power"', 'id="i-trash"'):
            self.assertIn(f'<symbol {symbol}', self.html, symbol)
        for fragment in ('data-shop-config="${esc(shop.key)}"><svg><use href="#i-sliders"/>',
                         'data-run-detail="${esc(report.run_id)}"><svg><use href="#i-eye"/>',
                         'data-report-backfill="${esc(shop.key)}|${esc(report.report_type)}"><svg><use href="#i-play"/>'):
            self.assertIn(fragment, self.reports, fragment)
        for fragment in ('data-detail="${id}"><svg><use href="#i-eye"/>',
                         'data-retry="${id}"><svg><use href="#i-refresh"/>',
                         'data-cancel="${id}"><svg><use href="#i-close"/>',
                         'data-view-task="${key}"><svg><use href="#i-list"/>',
                         'data-run-task="${key}"><svg><use href="#i-play"/>',
                         'data-config-task="${key}"><svg><use href="#i-calendar"/>',
                         "${job.enabled ? 'status-disable' : 'status-enable'}",
                         'data-toggle-task="${key}"><svg><use href="#i-power"/>'):
            self.assertIn(fragment, self.script, fragment)
        for style in (".link-button.status-enable { color: #52c41a; }", ".link-button.status-disable { color: #fa8c16; }"):
            self.assertIn(style, self.css, style)

    def test_schedules_page_only_defines_scheduling(self):
        for markup in ('id="jobRows"', 'id="jobSourceKind"', 'id="jobFlowId"', 'id="jobProfile"'):
            self.assertIn(markup, self.html, markup)
        self.assertIn("本页只定义“何时执行”", self.html)
        self.assertIn("data-config-task", self.script)
        self.assertIn("data-run-task", self.script)

    def test_runtime_page_covers_workers_locks_queue_and_notifications(self):
        for markup in ('id="runtimeWorkers"', 'id="runtimeLocks"', 'id="runtimeQueueRows"',
                       'id="notificationPolicyForm"', 'id="notificationOutboxInfo"',
                       'data-notification-event="failed"', 'data-notification-event="needs_human"', 'data-notification-event="stalled"',
                       'data-notification-event="success"', 'data-notification-event="no_data"', 'data-notification-event="cancelled"',
                       'data-notification-event="success_with_warnings"'):
            self.assertIn(markup, self.html, markup)
        for fragment in ("/api/automation/runtime-resources", "/api/automation/notification-policy"):
            self.assertIn(fragment, self.runtime)
        for style in (".runtime-grid", ".runtime-item", ".notification-row"):
            self.assertIn(style, self.css, style)

    def test_flow_studio_uses_available_main_height_without_outer_scroll(self):
        self.assertIn("main:has(#flow-studioPage.active){display:flex;flex-direction:column;min-height:0;overflow:hidden}", self.flow_css)
        self.assertIn("#flow-studioPage.active{display:flex;flex:1 1 0;width:100%;min-height:0;height:auto", self.flow_css)

    def test_timeline_progress_animation_and_terminal_lifecycle_fallbacks(self):
        for fragment in ("data-next-state", "TERMINAL_RUN_STATUSES", "status_label: '已创建'"):
            self.assertIn(fragment, self.script, fragment)
        for style in ('.timeline-step:not(:first-child) .timeline-rail:before',
                      '.timeline-step:not(:last-child) .timeline-rail:after',
                      '[data-next-state="running"]', 'top: -6px; bottom: 50%', 'top: 50%; bottom: -6px', 'align-items: stretch'):
            self.assertIn(style, self.css, style)

    def test_legacy_scripts_are_removed(self):
        for name in ("report-calendar.js", "report-calendar.css", "ops-center.js"):
            self.assertFalse((ROOT / "static" / name).exists(), name)
        self.assertNotIn("report-calendar.js", self.html)
        self.assertNotIn("ops-center.js", self.html)


if __name__ == "__main__":
    unittest.main()
