"""Cross-executor status regression; live fixtures are invisible and rolled back."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import unittest
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright

from apps.automation_center.report_center import ReportCenterMixin
from apps.automation_center.report_plan import china_today, step_reports
from apps.automation_center.report_sync import legacy_archive_period
from apps.automation_center.worker import AutomationWorker
from apps.automation_center.tests import test_ingest_upgrade as upgrade_fixture
from scripts.auto_download.ledger import RunJournal, confirmed_no_data, read_receipts
from scripts.auto_download.move_report import archive_report
from scripts.auto_download.playwright.douyin_bill_download import archive_download
from scripts.auto_download.run_all_platform_downloads import DownloadController


class StatusSemanticsTests(unittest.TestCase):
    def test_execution_day_and_business_day_have_distinct_meaning(self):
        target = dict(profile_name='p', report_type='r', report_name='资金', enabled=True, step={'module':'m'})
        artifact = dict(profile_name='p', report_type='r', file_exists=True, period_type='day',
                        business_date_start=date(2026,10,18), business_date_end=date(2026,10,18),
                        execution_date=date(2026,10,19))
        self.assertEqual('success', ReportCenterMixin._report_outcome(target,date(2026,10,19),[artifact],[],date_basis='execution')[0])
        self.assertEqual('missing', ReportCenterMixin._report_outcome(target,date(2026,10,19),[artifact],[])[0])
        self.assertEqual('success', ReportCenterMixin._report_outcome(target,date(2026,10,18),[artifact],[])[0])
        artifact['period_type'] = 'month'
        self.assertEqual('success', ReportCenterMixin._report_outcome(target,date(2026,10,19),[artifact],[],date_basis='execution')[0])
        self.assertEqual('monthly_only', ReportCenterMixin._report_outcome(target,date(2026,10,18),[artifact],[])[0])

    def test_fileless_success_is_unverified_but_explicit_no_data_is_successful(self):
        target = dict(profile_name='p', report_type='r', report_name='资金', enabled=True, step={'module':'m'})
        step = dict(profile_name='p', module_name='m', step_name='资金', status='success',execution_date=date(2026,10,19))
        self.assertEqual('unverified', ReportCenterMixin._report_outcome(target,date(2026,10,19),[],[step],date_basis='execution')[0])
        step['status'] = 'no_data'
        self.assertEqual('no_data', ReportCenterMixin._report_outcome(target,date(2026,10,19),[],[step],date_basis='execution')[0])

    def test_legacy_filename_never_claims_rolling_range_coverage(self):
        self.assertEqual('day',legacy_archive_period('20261018_平台_报表.csv')['period_type'])
        self.assertEqual(date(2026,9,30),legacy_archive_period('202609_平台_报表.csv')['business_date_end'])
        self.assertEqual({},legacy_archive_period('unknown.csv'))
        self.assertEqual({},legacy_archive_period('20261399_平台.csv'))
        with self.assertRaisesRegex(ValueError,'date_basis'):
            ReportCenterMixin._report_date_basis({'date_basis':'other'})

    def test_confirmed_empty_query_requires_both_explicit_messages_and_module(self):
        output='结算查询记录数：0\n结算查询无记录，跳过导出'
        self.assertTrue(confirmed_no_data('kuaishou_settlement_download',output))
        self.assertFalse(confirmed_no_data('other',output))
        self.assertFalse(confirmed_no_data('kuaishou_settlement_download','结算查询无记录，跳过导出'))

    def test_legacy_empty_summary_is_bound_to_the_run_profile_and_step(self):
        with tempfile.TemporaryDirectory() as directory:
            service=ReportCenterMixin();service.archive_root=Path(directory)
            service._report_config=Mock(return_value={})
            root=service.archive_root/'.automation_logs/all_platform_downloads';root.mkdir(parents=True)
            result={'module':'kuaishou_settlement_download','name':'结算','return_code':0,'artifacts':[],
                    'output_summary':'结算查询记录数：0\n结算查询无记录，跳过导出'}
            (root/'source.summary.json').write_text(json.dumps({'run_id':'source','profiles':[{'profile':'p','steps':[result]}]}),encoding='utf-8')
            cursor=Mock();cursor.fetchall.return_value=[{'step_run_id':'step','profile_name':'p','module_name':result['module'],'step_name':'结算','journal_key':'source'}]
            service._recover_empty_report_results(cursor)
            self.assertIn("status='no_data'",cursor.execute.call_args.args[0])
            cursor.reset_mock();cursor.fetchall.return_value[0]['profile_name']='different'
            service._recover_empty_report_results(cursor)
            self.assertEqual(1,cursor.execute.call_count)

    def test_journal_keeps_ingest_reference_without_arbitrary_response_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = RunJournal(Path(directory),'reference','interactive')
            journal.emit('step_succeeded', {'ingest':{'ingest_run_id':'safe-id','submitted':1,'token':'secret'}})
            data = journal.path.read_text(encoding='utf-8')
            self.assertIn('safe-id',data)
            self.assertNotIn('secret',data)

    def test_database_outage_preserves_journal_and_backs_off(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = DownloadController.__new__(DownloadController)
            controller.destination=Path(directory);controller.run_id='offline'
            controller.logger=logging.getLogger('report-status-test');controller.event_sink=None
            controller.journal=RunJournal(controller.destination,controller.run_id,'interactive')
            with patch('scripts.auto_download.report_calendar_admin.service_from_env',side_effect=OSError('private detail')) as factory:
                controller._emit('step_started',{'profile_name':'p'})
                controller._emit('step_failed',{'profile_name':'p','status':'failed'})
            self.assertEqual(1,factory.call_count)
            self.assertEqual(2,len(json.loads(controller.journal.path.read_text())['events']))


class DouyinReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_downloaded_bills_write_complete_shared_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest=root/'receipt.json'
            async def save(path):
                Path(path).write_text('字段\n数据',encoding='utf-8')
            download=SimpleNamespace(suggested_filename='source.csv',save_as=AsyncMock(side_effect=save))
            with patch.dict(os.environ,{'AUTOMATION_ARTIFACT_MANIFEST':str(manifest),
                                        'AUTOMATION_REPORT_START':'','AUTOMATION_REPORT_END':''}):
                for report in ('资金','结算'):
                    target=await archive_download(download,root,'抖音','公司','店铺',report,'20261018')
                    self.assertTrue(target.is_file())
            receipts=read_receipts(manifest)
            self.assertEqual(['douyin_fund','douyin_settlement'],[a['report_type'] for a in receipts])
            self.assertTrue(all(a['coverage_verified'] and a['business_date_start']=='2026-10-18' and a['file_hash'] for a in receipts))


@unittest.skipUnless(os.getenv('RUN_REPORT_STATUS_SYNC_DB_TESTS')=='1','live DB/browser checks opt-in')
class ReportStatusSyncDatabaseTests(unittest.TestCase):
    setUp = upgrade_fixture.IngestUpgradeTests.setUp

    def prepare_target(self, *, empty=False):
        self.empty=empty
        platform='快手' if empty else '拼多多'
        with self.service.transaction() as cursor:
            cursor.execute("SELECT * FROM dim.dim_platform_shop_company WHERE platform_name=%s AND is_active AND CURRENT_DATE>=valid_from AND (valid_to IS NULL OR CURRENT_DATE<=valid_to) LIMIT 1",(platform,))
            self.dim=dict(cursor.fetchone())
        self.today=china_today();self.yesterday=self.today-timedelta(days=1)
        self.profile='sync-test-'+uuid.uuid4().hex
        self.metadata={key:self.dim[key+'_name'] for key in ('platform','company','shop')}
        step={'name':'结算' if empty else '订单','module':'kuaishou_settlement_download' if empty else 'pinduoduo_order_download',
              'args':['--start-date',str(self.yesterday),'--end-date',str(self.yesterday)]}
        report=step_reports(platform,step)[0]
        self.target=dict(profile_name=self.profile,profile_id='fixture',target_key=self.profile+'|'+report.report_type,
                         **self.metadata,report_type=report.report_type,report_name=report.report_name,
                         enabled=True,profile_enabled=True,report_enabled=True,mapping_ok=True,
                         mapping_label='已匹配',step=step)
        self.service.report_targets=Mock(return_value={'items':[self.target],'disabled':[],'updated_at':'now','warning':None})

    def fake_download_process(self, command, **kwargs):
        # Only platform/browser I/O is substituted. Archive, HTTP API, Worker,
        # journal projection, SQL queries and page rendering are production code.
        if self.empty:
            return SimpleNamespace(stdout=iter(['结算查询记录数：0\n','结算查询无记录，跳过导出\n']),wait=lambda:0)
        source=self.root/('source-'+uuid.uuid4().hex+'.csv')
        source.write_text('字段\n'+uuid.uuid4().hex,encoding='utf-8')
        archive_report(source,**self.metadata,report='订单',business_date=str(self.yesterday),dest=self.root,
                       receipt_path=Path(kwargs['env']['AUTOMATION_ARTIFACT_MANIFEST']))
        return SimpleNamespace(stdout=iter([]),wait=lambda:0)

    def execute(self, source):
        patches=[patch('scripts.auto_download.run_all_platform_downloads.subprocess.Popen',side_effect=self.fake_download_process),
                 patch.dict(os.environ,{'INGEST_API_BASE_URL':self.base,'INGEST_ROBOT_TOKEN':'isolated-sync-test'}),
                 patch('scripts.auto_download.report_calendar_admin.service_from_env',return_value=self.service)]
        with patches[0],patches[1],patches[2]:
            if source=='web':
                request=Request(self.base+'/api/automation/report-batches',method='POST',
                    headers={'Content-Type':'application/json'},data=json.dumps({'profiles':[self.profile],
                    'dates':[str(self.yesterday)],'request_key':str(uuid.uuid4())}).encode())
                with urlopen(request) as response:
                    batch=json.load(response)['data']
                run_id=str(batch['runs'][0]['automation_run_id'])
                with self.service.transaction() as cursor:
                    cursor.execute('SELECT * FROM ops.automation_run WHERE automation_run_id=%s',(run_id,))
                    claim=dict(cursor.fetchone())
                    cursor.execute('SELECT * FROM ops.automation_job WHERE job_id=%s',(claim['job_id'],))
                    claim['job']=dict(cursor.fetchone())
                worker=AutomationWorker.__new__(AutomationWorker)
                worker.service=self.service;worker.worker_id=str(uuid.uuid4())
                def run(controller):
                    controller._run_step(profile_name=self.profile,profile_id='fixture',cdp_url='ws://fixture',
                        metadata=self.metadata,step_index=1,step=self.target['step'])
                    controller.summary['status']='success'
                    return 0
                with patch('apps.automation_center.worker.load_config',return_value={'version':3,'destination':str(self.root),'log_directory':str(self.root/'logs')}),patch.object(DownloadController,'run',run),patch('apps.automation_center.worker.configure_logger',return_value=logging.getLogger('web-sync-fixture')):
                    worker._run_download(claim)
            else:
                controller=DownloadController(config={},config_path=self.root/'config.json',destination=self.root,
                    logger=logging.getLogger('sync-fixture'),run_id='sync-'+uuid.uuid4().hex,
                    summary_path=self.root/'summary.json',mcp_url='http://fixture',
                    trigger_type='schedule' if source=='codex' else 'manual')
                controller._run_step(profile_name=self.profile,profile_id='fixture',cdp_url='ws://fixture',
                    metadata=self.metadata,step_index=1,step=self.target['step'])
                controller.summary['status']='success';controller.write_summary()
        with self.service.transaction() as cursor:
            cursor.execute('SELECT a.*,t.run_id AS ingest_run_id FROM ops.automation_artifact a JOIN ops.automation_step_run s USING(step_run_id) JOIN ops.ingest_file_task t ON t.file_task_id=a.ingest_file_task_id WHERE s.profile_name=%s',(self.profile,))
            row=cursor.fetchone()
            result=dict(row) if row else None
        return result

    def set_ingest_status(self,artifact,status):
        with self.service.transaction() as cursor:
            cursor.execute("UPDATE ops.ingest_file_task SET status=%s,finished_at=CASE WHEN %s='success' THEN NOW() ELSE NULL END WHERE file_task_id=%s",(status,status,artifact['ingest_file_task_id']))

    def test_three_executors_use_live_ingest_state_in_both_views(self):
        for source in ('web','codex','terminal'):
            with self.subTest(source=source):
                self.prepare_target()
                artifact=self.execute(source)
                for status in ('uploaded','processing','failed','success'):
                    self.set_ingest_status(artifact,status)
                    day=self.service.report_day({'date':str(self.today),'date_basis':'execution'})
                    calendar=self.service.report_calendar({'month':self.today.strftime('%Y-%m'),'date_basis':'execution','compact':'1'})
                    for shop in (day['shops'][0],calendar['days'][self.today.day-1]['shops'][0]):
                        self.assertEqual('success',shop['reports'][0]['status'])
                        self.assertEqual(status,shop['reports'][0]['upload_status'])
                self.assertEqual(1,day['summary']['download_success'])
                self.assertEqual(1,day['summary']['upload_success'])
                self.assertEqual(0,self.service.report_day({'date':str(self.today)})['summary']['download_success'])
                self.assertEqual(1,self.service.report_day({'date':str(self.yesterday)})['summary']['upload_success'])

    def test_explicit_zero_rows_are_complete_without_upload_for_all_executors(self):
        for source in ('web','codex','terminal'):
            with self.subTest(source=source):
                self.prepare_target(empty=True)
                self.assertIsNone(self.execute(source))
                result=self.service.report_day({'date':str(self.today),'date_basis':'execution'})
                self.assertEqual('no_data',result['shops'][0]['reports'][0]['status'])
                self.assertEqual('not_required',result['shops'][0]['reports'][0]['upload_status'])
                self.assertEqual(0,result['summary']['upload_total'])
                self.assertEqual(0,result['summary']['pending'])

    def test_web_submission_failure_is_distinct_from_waiting_for_upload(self):
        self.prepare_target()
        with patch.object(self.ingest,'save_upload',side_effect=ValueError('fixture rejected')):
            self.assertIsNone(self.execute('web'))
        result=self.service.report_day({'date':str(self.today),'date_basis':'execution'})
        report=result['shops'][0]['reports'][0]
        self.assertEqual('success',report['status'])
        self.assertEqual('failed',report['upload_status'])

    def test_legacy_unlinked_untyped_artifact_is_recovered_without_new_ingest(self):
        self.prepare_target();artifact=self.execute('terminal')
        self.set_ingest_status(artifact,'success')
        with self.service.transaction() as cursor:
            cursor.execute('SELECT COUNT(*) AS count FROM ops.ingest_file_task')
            count=cursor.fetchone()['count']
            cursor.execute("UPDATE ops.automation_artifact SET ingest_file_task_id=NULL,report_type=NULL,business_date_start=NULL,business_date_end=NULL,period_type='unknown',coverage_verified=FALSE WHERE artifact_id=%s",(artifact['artifact_id'],))
        day=self.service.report_day({'date':str(self.today),'date_basis':'execution'})
        self.assertEqual(1,day['summary']['upload_success'])
        self.assertFalse(day['shops'][0]['reports'][0]['artifact']['coverage_verified'])
        with self.service.transaction() as cursor:
            cursor.execute('SELECT COUNT(*) AS count FROM ops.ingest_file_task')
            self.assertEqual(count,cursor.fetchone()['count'])

    def test_hash_or_identity_mismatch_cannot_claim_another_import(self):
        self.prepare_target();artifact=self.execute('terminal')
        with self.service.transaction() as cursor:
            cursor.execute("UPDATE ops.automation_artifact SET ingest_file_task_id=NULL,file_hash=%s WHERE artifact_id=%s",('0'*64,artifact['artifact_id']))
        day=self.service.report_day({'date':str(self.today),'date_basis':'execution'})
        self.assertEqual('not_uploaded',day['shops'][0]['reports'][0]['upload_status'])
        with self.service.transaction() as cursor:
            cursor.execute('UPDATE ops.automation_artifact SET file_hash=%s WHERE artifact_id=%s',(artifact['file_hash'],artifact['artifact_id']))
            cursor.execute('UPDATE ops.automation_step_run SET shop_code=%s WHERE step_run_id=%s',('different-shop',artifact['step_run_id']))
        day=self.service.report_day({'date':str(self.today),'date_basis':'execution'})
        self.assertEqual('not_uploaded',day['shops'][0]['reports'][0]['upload_status'])

    def test_execution_backfill_preserves_the_requested_business_day(self):
        self.prepare_target()
        preview=self.service.preview_report_batch({'profiles':[self.profile],'dates':[str(self.today)],'date_basis':'execution'})
        args=preview['plans'][0]['steps'][0]['args']
        self.assertEqual(str(self.yesterday),args[args.index('--end-date')+1])

    def test_open_page_automatically_syncs_all_three_executors(self):
        if os.getenv('RUN_REPORT_STATUS_SYNC_BROWSER_TESTS')!='1':
            self.skipTest('live browser checks opt-in')
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True,channel='chrome')
            try:
                page=browser.new_page(viewport={'width':1640,'height':1000})
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.route('**/identity-assets/shell.js',lambda route:route.fulfill(content_type='text/javascript',body="window.currentPermissions=new Set(['automation.results.view','automation.runs.execute','automation.jobs.manage']);window.showAppToast=()=>{};"))
                for source in ('web','codex','terminal'):
                    with self.subTest(source=source):
                        self.prepare_target()
                        page.goto(self.base+'/automation/?executor='+source+'#reports')
                        page.locator('[data-shop-toggle]').first.click()
                        page.wait_for_function("document.querySelector('.report-row').textContent.includes('未获取')")
                        artifact=self.execute(source)
                        page.wait_for_function("document.querySelector('.report-row').textContent.includes('已下载') && document.querySelector('.report-row').textContent.includes('上传中')",timeout=15000)
                        self.set_ingest_status(artifact,'success')
                        page.wait_for_function("document.querySelector('.report-row').textContent.includes('已上传')",timeout=15000)
                        page.locator('[data-report-view="calendar"]').click()
                        page.wait_for_function("document.querySelector('.rc-day.is-today')?.textContent.includes('下载 1/1') && document.querySelector('.rc-day.is-today')?.textContent.includes('上传 1/1')",timeout=15000)
                        page.screenshot(path=str(self.root/('sync-'+source+'.png')),full_page=True)
                self.assertEqual([],errors)
                self.assertEqual([],self.http_errors)
            finally:
                browser.close()


if __name__=='__main__':
    unittest.main()
