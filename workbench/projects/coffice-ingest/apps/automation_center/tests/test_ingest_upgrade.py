"""API and browser acceptance; all database writes are rolled back."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from psycopg2.extras import RealDictCursor
from playwright.sync_api import sync_playwright

from apps.automation_center.module import AutomationCenterModule
from apps.automation_center.service import AutomationService
from apps.file_ingest.module import FileIngestModule
from apps.file_ingest.naming import build_filename
from apps.file_ingest.service import FileIngestService
from apps.fund_split_adjust.server import load_project_env
from scripts.auto_download.ingest_api import IngestAPIError, _request, submit_archived_reports

ROOT = Path(__file__).resolve().parents[3]


@unittest.skipUnless(os.getenv('RUN_AUTOMATION_UPGRADE_DB_TESTS') == '1', 'live DB/browser checks opt-in')
class IngestUpgradeTests(unittest.TestCase):
    def setUp(self):
        load_project_env()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        args = argparse.Namespace(host=os.getenv('PGHOST','192.168.77.111'), pg_port=int(os.getenv('PGPORT','5432')), dbname=os.getenv('PGDATABASE','mock_coffice'), user=os.getenv('PGUSER','postgres'), password=os.getenv('PGPASSWORD'))
        ingest = FileIngestService(args, storage_root=self.root/'uploads')
        self.service = AutomationService(args, file_ingest_service=ingest, archive_root=self.root)
        connection = self.service.connect()
        self.addCleanup(connection.close)
        self.addCleanup(connection.rollback)
        @contextmanager
        def transaction():
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor
        self.service.transaction = ingest.transaction = transaction
        with transaction() as cursor:
            cursor.execute((ROOT/'sql/common/438_ingest_api_source_postgres.sql').read_text(encoding='utf-8'))
        automation_module = AutomationCenterModule.__new__(AutomationCenterModule)
        automation_module.service = self.service
        automation_module.static_dir = ROOT/'apps/automation_center/static'
        ingest_module = FileIngestModule.__new__(FileIngestModule)
        ingest_module.service = ingest
        self.ingest = ingest
        self.http_errors = []
        http_errors = self.http_errors

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def handle_request(self, method):
                url = urlsplit(self.path)
                try:
                    if method == 'POST' and url.path.endswith('/files'):
                        data, status = ingest_module.upload(url.path, self.headers, self.rfile, operator='upgrade-fixture', ip_address=None)
                    elif url.path.startswith('/api/'):
                        size = int(self.headers.get('Content-Length',0))
                        payload = json.loads(self.rfile.read(size)) if size else {}
                        module = ingest_module if url.path.startswith('/api/ingest/') else automation_module
                        data, status = module.dispatch(method, url.path, url.query, payload, headers=self.headers, context=SimpleNamespace(can=lambda _:True), operator='upgrade-fixture') if module is ingest_module else module.dispatch(method, url.path, url.query, payload, context=SimpleNamespace(can=lambda _:True), operator='upgrade-fixture')
                    else:
                        path = automation_module.static_file(url.path) if url.path.startswith('/automation/') else ROOT/('apps/identity_access/static/'+url.path.removeprefix('/identity-assets/') if url.path.startswith('/identity-assets/') else 'apps/fund_split_adjust/static/'+url.path.lstrip('/'))
                        content = path.read_bytes()
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/javascript' if path.suffix=='.js' else 'text/css' if path.suffix=='.css' else 'text/html')
                        self.end_headers(); self.wfile.write(content); return
                    content = json.dumps({'data':data}, default=str, ensure_ascii=False).encode()
                except Exception as exc:
                    http_errors.append(str(exc))
                    status = 401 if isinstance(exc,PermissionError) else 400
                    content = json.dumps({'message':str(exc)}).encode()
                self.send_response(status); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(content)
            def do_GET(self): self.handle_request('GET')
            def do_POST(self): self.handle_request('POST')
        server = HTTPServer(('127.0.0.1',0), Handler)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        def stop():
            server.shutdown(); server.server_close(); thread.join(timeout=5)
        self.addCleanup(stop)
        self.base = f'http://127.0.0.1:{server.server_port}'

    def test_real_api_upload_source_dedup_and_rejected_token(self):
        with self.service.transaction() as cursor:
            cursor.execute("SELECT company_name,shop_name FROM dim.dim_platform_shop_company WHERE platform_name='拼多多' AND is_active AND CURRENT_DATE>=valid_from AND (valid_to IS NULL OR CURRENT_DATE<=valid_to) LIMIT 1")
            dim = cursor.fetchone()
        filename = '20261011_' + build_filename(extension='.csv',platform_name='拼多多',company_name=dim['company_name'],shop_name=dim['shop_name'],report_name='订单')
        file = self.root/filename
        file.write_text('测试字段\n'+os.urandom(12).hex(),encoding='utf-8')
        artifacts = [{'relative_path':filename,'file_hash':hashlib.sha256(file.read_bytes()).hexdigest()}]
        with patch.dict(os.environ, {'INGEST_API_BASE_URL':self.base}):
            try:
                result = submit_archived_reports(self.root,artifacts)
            except IngestAPIError:
                self.fail(str(self.http_errors))
            reused = submit_archived_reports(self.root,artifacts)
            self.assertEqual(result['ingest_run_id'],reused['ingest_run_id'])
            self.assertTrue(reused['reused'])
            with self.ingest.transaction() as cursor:
                cursor.execute('SELECT source,status,auto_refresh FROM ops.ingest_run WHERE run_id=%s',(result['ingest_run_id'],))
                run = cursor.fetchone()
                self.assertEqual(('api','ready',True),(run['source'],run['status'],run['auto_refresh']))
                cursor.execute('SELECT COUNT(*) AS count FROM ops.ingest_file_task WHERE run_id=%s',(result['ingest_run_id'],))
                self.assertEqual(1,cursor.fetchone()['count'])
            with self.assertRaisesRegex(IngestAPIError,'HTTP 401'):
                _request(self.base,'invalid-fixture-token','/api/ingest/runs',b'{"source":"api","expected_file_count":1,"idempotency_key":"rejected-fixture"}','application/json','rejected-fixture')
        artifacts[0]['file_hash']='incorrect'
        with self.assertRaises(IngestAPIError):submit_archived_reports(self.root,artifacts)

    def test_jobs_filters_pagination_and_flow_badges_in_browser(self):
        items = self.service.list_jobs()['items']
        flows = self.service.list_flows()['items']
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True,channel='chrome')
            try:
                page = browser.new_page(viewport={'width':1600,'height':1000})
                errors=[]; page.on('pageerror',lambda error:errors.append(str(error)))
                page.route('**/identity-assets/shell.js',lambda route:route.fulfill(content_type='text/javascript',body="window.currentPermissions=new Set(['automation.jobs.view','automation.jobs.manage','automation.runs.execute','automation.flows.view','automation.flows.manage','automation.flows.execute']);window.showAppToast=()=>{};"))
                page.goto(self.base+'/automation/#jobs')
                page.wait_for_function("document.getElementById('jobTotal').textContent!=='共 0 条'")
                self.assertEqual(min(10,len(items)),page.locator('#jobRows tr').count())
                self.assertEqual(f'第 1/{math.ceil(len(items)/10)} 页',page.locator('#jobPageInfo').inner_text())
                self.assertEqual(['任务','类型 / lane','调度','状态','7日健康','最近运行','运行状态','操作'],page.locator('#jobsPage th').all_text_contents())
                page.locator('#jobNextPage').click(); self.assertIn('第 2/',page.locator('#jobPageInfo').inner_text())
                page.locator('#jobPlatform').select_option('拼多多'); page.locator('#searchJobs').click()
                expected=[item for item in items if '拼多多' in item['platforms']]
                self.assertEqual(f'共 {len(expected)} 条',page.locator('#jobTotal').inner_text())
                page.locator('#jobReport').select_option('订单'); page.locator('#searchJobs').click()
                expected=[item for item in expected if '订单' in item['report_names']]
                self.assertEqual(f'共 {len(expected)} 条',page.locator('#jobTotal').inner_text())
                self.assertEqual(['启用' if item['enabled'] else '停用' for item in expected],page.locator('#jobRows td:nth-child(4)').all_text_contents())
                page.locator('#resetJobs').click(); page.locator('#jobStatus').select_option('disabled'); page.locator('#searchJobs').click()
                self.assertEqual(f"共 {sum(not item['enabled'] for item in items)} 条",page.locator('#jobTotal').inner_text())
                page.locator('#resetJobs').click(); page.locator('#jobSchedule').select_option('daily'); page.locator('#searchJobs').click()
                self.assertEqual(f"共 {sum(item['schedule_type']=='daily' for item in items)} 条",page.locator('#jobTotal').inner_text())
                page.locator('#resetJobs').click(); page.locator('#jobKeyword').fill('千川'); page.locator('#jobKeyword').press('Enter')
                self.assertEqual(f"共 {sum('千川' in ' '.join([item['job_name'],*item['platforms'],*item['report_names']]) for item in items)} 条",page.locator('#jobTotal').inner_text())
                page.locator('#jobKeyword').fill('没有这样的任务'); page.locator('#jobKeyword').press('Enter')
                self.assertIn('暂无符合条件',page.locator('#jobRows').inner_text())
                page.locator('#resetJobs').click(); page.locator('#jobPageSize').select_option('50')
                self.assertEqual(len(items),page.locator('#jobRows tr').count())
                page.locator('#jobPageSize').select_option('10')
                (ROOT/'.tmp/automation-tests').mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(ROOT/'.tmp/automation-tests/jobs-upgrade.png'),full_page=True)
                page.evaluate("location.hash='flow-studio'")
                page.locator('#flowPickerLabel .status-tag.ready').wait_for()
                page.locator('#flowPickerTrigger').click()
                self.assertEqual(len(flows),page.locator('#flowPickerOptions [role=option]').count())
                self.assertEqual(sum(flow['status']=='published' for flow in flows),page.locator('#flowPickerOptions .status-tag.success').count())
                self.assertEqual('rgb(22, 119, 255)',page.locator('#flowPickerOptions .status-tag.ready').first.evaluate('(node)=>getComputedStyle(node).color'))
                page.locator('#flowPickerOptions [role=option]').filter(has=page.locator('.status-tag.success')).last.click()
                page.wait_for_function("document.getElementById('flowPickerLabel').textContent.includes('已发布')")
                page.locator('#flowPickerTrigger').click()
                page.screenshot(path=str(ROOT/'.tmp/automation-tests/flow-picker-upgrade.png'),full_page=True)
                self.assertEqual([],errors)
            finally:
                browser.close()


if __name__ == '__main__':unittest.main()
