"""Live PostgreSQL acceptance, wholly rolled back and invisible to real Workers."""
from __future__ import annotations

import argparse
import os
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock
from psycopg2.extras import Json

from psycopg2.extras import RealDictCursor

from apps.automation_center.service import AutomationService
from apps.automation_center.report_plan import step_reports
from apps.automation_center.report_plan import china_today
from apps.fund_split_adjust.server import load_project_env
from scripts.auto_download.ledger import RunJournal, read_receipts
from scripts.auto_download.move_report import archive_report


@unittest.skipUnless(os.getenv('RUN_REPORT_CALENDAR_DB_TESTS') == '1', 'live DB checks opt-in')
class ReportCalendarDatabaseTests(unittest.TestCase):
    def setUp(self):
        load_project_env()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        args=argparse.Namespace(host=os.getenv('PGHOST','192.168.77.111'),pg_port=int(os.getenv('PGPORT','5432')),
                                dbname=os.getenv('PGDATABASE','mock_coffice'),user=os.getenv('PGUSER','postgres'),password=os.getenv('PGPASSWORD'))
        self.service=AutomationService(args,archive_root=self.root)
        self.connection=self.service.connect()
        self.addCleanup(self.connection.close)
        self.addCleanup(self.connection.rollback)

        @contextmanager
        def transaction():
            # Every nested service operation shares this uncommitted transaction.
            # The real Worker cannot see or claim any fixture run.
            with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor
        self.service.transaction=transaction
        with transaction() as cursor:
            cursor.execute((Path(__file__).resolve().parents[3]/'sql/common/432_automation_report_calendar_postgres.sql').read_text(encoding='utf-8'))
            cursor.execute("SELECT * FROM dim.dim_platform_shop_company WHERE platform_name='拼多多' AND is_active ORDER BY valid_from DESC LIMIT 1")
            dim=dict(cursor.fetchone())
        self.profile='calendar-test-'+uuid.uuid4().hex
        self.metadata={'platform':dim['platform_name'],'company':dim['company_name'],'shop':dim['shop_name']}
        step={'name':'订单','module':'pinduoduo_order_download','args':[]}
        report=step_reports('拼多多',step)[0]
        self.target={'profile_name':self.profile,'profile_id':'test-profile','target_key':self.profile+'|'+report.report_type,
                     **self.metadata,'shop_code':dim['shop_code'],'company_code':dim['company_code'],'platform_code':dim['platform_code'],
                     'report_type':report.report_type,'report_name':report.report_name,'enabled':True,
                     'profile_enabled':True,'report_enabled':True,'mapping_ok':True,'step':step}
        self.service.report_targets=Mock(return_value={'items':[self.target],'disabled':[],'updated_at':'2026-10-09','warning':None})

    def journal(self):
        source=self.root/'fixture.csv';source.write_text('字段\n数据',encoding='utf-8')
        target=archive_report(source,**{'platform':self.metadata['platform'],'company':self.metadata['company'],'shop':self.metadata['shop']},
                              report='订单',business_date='2026-08-07',dest=self.root,
                              period_start='2026-08-01',period_end='2026-08-07',receipt_path=self.root/'receipt.json')
        journal=RunJournal(self.root,'test_'+uuid.uuid4().hex,'interactive')
        payload={'profile_name':self.profile,'metadata':self.metadata,'step_name':'订单','module_name':'pinduoduo_order_download'}
        journal.emit('step_started',payload)
        journal.emit('step_succeeded',{**payload,'status':'success','artifacts':read_receipts(self.root/'receipt.json')})
        journal.emit('completed',{'status':'success'})
        return target

    def test_external_cli_sync_is_idempotent_and_marks_business_days(self):
        target=self.journal()
        self.assertEqual(1,self.service.sync_report_journals())
        self.assertEqual(0,self.service.sync_report_journals())
        calendar=self.service.report_calendar({'month':'2026-08'})
        self.assertTrue(all(day['items'][0]['status']=='success' for day in calendar['days'][:7]))
        self.assertEqual('missing',calendar['days'][7]['items'][0]['status'])
        target.unlink()
        self.assertEqual('missing_file',self.service.report_calendar({'month':'2026-08'})['days'][0]['items'][0]['status'])

    def test_journal_growth_is_imported_after_history_fast_path(self):
        self.journal()
        self.assertEqual(1, self.service.sync_report_journals())
        self.assertEqual(0, self.service.sync_report_journals())
        journal = next((self.root/'.automation_logs/report_ledger').glob('*.json'))
        import json
        data = json.loads(journal.read_text(encoding='utf-8'))
        data['events'].append({'event': 'completed', 'payload': {'status': 'failed'}})
        journal.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        self.assertEqual(1, self.service.sync_report_journals())
        self.assertEqual(0, self.service.sync_report_journals())
        with self.service.transaction() as cursor:
            cursor.execute('''SELECT r.status,j.imported_events FROM ops.automation_download_journal j
                JOIN ops.automation_run r USING(automation_run_id) WHERE j.journal_key=%s''', (data['run_id'],))
            row = cursor.fetchone()
        self.assertEqual('failed', row['status'])
        self.assertEqual(len(data['events']), row['imported_events'])

    def test_stopped_process_is_detected_even_when_journal_file_is_unchanged(self):
        from unittest.mock import patch
        import json
        self.journal()
        journal = next((self.root/'.automation_logs/report_ledger').glob('*.json'))
        data = json.loads(journal.read_text(encoding='utf-8'))
        data['events'] = [event for event in data['events'] if event['event'] != 'completed']
        journal.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        with patch('apps.automation_center.report_center.journal_process_running', return_value=True):
            self.assertEqual(1, self.service.sync_report_journals())
            self.assertEqual(0, self.service.sync_report_journals())
        with patch('apps.automation_center.report_center.journal_process_running', return_value=False):
            self.assertEqual(1, self.service.sync_report_journals())
            self.assertEqual(0, self.service.sync_report_journals())
        with self.service.transaction() as cursor:
            cursor.execute('''SELECT r.status FROM ops.automation_download_journal j
                JOIN ops.automation_run r USING(automation_run_id) WHERE j.journal_key=%s''', (data['run_id'],))
            self.assertEqual('failed', cursor.fetchone()['status'])

    def test_batch_duplicate_submission_and_different_keys_do_not_duplicate_queue(self):
        payload={'profiles':[self.profile],'report_types':[self.target['report_type']], 'month':'2026-08','request_key':str(uuid.uuid4())}
        batch=self.service.create_report_batch(payload,'calendar-integration')
        self.assertEqual(1,batch['total'])
        self.assertEqual(1,batch['plan_snapshot']['step_count'])
        self.assertEqual(batch['batch_id'],self.service.create_report_batch(payload,'calendar-integration')['batch_id'])
        # The August report request belongs to today's execution ledger.
        today=china_today()
        days=self.service.report_calendar({'month':today.strftime('%Y-%m')})['days']
        self.assertTrue(any(str(run['automation_run_id']) == str(batch['runs'][0]['automation_run_id'])
                            for run in days[today.day-1]['executions']))
        self.assertFalse(any(str(run['automation_run_id']) == str(batch['runs'][0]['automation_run_id'])
                             for day in self.service.report_calendar({'month':'2026-08'})['days'] for run in day['executions']))
        payload['request_key']=str(uuid.uuid4())
        self.assertEqual(batch['batch_id'],self.service.create_report_batch(payload,'calendar-integration')['batch_id'])

    def test_preview_skips_verified_coverage_and_can_explicitly_refresh(self):
        self.journal()
        payload={'profiles':[self.profile],'report_types':[self.target['report_type']], 'start_date':'2026-08-01','end_date':'2026-08-10'}
        preview=self.service.preview_report_batch(payload)
        self.assertEqual(7,preview['skipped'])
        self.assertIn('2026-08-08',preview['plans'][0]['steps'][0]['args'])
        payload['force']=True
        self.assertEqual(0,self.service.preview_report_batch(payload)['skipped'])

    def test_all_new_table_and_column_comments_are_present(self):
        with self.service.transaction() as cursor:
            cursor.execute("""SELECT c.relname,a.attname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
                WHERE n.nspname='ops' AND c.relname IN ('automation_download_batch','automation_download_journal')
                AND (obj_description(c.oid,'pg_class') IS NULL OR col_description(c.oid,a.attnum) IS NULL)""")
            self.assertEqual([],cursor.fetchall())

    def test_backend_artifact_without_shop_mapping_cannot_mark_coverage_verified(self):
        batch=self.service.create_report_batch({'profiles':[self.profile], 'dates':['2026-08-01'],
                                                'request_key':str(uuid.uuid4())}, 'calendar-integration')
        run_id=str(batch['runs'][0]['automation_run_id'])
        period={'business_date_start':'2026-08-01','business_date_end':'2026-08-01','period_type':'day'}
        step_id=self.service.start_step(run_id,{'profile_name':self.profile,'metadata':self.metadata,
                                               'business_period':period,'step_name':'订单','module_name':'pinduoduo_order_download'})
        receipt={'relative_path':'fixture.csv','file_name':'fixture.csv','file_size_bytes':10,
                 'report_type':self.target['report_type'],'coverage_verified':True,**period}
        self.assertTrue(self.service.record_artifacts(run_id,step_id,[receipt],period)[0]['coverage_verified'])
        with self.service.transaction() as cursor:
            cursor.execute('UPDATE ops.automation_step_run SET shop_code=NULL WHERE step_run_id=%s',(step_id,))
        self.assertFalse(self.service.record_artifacts(run_id,step_id,[receipt],period)[0]['coverage_verified'])

    def test_claim_excludes_external_queue_and_blocks_controller_against_flow_lock(self):
        batch=self.service.create_report_batch({'profiles':[self.profile], 'dates':['2026-08-01'],
                                                'request_key':str(uuid.uuid4())}, 'calendar-integration')
        candidate=batch['runs'][0]['automation_run_id']
        holder=str(uuid.uuid4())
        recorder=Mock();recorder.fetchone.return_value=None
        capture=AutomationService.__new__(AutomationService)
        @contextmanager
        def record_transaction():
            yield recorder
        capture.transaction=record_transaction
        capture.claim_run(str(uuid.uuid4()))
        query=next(call.args[0] for call in recorder.execute.call_args_list if 'SELECT r.automation_run_id' in call.args[0])
        # Limit the real query to this invisible fixture; never claim live jobs.
        query=query.replace("platform_download%'", "platform_download%%'").replace(
            'ORDER BY r.queued_at', 'AND r.automation_run_id=%s ORDER BY r.queued_at')
        query=query.replace('FROM ops.automation_resource_lock l',
                            'FROM (SELECT * FROM ops.automation_resource_lock WHERE automation_run_id=%s) l')
        with self.service.transaction() as cursor:
            # Inspect only fixture locks without changing unrelated live rows.
            parameters=(holder,holder,candidate)
            cursor.execute(query,parameters)
            self.assertIsNotNone(cursor.fetchone())
            cursor.execute("UPDATE ops.automation_run SET input_context=input_context || %s WHERE automation_run_id=%s",
                           (Json({'execution_source':'external'}),candidate))
            cursor.execute(query,parameters)
            self.assertIsNone(cursor.fetchone())
            cursor.execute("UPDATE ops.automation_run SET input_context=input_context-'execution_source' WHERE automation_run_id=%s",(candidate,))
            cursor.execute("""INSERT INTO ops.automation_run(automation_run_id,job_id,business_date,status,execution_lane,resource_key,trigger_type)
                              SELECT %s,job_id,business_date,'running','interactive',%s,'manual' FROM ops.automation_run WHERE automation_run_id=%s""",
                           (holder,'profile:'+self.profile,candidate))
            cursor.execute("INSERT INTO ops.automation_resource_lock(resource_key,automation_run_id,worker_id) VALUES(%s,%s,%s)",
                           ('profile:'+self.profile,holder,str(uuid.uuid4())))
            cursor.execute(query,parameters)
            self.assertIsNone(cursor.fetchone())
