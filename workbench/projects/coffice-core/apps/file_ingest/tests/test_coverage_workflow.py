"""Source selection, duplicate adoption and retry tests in a disposable database."""
import argparse
import csv
import hashlib
import importlib
import io
import json
import os
import tempfile
import threading
import urllib.request
import unittest
import uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json

from apps.file_ingest.coverage import (ROOT,SUPPORTED,CoverageConflict,compare_days,fingerprint_rows,activate)
from apps.file_ingest.service import FileIngestService,FileIngestWorker,ConflictError
from apps.file_ingest.refresh_scope import retry_refresh_context
from etl.common.settlement_sources import TABLES,load_pg_env


class ContentComparisonTests(unittest.TestCase):
    def test_unverified_bearer_cannot_bypass_user_authentication(self):
        from apps.fund_split_adjust.server import ApplicationHandler
        from apps.file_ingest.module import FileIngestModule
        with patch.dict(os.environ,{'INGEST_ROBOT_TOKEN':'test-only-token'}):
            fake=SimpleNamespace(headers={'Authorization':'Bearer arbitrary'})
            self.assertFalse(ApplicationHandler.is_robot_request(fake,'POST','/api/ingest/runs'))
            fake.headers['Authorization']='Bearer test-only-token'
            self.assertTrue(ApplicationHandler.is_robot_request(fake,'POST','/api/ingest/runs'))
            self.assertFalse(ApplicationHandler.is_robot_request(fake,'POST','/api/ingest/fee-mappings/assign'))
            module=FileIngestModule.__new__(FileIngestModule)
            with self.assertRaises(PermissionError):module.require_robot_token(fake.headers,source='manual')

    def test_confirmed_zero_is_a_known_source_not_an_automatic_gap(self):
        days=compare_days({'2026-10-01':[{'a':'new'}]}, {}, ['a'],mode='fill_gaps',claim={},
            choices={'2026-10-01':{'selection_id':1,'batch_ids':[]}})
        self.assertEqual(days[0]['status'],'different');self.assertTrue(days[0]['blocked'])

    def test_same_counts_and_total_do_not_prove_equality(self):
        old={'2026-10-01':[{'batch_id':1,'id':'a','金额':'10'},{'batch_id':1,'id':'b','金额':'20'}]}
        new={'2026-10-01':[{'id':'c','金额':'15'},{'id':'d','金额':'15'}]}
        self.assertTrue(compare_days(new,old,['id','金额'],mode='fill_gaps',claim={})[0]['blocked'])

    def test_multiset_keeps_multiplicity_ignores_order_and_excel_quotes(self):
        self.assertEqual(fingerprint_rows([{'a':'="1"'},{'a':'2'}],['a']),fingerprint_rows([{'a':'2'},{'a':'1'}],['a']))
        self.assertNotEqual(fingerprint_rows([{'a':'1'}],['a']),fingerprint_rows([{'a':'1'},{'a':'1'}],['a']))

    def test_empty_day_can_exist_but_cannot_silently_remove_old_rows(self):
        claim={'start':'2026-10-01','end':'2026-10-02','reason':'finance correction'}
        old={'2026-10-01':[{'batch_id':1,'a':'1'}]}
        days=compare_days({},old,['a'],mode='replace_range',claim=claim)
        self.assertTrue(days[0]['blocked']);self.assertFalse(days[1]['blocked'])
        claim['confirmed_empty_days']=['2026-10-01']
        self.assertFalse(compare_days({},old,['a'],mode='replace_range',claim=claim)[0]['blocked'])
        self.assertFalse(compare_days({},old,['a'],mode='fill_gaps',claim=claim)[0]['blocked'])


class CoverageDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_pg_env()
        cls.name='codex_ingest_coverage_test_'+uuid.uuid4().hex[:10]
        cls.admin=psycopg2.connect();cls.admin.autocommit=True
        with cls.admin.cursor() as cur:
            cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        cls.temp=tempfile.TemporaryDirectory()
        cls.conn=psycopg2.connect(dbname=cls.name)
        try:
            with cls.conn.cursor() as cur:
                for f in ('common/00_ods_file_ingest_log_postgres.sql','dim/32_dim_platform_shop_company_postgres.sql',
                          'common/52_ingest_batch_shop_context_postgres.sql','common/368_file_ingest_automation_postgres.sql',
                          'common/391_ingest_file_loader_diagnostics_postgres.sql',
                          'common/438_ingest_api_source_postgres.sql','common/467_incremental_etl_context_postgres.sql'):
                    cur.execute((ROOT/'sql'/f).read_text(encoding='utf-8'))
                cur.execute("ALTER TABLE ods.ods_file_ingest_log ADD COLUMN report_period_start date, ADD COLUMN report_period_end date")
                for report,(table,_,_) in SUPPORTED.items():
                    config=importlib.import_module(f'etl.{report.split("_")[0]}.load_{report}_ods').CONFIG
                    cur.execute(sql.SQL('''CREATE TABLE ods.{}(id BIGSERIAL PRIMARY KEY,batch_id BIGINT,
                        source_file_name TEXT,source_sheet_name TEXT,source_row_no INT,row_hash TEXT UNIQUE,
                        ingest_time TIMESTAMPTZ DEFAULT NOW(),{})''').format(sql.Identifier(table),
                        sql.SQL(',').join(sql.SQL('{} TEXT').format(sql.Identifier(c)) for c in config.expected_columns)))
                for table,field in [('ods_ks_settlement_raw','实际结算时间'),('ods_xhs_settlement_income_raw','结算时间'),
                                    ('ods_xhs_settlement_expense_raw','结算时间'),('ods_tmall_aggregate_fund_raw','入帐日期'),('ods_tmall_alipay_fund_raw','发生时间')]:
                    cur.execute(sql.SQL('CREATE TABLE ods.{}(id BIGINT,batch_id BIGINT,{} TEXT)').format(sql.Identifier(table),sql.Identifier(field)))
                for f in ('370_xhs_settlement_multi_sheet_ingest_postgres.sql','468_ingest_source_day_selection_postgres.sql','436_settlement_source_registry_postgres.sql',
                          '469_ingest_coverage_workflow_postgres.sql'):
                    cur.execute((ROOT/'sql/common'/f).read_text(encoding='utf-8'))
                # Only Dy current wallet is needed in these workflow fixtures.
                cur.execute('CREATE VIEW common.v_current_douyin_fund_raw AS SELECT * FROM common.v_selected_douyin_fund_raw')
                cur.execute('''CREATE TABLE ops.automation_step_run(step_run_id uuid,platform_code text,shop_code text,
                    business_date_start date,business_date_end date);
                    CREATE TABLE ops.automation_artifact(artifact_id uuid,step_run_id uuid,file_hash text,coverage_verified bool,
                    business_date_start date,business_date_end date);
                    CREATE SCHEMA dwd;
                    CREATE TABLE dwd.dwd_jd_platform_expense_source_detail(shop_identity_key text,shop_code text,
                        merchant_order_no text,stat_date date,source_batch_id bigint,signed_amount numeric,
                        source_document_type text,source_business_type text,event_at timestamp);''')
                for platform,name in [('douyin','抖音'),('jd','京东')]:
                    cur.execute('''INSERT INTO dim.dim_platform_shop_company(platform_code,platform_name,company_code,company_name,
                        shop_code,shop_name,shop_type,account_id) VALUES(%s,%s,'test','测试公司','one','测试店','test','test')''',(platform,name))
            cls.conn.commit()
        except Exception:
            cls._cleanup();raise

    @classmethod
    def _cleanup(cls):
        cls.conn.close();cls.temp.cleanup()
        with cls.admin.cursor() as cur:
            cur.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(cls.name)))
        cls.admin.close()

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    def setUp(self):
        args=argparse.Namespace(host=os.environ['PGHOST'],pg_port=int(os.getenv('PGPORT','5432')),
            dbname=self.name,user=os.getenv('PGUSER','postgres'),password=os.getenv('PGPASSWORD'))
        self.service=FileIngestService(args,Path(self.temp.name))
        self.run_ids=[]

    def tearDown(self):
        # All data live in the test DB; each test also starts from a clean state.
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute('TRUNCATE common.ingest_source_day_selection,ops.ingest_run,ops.operation_log,ods.ods_file_ingest_log CASCADE')
            for table,_,_ in SUPPORTED.values():
                cur.execute(sql.SQL('TRUNCATE ods.{}').format(sql.Identifier(table)))
            cur.execute('TRUNCATE dwd.dwd_jd_platform_expense_source_detail')
        self.conn.commit()

    def upload(self, days, *, mode='fill_gaps',source='manual',claim=None,report='douyin_settlement'):
        config=importlib.import_module(f'etl.{report.split("_")[0]}.load_{report}_ods').CONFIG
        table,date_field,amount_field=SUPPORTED[report]
        stream=io.StringIO();writer=csv.writer(stream);writer.writerow(config.expected_columns)
        if config.data_start_row_no==3:writer.writerow(['说明'])
        for d,amount,identity in days:
            row={date_field:d,amount_field:str(amount),'订单号':identity,'动帐流水号':identity,'动账账户':'wallet','结算账户':'wallet'}
            writer.writerow([row.get(c,'') for c in config.expected_columns])
        data=stream.getvalue().encode('utf-8-sig')
        run=self.service.create_run({'idempotency_key':uuid.uuid4().hex,'expected_file_count':1,'auto_refresh':False,'import_mode':mode},'tester',source)
        task=self.service.save_upload(str(run['run_id']),filename=report+'.csv',content=data,
            metadata={'client_file_id':'file','report_type':report,'shop_code':'one','coverage':claim or {}},operator='tester',ip_address=None)
        return str(run['run_id']),task

    def materialize(self, run_id):
        # The acceptance suite compares real parsed file rows to the real ODS;
        # loaders are separately covered. This isolates the publication contract.
        from apps.file_ingest.coverage import load_file
        with self.service.transaction() as cur:
            cur.execute('SELECT * FROM ops.ingest_file_task WHERE run_id=%s',(run_id,));task=dict(cur.fetchone())
            if task['status']=='duplicate':return
            columns,rows=load_file(task,self.service.storage_root)
            table=SUPPORTED[task['report_type']][0]
            cur.execute('''INSERT INTO ods.ods_file_ingest_log(platform_code,data_domain,source_file_path,source_file_name,
                file_hash,target_table,ingest_status,shop_code,shop_name,shop_identity_key,shop_mapping_status,
                total_rows,parsed_rows,success_rows,failed_rows,ingest_run_id,report_type)
                VALUES(%s,'test',%s,%s,%s,%s,'success','one','测试店',%s,'mapped',%s,%s,%s,0,%s,%s) RETURNING batch_id''',
                (task['resolved_platform_code'],str(self.service.storage_root/task['storage_path']),task['source_file_name'],
                 task['file_hash'],table,task['shop_identity_key'],len(rows),len(rows),len(rows),run_id,task['report_type']))
            batch=cur.fetchone()['batch_id']
            for row in rows:
                cur.execute(sql.SQL('INSERT INTO ods.{}(batch_id,{}) VALUES(%s,{})').format(sql.Identifier(table),
                    sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join(sql.Placeholder() for _ in columns)),
                    [batch]+[row.get(c) for c in columns])
            cur.execute("UPDATE ops.ingest_file_task SET status='success',batch_id=%s WHERE run_id=%s",(batch,run_id))

    def finish(self, run_id, token=None):
        self.service.complete_run(run_id,'tester',None,payload={'preflight_token':token})
        self.materialize(run_id)
        worker=FileIngestWorker.__new__(FileIngestWorker);worker.service=self.service
        worker._process_claimed_ingest_run(run_id)

    def selected(self):
        with self.service.transaction() as cur:
            cur.execute('SELECT "结算时间","订单号","结算金额" FROM common.v_current_douyin_settlement_raw ORDER BY 1,2')
            return [tuple(r.values()) for r in cur.fetchall()]

    def seed_wallet_source(self, cursor, shop, merchant, day, amount):
        cursor.execute('''INSERT INTO dim.dim_platform_shop_company(platform_code,platform_name,company_code,company_name,
            shop_code,shop_name,shop_type,account_id) SELECT 'jd','京东','test','测试公司',%s,'测试店','test','test'
            WHERE NOT EXISTS(SELECT 1 FROM dim.dim_platform_shop_company WHERE platform_code='jd' AND shop_code=%s)''',(shop,shop))
        cursor.execute('''INSERT INTO ods.ods_file_ingest_log(platform_code,data_domain,source_file_path,source_file_name,
            file_hash,target_table,ingest_status,shop_code,shop_name,shop_identity_key,shop_mapping_status,
            total_rows,parsed_rows,success_rows,failed_rows)
            VALUES('jd','fund','test-only','test-only','fixture-wallet','ods_jd_fund_raw','success',%s,'测试店',%s,'mapped',1,1,1,0)
            RETURNING batch_id''',(shop,'jd|'+shop))
        batch=cursor.fetchone()['batch_id'] if isinstance(cursor,psycopg2.extras.RealDictCursor) else cursor.fetchone()[0]
        cursor.execute('''INSERT INTO ods.ods_jd_fund_raw(batch_id,"商户订单号","交易订单号","支出类型","交易金额","交易类型","入账时间")
            VALUES(%s,%s,%s,'收入',%s,'商户结算',%s)''',(batch,merchant,merchant,str(amount),str(day)))
        return batch

    def test_range_fills_unknown_missing_day_and_preserves_equal_overlap(self):
        day1=('2026-10-01',10,'a');day2=('2026-10-02',20,'b')
        first,_=self.upload([day1]);self.finish(first)
        second,_=self.upload([day1,day2]);self.finish(second)
        self.assertEqual(len(self.selected()),2)
        with self.service.transaction() as cur:
            cur.execute('SELECT count(*) n FROM ods.ods_douyin_settlement_raw')
            self.assertEqual(cur.fetchone()['n'],3)

    def test_conflict_blocks_before_ods_and_explicit_range_replaces(self):
        first,_=self.upload([('2026-10-01',10,'a')]);self.finish(first)
        second,_=self.upload([('2026-10-01',20,'a')])
        report=self.service.coverage_preflight(second,{},'tester');self.assertTrue(report['blocked'])
        with self.assertRaises(CoverageConflict):self.finish(second)
        claim={'start':'2026-10-01','end':'2026-10-01','complete_export':True,'reason':'财务核对后更正'}
        report=self.service.coverage_preflight(second,{'import_mode':'replace_range','coverage':claim},'tester')
        self.finish(second,report['token'])
        self.assertEqual(self.selected()[0][2],'20')

    def test_duplicate_file_can_be_adopted_without_reinserting_ods(self):
        rows=[('2026-10-01',10,'a')]
        first,_=self.upload(rows);self.finish(first)
        second,task=self.upload(rows,mode='replace_range',claim={'start':'2026-10-01','end':'2026-10-01','complete_export':True,'reason':'重新采信'})
        self.assertEqual(task['status'],'duplicate')
        report=self.service.coverage_preflight(second,{},'tester');self.finish(second,report['token'])
        with self.service.transaction() as cur:
            cur.execute('SELECT count(*) n FROM ods.ods_douyin_settlement_raw');self.assertEqual(cur.fetchone()['n'],1)
            cur.execute('SELECT coverage_result FROM ops.ingest_run WHERE run_id=%s',(second,));self.assertEqual(cur.fetchone()['coverage_result']['selected_days'],1)

    def test_existing_successful_files_can_be_reused_without_upload_or_new_ods(self):
        first,_=self.upload([('2026-10-01',10,'a')]);self.finish(first)
        detail=self.service.reuse_run_files(first,{'idempotency_key':'review-once'},'tester',None)
        again=self.service.reuse_run_files(first,{'idempotency_key':'review-once'},'tester',None)
        self.assertEqual(detail['run']['run_id'],again['run']['run_id'])
        self.assertEqual(detail['files'][0]['status'],'duplicate')
        self.finish(str(detail['run']['run_id']))
        with self.service.transaction() as cur:
            cur.execute('SELECT count(*) n FROM ods.ods_douyin_settlement_raw');self.assertEqual(cur.fetchone()['n'],1)

    def test_cancelled_reuse_draft_does_not_delete_original_file(self):
        first,task=self.upload([('2026-10-01',10,'a')]);self.finish(first)
        reused=self.service.reuse_run_files(first,{'idempotency_key':'cancel-review'},'tester',None)
        self.service.delete_run(str(reused['run']['run_id']),'tester',None)
        self.assertTrue((self.service.storage_root/task['storage_path']).is_file())

    def test_source_selection_table_and_every_column_have_comments(self):
        with self.service.transaction() as cur:
            cur.execute('''SELECT obj_description(c.oid) table_comment,
                COUNT(*) FILTER(WHERE col_description(c.oid,a.attnum) IS NULL) missing_comments
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
                WHERE n.nspname='common' AND c.relname='ingest_source_day_selection' GROUP BY c.oid''')
            result=cur.fetchone();self.assertTrue(result['table_comment']);self.assertEqual(result['missing_comments'],0)

    def test_automatic_source_cannot_claim_manual_replacement(self):
        with self.assertRaises(ValueError):self.upload([],mode='replace_range',source='api')

    def test_real_loader_matches_preflight_and_publishes_source_choice(self):
        run_id,_=self.upload([('2026-10-01',10,'a')],report='douyin_fund')
        self.service.complete_run(run_id,'tester',None)
        worker=FileIngestWorker.__new__(FileIngestWorker);worker.service=self.service
        worker._process_claimed_ingest_run(run_id)
        detail=self.service.run_detail(run_id)
        self.assertEqual(detail['run']['status'],'success',detail['run'].get('error_message'))
        self.assertEqual(detail['files'][0]['loader_exit_code'],0)
        self.assertEqual(detail['run']['coverage_result']['selected_days'],1)

    def test_confirmed_zero_day_removes_only_derived_source_selection(self):
        first,_=self.upload([('2026-10-01',10,'a'),('2026-10-02',20,'b')]);self.finish(first)
        claim={'start':'2026-10-01','end':'2026-10-01','complete_export':True,'reason':'确认当日为零交易'}
        second,_=self.upload([],mode='replace_range',claim=claim)
        report=self.service.coverage_preflight(second,{},'tester');self.assertTrue(report['blocked'])
        claim['confirmed_empty_days']=['2026-10-01']
        report=self.service.coverage_preflight(second,{'coverage':claim},'tester');self.finish(second,report['token'])
        self.assertEqual(len(self.selected()),1);self.assertEqual(self.selected()[0][0],'2026-10-02')
        with self.service.transaction() as cur:
            cur.execute('SELECT count(*) n FROM ods.ods_douyin_settlement_raw');self.assertEqual(cur.fetchone()['n'],2)

    def test_crossing_ranges_preserve_days_outside_explicit_replacement(self):
        first,_=self.upload([('2026-10-01',10,'a'),('2026-10-02',20,'b')]);self.finish(first)
        claim={'start':'2026-10-02','end':'2026-10-03','complete_export':True,'reason':'更正交叉区间'}
        second,_=self.upload([('2026-10-02',30,'b'),('2026-10-03',40,'c')],mode='replace_range',claim=claim)
        report=self.service.coverage_preflight(second,{},'tester');self.finish(second,report['token'])
        self.assertEqual([r[2] for r in self.selected()],['10','30','40'])

    def test_duplicate_adoption_still_enqueues_metrics(self):
        rows=[('2026-10-01',10,'a')]
        first,_=self.upload(rows);self.finish(first)
        second,_=self.upload(rows)
        with self.service.transaction() as cur:cur.execute('UPDATE ops.ingest_run SET auto_refresh=TRUE WHERE run_id=%s',(second,))
        self.finish(second)
        self.assertTrue(self.service.run_detail(second)['etl_runs'])

    def test_preview_token_does_not_authorize_a_changed_source_revision(self):
        first,_=self.upload([('2026-10-01',10,'a')]);self.finish(first)
        claim={'start':'2026-10-01','end':'2026-10-01','complete_export':True,'reason':'预览后来源变化'}
        second,_=self.upload([('2026-10-01',20,'a')],mode='replace_range',claim=claim)
        report=self.service.coverage_preflight(second,{},'tester')
        third,_=self.upload([('2026-10-01',30,'a')],mode='replace_range',claim=claim)
        next_report=self.service.coverage_preflight(third,{},'tester');self.finish(third,next_report['token'])
        with self.assertRaises(CoverageConflict):self.finish(second,report['token'])

    def test_wallet_checks_every_group_in_scope_and_isolates_shops(self):
        from etl.jd.wallet_reconciliation import validate
        with self.conn.cursor() as cur:
            cur.execute('''INSERT INTO dwd.dwd_jd_platform_expense_source_detail VALUES
                ('jd|one','one','20261002batch','2026-10-01',1,10,'settlement','订单','2026-10-01'),
                ('jd|one','one','20261003batch','2026-10-02',2,20,'settlement','订单','2026-10-02'),
                ('jd|one','one','20261002batch','2026-10-02',3,10,'fund','商户结算','2026-10-02'),
                ('jd|one','one','20261003batch','2026-10-03',4,20,'fund','商户结算','2026-10-03'),
                ('jd|two','two','20261002batch','2026-10-01',5,99,'settlement','订单','2026-10-01'),
                ('jd|two','two','20261002batch','2026-10-02',6,99,'fund','商户结算','2026-10-02')''')
            self.seed_wallet_source(cur,'one','20261002batch','2026-10-02',10)
            self.seed_wallet_source(cur,'one','20261003batch','2026-10-03',20)
            two_batch=self.seed_wallet_source(cur,'two','20261002batch','2026-10-02',99)
            result=validate(cur,{'months':{'jd':['2026-10-01']},'shops':{'jd':['one','two']}})
            self.assertEqual(result['matched_count'],3);self.assertEqual(result['settlement_total'],129)
            cur.execute("UPDATE dwd.dwd_jd_platform_expense_source_detail SET signed_amount=98 WHERE shop_code='two' AND source_document_type='fund'")
            cur.execute('UPDATE ods.ods_jd_fund_raw SET "交易金额"=\'98\' WHERE batch_id=%s',(two_batch,))
            with self.assertRaisesRegex(RuntimeError,'amount_mismatch=1'):validate(cur)
        self.conn.rollback()

    def test_terminal_and_automation_use_the_same_http_preflight_contract(self):
        from apps.file_ingest.module import FileIngestModule
        from apps.file_ingest.cli import Client
        module=FileIngestModule.__new__(FileIngestModule);module.service=self.service
        _,seed=self.upload([('2026-10-01',10,'a')],report='douyin_fund')
        path=self.service.storage_root/seed['storage_path']
        principal=SimpleNamespace(can=lambda permission:True)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def send(self,data,status=200,headers=()):
                raw=json.dumps({'code':0 if status<400 else status,'data':data,'message':data if isinstance(data,str) else ''},ensure_ascii=False,default=str).encode()
                self.send_response(status)
                for key,value in headers:self.send_header(key,value)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def do_POST(self):
                try:
                    if self.path=='/api/auth/login':
                        self.rfile.read(int(self.headers.get('Content-Length',0)))
                        self.send({'csrf_token':'test-csrf'},headers=[('Set-Cookie','mocc_session=test-session; Path=/')]);return
                    if self.path.endswith('/files'):
                        self.send(*module.upload(self.path,self.headers,self.rfile,operator='test',ip_address=None));return
                    body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
                    response=module.dispatch('POST',self.path,payload=body,headers=self.headers,
                        context=principal if 'mocc_session' in self.headers.get('Cookie','') else None,operator='test')
                    self.send(*response)
                except Exception as exc:self.send(str(exc),getattr(exc,'http_status',400))
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base=f'http://127.0.0.1:{server.server_port}'
            client=Client(base,'test-user','test-only-password')
            manual=client.call('POST','/api/ingest/runs',{'source':'manual','idempotency_key':uuid.uuid4().hex,'expected_file_count':1,'auto_refresh':False})
            client.upload(manual['run_id'],{'path':str(path),'report_type':'douyin_fund','shop_code':'one'},Path('.'),0)
            first=client.call('POST',f"/api/ingest/runs/{manual['run_id']}/coverage-preflight",{})
            token='test-only-robot-token'
            with patch.dict(os.environ,{'INGEST_ROBOT_TOKEN':token}):
                def automatic(path,body):
                    request=urllib.request.Request(base+path,data=json.dumps(body).encode(),
                        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
                    with urllib.request.urlopen(request) as response:return json.load(response)['data']
                auto=automatic('/api/ingest/runs',{'source':'api','idempotency_key':uuid.uuid4().hex,'expected_file_count':1,'auto_refresh':False})
                original=client.call
                def api_call(method,path,**kwargs):
                    # Feed the terminal serializer to the identical multipart API,
                    # with the automated principal and mandatory idempotency key.
                    request=urllib.request.Request(base+path,data=kwargs['body'],method=method,
                        headers={'Authorization':'Bearer '+token,'Idempotency-Key':kwargs['key'],'Content-Type':kwargs['content_type']})
                    with urllib.request.urlopen(request) as response:return json.load(response)['data']
                client.call=api_call
                client.upload(auto['run_id'],{'path':str(path),'report_type':'douyin_fund','shop_code':'one'},Path('.'),0)
                second=automatic(f"/api/ingest/runs/{auto['run_id']}/coverage-preflight",{})
                client.call=original
            self.assertEqual(first['summary'],second['summary']);self.assertEqual(first['blocked'],second['blocked'])
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)

    def test_changed_idempotent_upload_is_rejected(self):
        run_id,task=self.upload([('2026-10-01',10,'a')])
        with self.assertRaises(ConflictError):
            self.service.save_upload(run_id,filename='other.csv',content=b'changed',metadata={'client_file_id':'file'},operator='tester',ip_address=None)

    def test_new_retry_has_later_snapshot_preserves_original_and_queues_full_chain(self):
        run_id,_=self.upload([('2026-10-01',10,'a')]);self.finish(run_id)
        with self.service.transaction() as cur:
            parent=self.service.create_etl_run({'jd_settlement'},trigger_type='ingest_complete',scope='affected',operator='tester',ingest_run_id=run_id,cursor=cur)
            context={'version':1,'mode':'incremental','trigger_type':'ingest_complete','months':{'jd':['2026-10-01']},'shops':{'jd':['one']},'batch_cutoff':0,'source_selection_cutoff':0}
            cur.execute("UPDATE ops.etl_run SET status='partial_failed',refresh_context=%s WHERE etl_run_id=%s",(Json(context),str(parent['etl_run_id'])))
            cur.execute("UPDATE ops.etl_task SET status='failed' WHERE etl_run_id=%s RETURNING etl_task_id",(str(parent['etl_run_id']),));task_id=str(cur.fetchone()['etl_task_id'])
        result=self.service.retry_etl_task(task_id,'tester',None)
        self.assertGreater(result['batch_cutoff'],0)
        with self.service.transaction() as cur:
            cur.execute('SELECT status,refresh_context FROM ops.etl_run WHERE etl_run_id=%s',(str(parent['etl_run_id']),));old=cur.fetchone()
            self.assertEqual(old['status'],'partial_failed');self.assertEqual(old['refresh_context']['batch_cutoff'],0)
            cur.execute('SELECT etl_key,status FROM ops.etl_task WHERE etl_run_id=%s',(str(result['etl_run_id']),));tasks=cur.fetchall()
            self.assertGreater(len(tasks),1);self.assertTrue(all(t['status']=='queued' for t in tasks))

    def legacy_upload(self, rows, *, report='douyin_settlement'):
        run_id,task=self.upload(rows,report=report)
        self.materialize(run_id)
        with self.service.transaction() as cur:
            cur.execute("UPDATE ops.ingest_run SET status='success',success_file_count=1 WHERE run_id=%s",(run_id,))
            cur.execute('SELECT batch_id FROM ops.ingest_file_task WHERE run_id=%s',(run_id,))
            batch=cur.fetchone()['batch_id']
        return run_id,batch

    def failed_douyin_run(self, run_id):
        with self.service.transaction() as cur:
            parent=self.service.create_etl_run({'douyin_settlement'},trigger_type='ingest_complete',scope='affected',
                operator='tester',ingest_run_id=run_id,cursor=cur)
            context={'version':1,'mode':'incremental','trigger_type':'ingest_complete','months':{'douyin':['2026-10-01']},
                'shops':{'douyin':['one']},'batch_cutoff':0,'source_selection_cutoff':0}
            cur.execute("UPDATE ops.etl_run SET status='failed',refresh_context=%s WHERE etl_run_id=%s",
                (Json(context),str(parent['etl_run_id'])))
            cur.execute("UPDATE ops.etl_task SET status='failed' WHERE etl_run_id=%s AND etl_key='douyin_settlement' RETURNING etl_task_id",
                (str(parent['etl_run_id']),))
            return str(cur.fetchone()['etl_task_id'])

    def test_latest_retry_recovers_equal_legacy_overlap_and_missing_dates_atomically(self):
        _,old_batch=self.legacy_upload([('2026-10-01',10,'a')])
        run_id,new_batch=self.legacy_upload([('2026-10-01',10,'a'),('2026-10-02',20,'b')])
        task_id=self.failed_douyin_run(run_id)
        result=self.service.retry_etl_task(task_id,'tester',None)
        self.assertEqual(result['coverage_recovery']['summary'],{'same':1,'new_only':1})
        self.assertEqual(len(self.selected()),2)
        with self.service.transaction() as cur:
            cur.execute('SELECT batch_ids FROM common.v_ingest_source_day_selection ORDER BY stat_date')
            self.assertEqual([r['batch_ids'] for r in cur.fetchall()],[[old_batch],[new_batch]])
            cur.execute('SELECT count(*) n FROM ods.ods_douyin_settlement_raw');self.assertEqual(cur.fetchone()['n'],3)
            cur.execute('SELECT refresh_context FROM ops.etl_run WHERE etl_run_id=%s',(result['etl_run_id'],))
            self.assertGreater(cur.fetchone()['refresh_context']['source_selection_cutoff'],0)
        again=self.service.retry_etl_task(task_id,'tester',None)
        self.assertTrue(again['reused']);self.assertEqual(str(again['etl_run_id']),result['etl_run_id'])

    def test_legacy_retry_conflict_never_partially_selects_days_or_queues_a_child(self):
        self.legacy_upload([('2026-10-02',10,'a')])
        run_id,_=self.legacy_upload([('2026-10-01',5,'gap'),('2026-10-02',20,'a')])
        task_id=self.failed_douyin_run(run_id)
        with self.assertRaisesRegex(CoverageConflict,'未自动覆盖、未创建重试'):
            self.service.retry_etl_task(task_id,'tester',None)
        with self.service.transaction() as cur:
            cur.execute('SELECT count(*) n FROM common.ingest_source_day_selection');self.assertEqual(cur.fetchone()['n'],0)
            cur.execute('SELECT count(*) n FROM ops.etl_run WHERE parent_etl_run_id IS NOT NULL');self.assertEqual(cur.fetchone()['n'],0)
            cur.execute('SELECT coverage_result FROM ops.ingest_run WHERE run_id=%s',(run_id,));self.assertIsNone(cur.fetchone()['coverage_result'])

    def test_legacy_recovery_respects_an_existing_explicit_choice(self):
        first,_=self.upload([('2026-10-01',10,'a')]);self.finish(first)
        run_id,_=self.legacy_upload([('2026-10-01',99,'a'),('2026-10-02',20,'b')])
        result=self.service.retry_etl_task(self.failed_douyin_run(run_id),'tester',None)
        self.assertEqual(result['coverage_recovery']['summary'],{'new_only':1})
        self.assertEqual([r[2] for r in self.selected()],['10','20'])

    def test_replay_keeps_legacy_sources_unchanged(self):
        run_id,_=self.legacy_upload([('2026-10-01',10,'a')])
        result=self.service.retry_etl_task(self.failed_douyin_run(run_id),'tester',None,snapshot_policy='replay',confirm_replay_publish=True)
        self.assertNotIn('coverage_recovery',result)
        self.assertTrue(result['confirm_replay_publish'])
        with self.service.transaction() as cur:
            cur.execute('SELECT count(*) n FROM common.ingest_source_day_selection');self.assertEqual(cur.fetchone()['n'],0)

    def test_reuse_of_legacy_monthly_file_compares_before_its_own_unselected_rows(self):
        self.legacy_upload([('2026-10-01',10,'a')])
        run_id,_=self.legacy_upload([('2026-10-01',10,'a'),('2026-10-02',20,'b')])
        draft=self.service.reuse_run_files(run_id,{'idempotency_key':'legacy-review'},'tester',None)
        new_id=str(draft['run']['run_id'])
        report=self.service.coverage_preflight(new_id,{},'tester')
        self.assertFalse(report['blocked']);self.assertEqual(report['summary'],{'same':1,'new_only':1})
        self.finish(new_id)
        self.assertEqual(len(self.selected()),2)

    def test_fund_baseline_excludes_new_batch_before_native_flow_version_selection(self):
        from apps.file_ingest.coverage import load_file,effective_old_rows
        _,old_batch=self.legacy_upload([('2026-10-01',10,'a')],report='douyin_fund')
        run_id,new_batch=self.legacy_upload([('2026-10-01',20,'a')],report='douyin_fund')
        with self.service.transaction() as cur:
            cur.execute('DROP VIEW common.v_current_douyin_fund_raw')
            cur.execute('''CREATE VIEW common.v_current_douyin_fund_raw AS
                SELECT DISTINCT ON("动账账户","动帐流水号") * FROM common.v_selected_douyin_fund_raw
                ORDER BY "动账账户","动帐流水号",ingest_time DESC,id DESC''')
            try:
                cur.execute('SELECT * FROM ops.ingest_file_task WHERE run_id=%s',(run_id,));task=dict(cur.fetchone())
                columns,_=load_file(task,self.service.storage_root)
                old=effective_old_rows(cur,task,columns,{new_batch},('2026-10-01','2026-10-01'))
                self.assertEqual(old['2026-10-01'][0]['batch_id'],old_batch)
                self.assertEqual(old['2026-10-01'][0]['动账金额'],'10')
            finally:
                cur.execute('DROP VIEW common.v_current_douyin_fund_raw')
                cur.execute('CREATE VIEW common.v_current_douyin_fund_raw AS SELECT * FROM common.v_selected_douyin_fund_raw')

    def test_new_selection_is_invisible_to_an_old_selection_cutoff(self):
        first,_=self.upload([('2026-10-01',10,'a')]);self.finish(first)
        with self.service.transaction() as cur:
            cur.execute('SELECT max(selection_id) revision FROM common.ingest_source_day_selection');revision=cur.fetchone()['revision']
        second,_=self.upload([('2026-10-01',20,'a')],mode='replace_range',claim={'start':'2026-10-01','end':'2026-10-01','complete_export':True,'reason':'更正'})
        preview=self.service.coverage_preflight(second,{},'tester');self.finish(second,preview['token'])
        with self.service.transaction() as cur:
            cur.execute("SELECT set_config('mock_coffice.source_selection_cutoff',%s,TRUE)",(str(revision),))
            cur.execute('SELECT "结算金额" FROM common.v_current_douyin_settlement_raw');self.assertEqual(cur.fetchone()['结算金额'],'10')

    def test_reused_cursor_keeps_its_frozen_selection_after_commit(self):
        from etl.common.refresh_runtime import connection_factory
        first,_=self.upload([('2026-10-01',10,'a')]);self.finish(first)
        with self.service.transaction() as cur:
            cur.execute('SELECT max(selection_id) revision FROM common.ingest_source_day_selection');revision=cur.fetchone()['revision']
        claim={'start':'2026-10-01','end':'2026-10-01','complete_export':True,'reason':'更正'}
        second,_=self.upload([('2026-10-01',20,'a')],mode='replace_range',claim=claim)
        preview=self.service.coverage_preflight(second,{},'tester');self.finish(second,preview['token'])
        with self.service.transaction() as cur:
            cur.execute('SELECT max(batch_id) cutoff FROM ods.ods_file_ingest_log');cutoff=cur.fetchone()['cutoff']
        context={'version':1,'mode':'incremental','trigger_type':'ingest_complete','months':{'douyin':['2026-10-01']},
            'shops':{'douyin':['one']},'batch_cutoff':cutoff,'source_selection_cutoff':revision}
        conn=psycopg2.connect(**self.service.connect_kwargs,connection_factory=connection_factory(context))
        try:
            cur=conn.cursor()
            for _ in range(2):
                cur.execute('SELECT "结算金额" FROM common.v_current_douyin_settlement_raw')
                self.assertEqual(cur.fetchone()[0],'10')
                conn.commit()
        finally:conn.close()

    def test_selected_jd_view_obeys_real_incremental_runtime_bounds(self):
        from etl.common.refresh_runtime import connection_factory
        first,_=self.upload([('2026-10-01',10,'a')],report='jd_fund');self.finish(first)
        second,_=self.upload([('2026-09-01',30,'b')],report='jd_fund');self.finish(second)
        with self.service.transaction() as cur:
            cur.execute('''CREATE TABLE IF NOT EXISTS dwd.dwd_jd_scope_test(stat_date date,platform_code text,shop_code text,amount numeric);
                SELECT MAX(batch_id) cutoff FROM ods.ods_file_ingest_log''');cutoff=cur.fetchone()['cutoff']
            cur.execute('SELECT MAX(selection_id) revision FROM common.ingest_source_day_selection');revision=cur.fetchone()['revision']
        context={'version':1,'mode':'incremental','trigger_type':'ingest_complete','months':{'jd':['2026-10-01']},
            'shops':{'jd':['one']},'batch_cutoff':cutoff,'source_selection_cutoff':revision}
        with psycopg2.connect(**self.service.connect_kwargs,connection_factory=connection_factory(context)) as conn:
            with conn.cursor() as cur:
                cur.execute('''TRUNCATE TABLE dwd.dwd_jd_scope_test;
                    INSERT INTO dwd.dwd_jd_scope_test(stat_date,platform_code,shop_code,amount)
                    SELECT "入账时间"::date,'jd','one',"交易金额"::numeric FROM common.v_selected_jd_fund_raw''')
                cur.execute('SELECT amount FROM dwd.dwd_jd_scope_test');self.assertEqual(cur.fetchall(),[(10,)])
        # psycopg's context manager does not close the connection.
        conn.close()


if __name__=='__main__':unittest.main()
