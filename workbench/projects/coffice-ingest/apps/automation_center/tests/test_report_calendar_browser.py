"""Opt-in UI acceptance against real service APIs in a rolled-back DB fixture."""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from apps.automation_center.module import AutomationCenterModule
from apps.automation_center.tests import test_report_calendar_database as database_tests


class ReportCalendarBrowserTests(database_tests.ReportCalendarDatabaseTests):
    # Reuse only the fixture, not every database test a second time.
    test_external_cli_sync_is_idempotent_and_marks_business_days = None
    test_batch_duplicate_submission_and_different_keys_do_not_duplicate_queue = None
    test_preview_skips_verified_coverage_and_can_explicitly_refresh = None
    test_all_new_table_and_column_comments_are_present = None
    test_claim_excludes_external_queue_and_blocks_controller_against_flow_lock = None
    test_backend_artifact_without_shop_mapping_cannot_mark_coverage_verified = None
    test_journal_growth_is_imported_after_history_fast_path = None
    test_stopped_process_is_detected_even_when_journal_file_is_unchanged = None

    def test_calendar_selection_preview_queue_and_execution_switch(self):
        if os.getenv('RUN_REPORT_CALENDAR_BROWSER_TESTS') != '1':
            self.skipTest('live browser checks opt-in')
        module = AutomationCenterModule.__new__(AutomationCenterModule)
        module.service = self.service
        module.static_dir = Path(__file__).resolve().parents[1] / 'static'
        repository = Path(__file__).resolve().parents[3]

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def handle_request(self, method):
                target = urlsplit(self.path)
                if target.path.startswith('/api/automation'):
                    size = int(self.headers.get('Content-Length', '0'))
                    payload = json.loads(self.rfile.read(size)) if size else {}
                    try:
                        data, status = module.dispatch(method, target.path, target.query, payload,
                                                       context=SimpleNamespace(can=lambda _: True), operator='browser-fixture')
                        body = json.dumps({'data': data}, default=str, ensure_ascii=False).encode()
                    except ValueError as exc:
                        status, body = 400, json.dumps({'message': str(exc)}, ensure_ascii=False).encode()
                    mime = 'application/json; charset=utf-8'
                else:
                    if target.path.startswith('/automation'):
                        path = module.static_file(target.path)
                    elif target.path.startswith('/identity-assets/'):
                        path = repository/'apps/identity_access/static'/target.path.removeprefix('/identity-assets/')
                    else:
                        path = repository/'apps/fund_split_adjust/static'/target.path.lstrip('/')
                    status = 200 if path and path.is_file() else 404
                    body = path.read_bytes() if status == 200 else b''
                    mime = 'text/css' if target.path.endswith('.css') else 'text/javascript' if target.path.endswith('.js') else 'text/html'
                self.send_response(status); self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

            def do_GET(self): self.handle_request('GET')
            def do_POST(self): self.handle_request('POST')

        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, channel='chrome')
                try:
                    page = browser.new_page(viewport={'width':1440,'height':1000})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    # Authentication is fixture-local; production authorization
                    # and all module/service routes remain unchanged.
                    page.route('**/identity-assets/shell.js', lambda route: route.fulfill(
                        content_type='text/javascript', body="window.currentPermissions=new Set(['automation.results.view','automation.runs.execute','automation.runs.retry']);window.showAppToast=()=>{};"))
                    page.goto(f'http://127.0.0.1:{server.server_port}/automation/#reports')
                    page.locator('#reportShopRows .shop-row').first.wait_for()
                    # 列表视图默认当天；店铺行可展开、可打开配置抽屉。
                    page.locator('[data-shop-toggle]').first.click()
                    page.locator('.shop-block.is-open .report-row').first.wait_for()
                    page.locator('[data-shop-config]').first.click()
                    page.locator('#reportDrawer').wait_for()
                    self.assertIn('报表清单', page.locator('#reportDrawerBody').inner_text())
                    page.locator('#reportDrawerCancel').click()
                    # 切换到日历视图并按月份查询。
                    page.locator('[data-report-view="calendar"]').click()
                    page.locator('#calendarMonth').fill('2026-10')
                    page.locator('#queryReports').click()
                    page.wait_for_function("!document.getElementById('queryReports').disabled")
                    page.locator('[data-calendar-date="2026-10-01"]').wait_for()
                    width=page.locator('[data-calendar-date="2026-10-01"]').evaluate('e=>e.getBoundingClientRect().width')
                    self.assertGreater(width,90)
                    for day in range(1,8):
                        page.locator(f'[data-calendar-date="2026-10-{day:02d}"]').click()
                    self.assertIn('7', page.locator('#calendarSelectionCount').inner_text())
                    page.locator('#calendarBackfill').click()
                    page.locator('#reportPreviewDialog').wait_for()
                    self.assertIn('2026-10-01 至 2026-10-07', page.locator('#reportPreviewContent').inner_text())
                    page.locator('#reportForce').check()
                    self.assertTrue(page.locator('#reportSubmit').is_disabled())
                    page.locator('#reportPreviewRefresh').click()
                    page.wait_for_function("!document.getElementById('reportSubmit').disabled")
                    page.locator('#reportSubmit').click()
                    page.locator('#reportBatchPanel').wait_for()
                    self.assertIn('排队中', page.locator('#reportBatchRuns').inner_text())
                    page.screenshot(path=str(repository/'.tmp/automation-tests/report-calendar.png'), full_page=True)
                    self.assertEqual([], errors)
                finally:
                    browser.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
