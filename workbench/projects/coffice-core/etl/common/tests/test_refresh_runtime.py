"""Regression tests for bounded writes and immutable source snapshots."""
from __future__ import annotations

import os
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from hashlib import sha256
from unittest.mock import patch

import psycopg2
from psycopg2.extras import RealDictCursor

from apps.file_ingest.refresh_scope import build_refresh_context, _previous_order_months
from etl.common.refresh_runtime import RefreshScope, connection_factory, next_month, split_statements
from etl.common.settlement_sources import backfill_receipts


CONTEXT = {'version': 1, 'mode': 'incremental', 'trigger_type': 'ingest_complete',
           'months': {'ks': ['2026-10-01']}, 'shops': {'ks': ['one']}, 'batch_cutoff': 2}


class RefreshPolicyTests(unittest.TestCase):
    def test_automatic_full_refresh_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '只能由人工'):
            RefreshScope({'version': 1, 'mode': 'full', 'trigger_type': 'ingest_complete'})

    def test_unknown_scope_never_becomes_full(self):
        for context in ({}, {'version': 1, 'mode': 'unknown'}, {'version': 2, 'mode': 'incremental'}):
            with self.assertRaises(ValueError):
                RefreshScope(context)

    def test_manual_full_entrypoint_keeps_the_original_installation_path(self):
        from etl.common.refresh_entrypoint import main
        original = psycopg2.connect
        observed = []
        context = {'version':1, 'mode':'full', 'trigger_type':'manual'}
        with patch.dict(os.environ, {'MOCK_COFFICE_REFRESH_CONTEXT':json.dumps(context)}), \
             patch.object(sys, 'argv', ['refresh', '--etl-key', 'ks_settlement']), \
             patch('etl.common.refresh_entrypoint.runpy.run_module', side_effect=lambda *a, **kw: observed.append(psycopg2.connect)):
            main()
        self.assertEqual([original], observed)

    def test_months_must_be_month_starts(self):
        with self.assertRaisesRegex(ValueError, '自然月首日'):
            RefreshScope({**CONTEXT, 'months': {'ks': ['2026-10-02']}})

    def test_calendar_boundaries(self):
        self.assertEqual(date(2027, 1, 1), next_month(date(2026, 12, 1)))
        self.assertEqual(date(2025, 12, 1), next_month(date(2026, 1, 1), -1))

    def test_split_keeps_procedures_strings_and_comments_intact(self):
        statements = split_statements("-- preface;\nDO $body$ BEGIN RAISE NOTICE 'hello;'; END; $body$; SELECT ';'; /* ; */ SELECT 2;")
        self.assertEqual(3, len(statements))
        self.assertIn("RAISE NOTICE 'hello;'", statements[0])
        self.assertEqual("SELECT ';'", statements[1])


@unittest.skipUnless(os.getenv('INCREMENTAL_TEST_DB'), 'requires isolated INCREMENTAL_TEST_DB')
class RefreshDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dbname = os.environ['INCREMENTAL_TEST_DB']
        if not cls.dbname.startswith('codex_incremental_test_'):
            raise RuntimeError('Only an explicitly isolated temporary test database is allowed')
        cls.kwargs = dict(host=os.environ['PGHOST'], port=os.getenv('PGPORT', '5432'),
                          user=os.environ['PGUSER'], password=os.environ.get('PGPASSWORD'), dbname=cls.dbname)
        cls.control = psycopg2.connect(**cls.kwargs)
        with cls.control.cursor() as cur:
            cur.execute('''CREATE SCHEMA ods; CREATE SCHEMA common; CREATE SCHEMA dwd; CREATE SCHEMA dws; CREATE SCHEMA ads; CREATE SCHEMA ops;
                CREATE TABLE ods.ods_file_ingest_log(batch_id bigint,platform_code text,shop_code text,
                    target_table text DEFAULT 'ods_ks_fund_raw',report_period_start date,report_period_end date,
                    parsed_rows bigint DEFAULT 1,file_hash text,ingest_status text DEFAULT 'success');
                CREATE TABLE ops.ingest_file_task(run_id text,status text,batch_id bigint,file_task_id bigint,coverage jsonb DEFAULT '{}'::jsonb);
                CREATE TABLE ops.ingest_file_task_batch(file_task_id bigint,batch_id bigint);
                CREATE TABLE ops.automation_step_run(step_run_id bigint,platform_code text,shop_code text,
                    business_date_start date,business_date_end date);
                CREATE TABLE ops.automation_artifact(step_run_id bigint,file_hash text,coverage_verified boolean,
                    business_date_start date,business_date_end date);
                CREATE TABLE ods.ods_ks_fund_raw(id bigint,batch_id bigint,"入账时间" text,amount numeric,flow_no text);
                CREATE VIEW common.v_ingest_batch_shop_context AS SELECT *,
                    'ks|'||shop_code AS shop_identity_key,'test_company'::text AS company_code,
                    'mapped'::text AS shop_mapping_status FROM ods.ods_file_ingest_log;
                CREATE VIEW common.v_current_ks_fund_raw AS
                  SELECT DISTINCT ON (c.shop_code,r.flow_no) r.* FROM ods.ods_ks_fund_raw r
                  JOIN common.v_ingest_batch_shop_context c USING(batch_id)
                  ORDER BY c.shop_code,r.flow_no,r.batch_id DESC;
                CREATE TABLE dwd.dwd_ks_test(stat_date date,platform_code text,shop_code text,amount numeric,source_id bigint);
                CREATE TABLE ads.ads_test_daily(LIKE dwd.dwd_ks_test);
                CREATE TABLE ads.ads_test_company_daily(stat_date date,platform_code text,amount numeric);
                CREATE TABLE dws.dws_ks_rank_input(stat_date date,platform_code text,shop_code text,amount numeric);
                CREATE TABLE ads.ads_influencer_monthly_ranking_test(stat_month date,platform_code text,shop_code text,amount numeric,previous_amount numeric);
                INSERT INTO dws.dws_ks_rank_input VALUES ('2026-09-01','ks','one',4),('2026-10-02','ks','one',8),
                    ('2026-10-02','ks','two',7),('2026-11-01','ks','one',20);
                INSERT INTO ads.ads_influencer_monthly_ranking_test VALUES ('2026-09-01','ks','one',4,0),
                    ('2026-10-01','ks','one',1,4),('2026-10-01','ks','two',7,0),('2026-11-01','ks','one',20,1);
                CREATE TABLE dws.dws_ks_allocation_test(LIKE dwd.dwd_ks_test);
                CREATE PROCEDURE dws.refresh_operating_sales_product_allocation(source_table regclass,target_table regclass,flag boolean)
                LANGUAGE plpgsql AS $proc$ BEGIN EXECUTE FORMAT('TRUNCATE TABLE %s',target_table);
                    EXECUTE FORMAT('INSERT INTO %s SELECT * FROM %s',target_table,source_table); END; $proc$;
                CREATE TABLE dws.dws_douyin_calendar(stat_date date,platform_code text,amount numeric);
                INSERT INTO dws.dws_douyin_calendar VALUES ('2026-10-02','douyin',1);
                CREATE TABLE ads.ads_promotion_expense_company_shop_daily(stat_date date,platform_code text,shop_code text,amount numeric);
                INSERT INTO ods.ods_file_ingest_log(batch_id,platform_code,shop_code)
                    VALUES (1,'ks','one'),(2,'ks','one'),(3,'ks','one');
                INSERT INTO ods.ods_ks_fund_raw VALUES
                    (1,1,'2026-09-01',4,'old'),(2,2,'2026-10-02',8,'new'),(3,3,'2026-10-02',99,'new');
                INSERT INTO dwd.dwd_ks_test VALUES ('2026-09-01','ks','one',4,1),('2026-10-02','ks','one',1,2),
                    ('2026-10-02','ks','two',7,7),('2026-10-02','pdd','one',9,9);
                INSERT INTO ads.ads_test_daily SELECT * FROM dwd.dwd_ks_test;
                INSERT INTO dws.dws_ks_allocation_test SELECT * FROM dwd.dwd_ks_test;
            ''')
        cls.control.commit()

    @classmethod
    def tearDownClass(cls):
        cls.control.close()

    def setUp(self):
        self.connection = psycopg2.connect(**self.kwargs, connection_factory=connection_factory(CONTEXT))
        self.cursor = self.connection.cursor()

    def tearDown(self):
        self.connection.rollback()
        self.cursor.close()
        self.connection.close()

    def refresh(self):
        self.cursor.execute('''TRUNCATE TABLE dwd.dwd_ks_test;
            WITH normalized AS (SELECT r.*,c.shop_code FROM common.v_current_ks_fund_raw r
              JOIN common.v_ingest_batch_shop_context c USING(batch_id))
            INSERT INTO dwd.dwd_ks_test(stat_date,platform_code,shop_code,amount,source_id)
            SELECT "入账时间"::date,'ks',shop_code,amount,id FROM normalized''')

    def test_scope_preserves_other_month_shop_and_platform(self):
        self.refresh()
        self.cursor.execute('SELECT stat_date,platform_code,shop_code,amount FROM dwd.dwd_ks_test ORDER BY 1,2,3')
        self.assertEqual([(date(2026,9,1),'ks','one',4),(date(2026,10,2),'ks','one',8),
                          (date(2026,10,2),'ks','two',7),(date(2026,10,2),'pdd','one',9)], self.cursor.fetchall())

    def test_leading_comments_do_not_bypass_scoped_truncate(self):
        self.cursor.execute('/* refresh October only */\n-- keep other months\nTRUNCATE TABLE dwd.dwd_ks_test')
        self.cursor.execute('SELECT COUNT(*) FROM dwd.dwd_ks_test')
        self.assertEqual(3, self.cursor.fetchone()[0])

    def test_scope_uses_verified_receipt_including_zero_transaction_months(self):
        with self.connection.raw_cursor() as cur:
            cur.execute('''INSERT INTO ops.ingest_file_task(run_id,status,batch_id,file_task_id) VALUES ('scope-test','success',1,1);
                UPDATE ods.ods_file_ingest_log SET file_hash='receipt-hash',parsed_rows=0 WHERE batch_id=1;
                DELETE FROM ods.ods_ks_fund_raw WHERE batch_id=1;
                INSERT INTO ops.automation_step_run VALUES (1,'ks','one','2026-08-01','2026-09-30');
                INSERT INTO ops.automation_artifact VALUES (1,'receipt-hash',TRUE,'2026-08-01','2026-09-30')''')
            context = build_refresh_context(cur, {'trigger_type':'ingest_complete','scope':'affected','ingest_run_id':'scope-test'})
            self.assertEqual({'ks':['2026-08-01','2026-09-01']}, context['months'])
            self.assertEqual({'ks':['one']}, context['shops'])

    def test_new_receipt_coverage_is_visible_in_the_same_refresh_transaction(self):
        with tempfile.TemporaryDirectory(prefix='codex_coverage_test_') as directory:
            path = Path(directory) / 'receipt-source.txt'
            path.write_text('immutable source fixture', encoding='utf-8')
            digest = sha256(path.read_bytes()).hexdigest()
            with self.connection.raw_cursor() as cur:
                cur.execute('''ALTER TABLE ods.ods_file_ingest_log ADD COLUMN source_file_path text;
                    ALTER TABLE ods.ods_file_ingest_log ADD COLUMN failed_rows bigint DEFAULT 0;
                    ALTER TABLE ods.ods_file_ingest_log ADD COLUMN shop_identity_key text DEFAULT 'ks|one';
                    ALTER TABLE ops.automation_artifact ADD COLUMN artifact_id text DEFAULT 'receipt';
                    ALTER TABLE ops.automation_artifact ADD COLUMN batch_id bigint;
                    CREATE TABLE common.settlement_source_registry(batch_id bigint,source_group_key text,
                        period_start date,period_end date,file_hash text,evidence_type text,evidence jsonb);
                    CREATE VIEW common.v_settlement_source_batch AS
                        SELECT l.batch_id,l.platform_code,c.shop_identity_key,l.file_hash,r.period_start,r.period_end
                        FROM ods.ods_file_ingest_log l JOIN common.v_ingest_batch_shop_context c USING(batch_id)
                        LEFT JOIN common.settlement_source_registry r USING(batch_id);
                    CREATE VIEW common.v_settlement_source_days AS
                        SELECT batch_id,"入账时间"::date AS stat_date,COUNT(*) AS source_rows
                        FROM ods.ods_ks_fund_raw GROUP BY 1,2;
                    INSERT INTO ops.automation_step_run VALUES (1,'ks','one','2026-09-01','2026-09-30');
                    INSERT INTO ops.automation_artifact(step_run_id,file_hash,coverage_verified,business_date_start,business_date_end)
                        VALUES (1,'placeholder',TRUE,'2026-09-01','2026-09-30')''')
                cur.execute("UPDATE ods.ods_file_ingest_log SET target_table='ods_ks_settlement_raw',file_hash=%s,source_file_path=%s WHERE batch_id=1", (digest,str(path)))
                cur.execute('UPDATE ops.automation_artifact SET file_hash=%s', (digest,))
            self.cursor.execute('SELECT period_start FROM common.v_settlement_source_batch WHERE batch_id=1')
            self.assertIsNone(self.cursor.fetchone()[0])
            backfill_receipts(self.cursor, 'ks')
            self.cursor.execute('SELECT period_start,period_end FROM common.v_settlement_source_batch WHERE batch_id=1')
            self.assertEqual((date(2026,9,1),date(2026,9,30)),self.cursor.fetchone())

    def test_undated_batch_cannot_borrow_another_batchs_month(self):
        with self.connection.raw_cursor() as cur:
            cur.execute('''INSERT INTO ops.ingest_file_task(run_id,status,batch_id,file_task_id) VALUES ('scope-test','success',1,1),('scope-test','success',2,2);
                UPDATE ods.ods_file_ingest_log SET parsed_rows=0 WHERE batch_id=2;
                DELETE FROM ods.ods_ks_fund_raw WHERE batch_id=2''')
            with self.assertRaisesRegex(ValueError, '批次2无法确定'):
                build_refresh_context(cur, {'trigger_type':'ingest_complete','scope':'affected','ingest_run_id':'scope-test'})

    def test_duplicate_adoption_keeps_the_existing_batch_business_scope(self):
        with self.connection.raw_cursor() as cur:
            cur.execute("INSERT INTO ops.ingest_file_task(run_id,status,batch_id,file_task_id) VALUES ('scope-test','duplicate',1,1)")
            context = build_refresh_context(cur, {'trigger_type':'ingest_complete','scope':'affected','ingest_run_id':'scope-test'})
            self.assertEqual({'ks':['2026-09-01']}, context['months'])
            self.assertEqual([1], context['batch_ids'])

    def test_source_cutoff_applies_before_latest_version_selection(self):
        self.cursor.execute('SELECT id,amount FROM common.v_current_ks_fund_raw ORDER BY id')
        self.assertEqual([(1,4),(2,8)], self.cursor.fetchall())
        self.cursor.execute('SELECT COUNT(*) FROM common.v_current_ks_fund_raw')
        self.assertEqual(2, self.cursor.fetchone()[0])
        self.assertEqual(1, len([e for e in self.connection.refresh_events if e.get('source')=='common.v_current_ks_fund_raw']))

    def test_late_finishing_older_batch_cannot_enter_the_frozen_snapshot(self):
        factory = connection_factory({**CONTEXT, 'batch_cutoff':3, 'excluded_batch_ids':[3]})
        conn = psycopg2.connect(**self.kwargs, connection_factory=factory)
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT id,amount FROM common.v_current_ks_fund_raw ORDER BY id')
                self.assertEqual([(1,4),(2,8)], cur.fetchall())
        finally:
            conn.rollback()
            conn.close()

    def test_explicit_manual_full_refresh_can_replace_the_whole_metric(self):
        factory = connection_factory({'version':1, 'mode':'full', 'trigger_type':'manual'})
        conn = psycopg2.connect(**self.kwargs, connection_factory=factory)
        try:
            with conn.cursor() as cur:
                cur.execute('''TRUNCATE dwd.dwd_ks_test;
                    INSERT INTO dwd.dwd_ks_test(stat_date,platform_code,shop_code,amount,source_id)
                    SELECT r."入账时间"::date,'ks',c.shop_code,r.amount,r.id
                    FROM common.v_current_ks_fund_raw r JOIN common.v_ingest_batch_shop_context c USING(batch_id)''')
                cur.execute('SELECT stat_date,amount FROM dwd.dwd_ks_test ORDER BY 1')
                self.assertEqual([(date(2026,9,1),4),(date(2026,10,2),99)],cur.fetchall())
        finally:
            conn.rollback()
            conn.close()

    def test_explicit_dictionary_cursor_keeps_the_same_snapshot(self):
        with self.connection.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT id,amount FROM common.v_current_ks_fund_raw ORDER BY id')
            self.assertEqual([1,2],[r['id'] for r in cur.fetchall()])

    def test_committed_snapshot_can_be_used_again_on_the_same_connection(self):
        self.refresh()
        try:
            self.connection.commit()
            with self.control.cursor() as cur:
                cur.execute("SELECT amount FROM dwd.dwd_ks_test WHERE platform_code='ks' AND shop_code='one' AND stat_date='2026-10-02'")
                self.assertEqual(8, cur.fetchone()[0])
            self.refresh()
            self.cursor.execute("SELECT amount FROM dwd.dwd_ks_test WHERE platform_code='ks' AND shop_code='one' AND stat_date='2026-10-02'")
            self.assertEqual(8, self.cursor.fetchone()[0])
        finally:
            self.connection.rollback()
            with self.control.cursor() as cur:
                cur.execute("UPDATE dwd.dwd_ks_test SET amount=1 WHERE platform_code='ks' AND shop_code='one' AND stat_date='2026-10-02'")
            self.control.commit()

    def test_derived_aggregation_keeps_other_shops_contributions(self):
        self.refresh()
        self.cursor.execute('''TRUNCATE ads.ads_test_company_daily;
            INSERT INTO ads.ads_test_company_daily(stat_date,platform_code,amount)
            SELECT stat_date,platform_code,SUM(amount) FROM dwd.dwd_ks_test GROUP BY 1,2''')
        self.cursor.execute('SELECT amount FROM ads.ads_test_company_daily')
        self.assertEqual([(15,)], self.cursor.fetchall())

    def test_monthly_ranking_rebuilds_other_shops_and_next_month_comparison(self):
        self.cursor.execute('''TRUNCATE ads.ads_influencer_monthly_ranking_test;
            INSERT INTO ads.ads_influencer_monthly_ranking_test(stat_month,platform_code,shop_code,amount,previous_amount)
            WITH monthly AS (SELECT DATE_TRUNC('month',stat_date)::date AS month,platform_code,shop_code,SUM(amount) AS amount
                FROM dws.dws_ks_rank_input GROUP BY 1,2,3)
            SELECT current.month,current.platform_code,current.shop_code,current.amount,COALESCE(previous.amount,0)
            FROM monthly current LEFT JOIN monthly previous ON previous.month=(current.month-INTERVAL '1 month')::date
                AND previous.platform_code=current.platform_code AND previous.shop_code=current.shop_code''')
        self.cursor.execute('SELECT stat_month,shop_code,amount,previous_amount FROM ads.ads_influencer_monthly_ranking_test ORDER BY 1,2')
        self.assertEqual([(date(2026,9,1),'one',4,0),(date(2026,10,1),'one',8,4),
                          (date(2026,10,1),'two',7,0),(date(2026,11,1),'one',20,8)],self.cursor.fetchall())

    def test_allocation_procedure_truncates_only_its_temporary_target(self):
        self.refresh()
        self.cursor.execute("CALL dws.refresh_operating_sales_product_allocation('dwd.dwd_ks_test'::REGCLASS,'dws.dws_ks_allocation_test'::REGCLASS,TRUE)")
        self.cursor.execute('SELECT stat_date,platform_code,shop_code,amount FROM dws.dws_ks_allocation_test ORDER BY 1,2,3')
        self.assertEqual([(date(2026,9,1),'ks','one',4),(date(2026,10,2),'ks','one',8),
                          (date(2026,10,2),'ks','two',7),(date(2026,10,2),'pdd','one',9)],self.cursor.fetchall())

    def test_zero_promotion_rows_keep_cross_platform_date_calendar(self):
        self.cursor.execute('''TRUNCATE ads.ads_promotion_expense_company_shop_daily;
            INSERT INTO ads.ads_promotion_expense_company_shop_daily(stat_date,platform_code,shop_code,amount)
            SELECT DISTINCT stat_date,'ks','one',0 FROM dws.dws_douyin_calendar''')
        self.cursor.execute('SELECT stat_date,amount FROM ads.ads_promotion_expense_company_shop_daily')
        self.assertEqual([(date(2026,10,2),0)],self.cursor.fetchall())

    def test_order_scope_does_not_match_merchant_order_no_as_order_no(self):
        with self.connection.raw_cursor() as cur:
            cur.execute('''CREATE TABLE dwd.dwd_pdd_settlement_test(
                    stat_date date,shop_code text,merchant_order_no text);
                CREATE TABLE dwd.dwd_pdd_order_test(stat_date date,shop_code text,order_no text);
                CREATE TABLE ods.ods_pdd_order_raw(batch_id bigint,"订单号" text);
                INSERT INTO dwd.dwd_pdd_order_test VALUES ('2026-09-30','one','changed');
                INSERT INTO ods.ods_pdd_order_raw VALUES (1,'changed')''')
            months = _previous_order_months(cur, {'platform_code':'pdd','shop_code':'one',
                'batch_id':1,'target_table':'ods_pdd_order_raw'})
        self.assertEqual({'2026-09-01'}, months)

    def test_promotion_counts_ignore_other_shops_months_and_newer_batches(self):
        from etl.promotion_expense.run_promotion_expense_etl import count_refresh_rows
        context = {**CONTEXT, 'months':{'douyin':['2026-10-01']}, 'shops':{'douyin':['one']}}
        conn = psycopg2.connect(**self.kwargs, connection_factory=connection_factory(context))
        try:
            with conn.raw_cursor() as cur:
                cur.execute('''CREATE TABLE ods.ods_douyin_qianchuan_finance_raw(
                        id bigint,batch_id bigint,"日期" text);
                    CREATE TABLE dwd.dwd_douyin_promotion_expense_detail(
                        source_record_id bigint,expense_date date,shop_code text);
                    UPDATE ods.ods_file_ingest_log SET platform_code='douyin',
                        target_table='ods_douyin_qianchuan_finance_raw';
                    UPDATE ods.ods_file_ingest_log SET shop_code='two' WHERE batch_id=1;
                    INSERT INTO ods.ods_douyin_qianchuan_finance_raw VALUES
                        (1,1,'2026-10-02'),(2,2,'2026-10-02'),(3,2,'2026-09-30'),(4,3,'2026-10-03');
                    INSERT INTO dwd.dwd_douyin_promotion_expense_detail VALUES
                        (2,'2026-10-02','one'),(1,'2026-10-02','two'),(3,'2026-09-30','one')''')
            with conn.cursor() as cur:
                self.assertEqual(1, count_refresh_rows(cur,'ods.ods_douyin_qianchuan_finance_raw','douyin'))
                self.assertEqual(1, count_refresh_rows(cur,'dwd.dwd_douyin_promotion_expense_detail','douyin'))
        finally:
            conn.rollback(); conn.close()

    def test_real_promotion_refresh_also_replaces_zero_platforms(self):
        context = {**CONTEXT, 'months':{'jd':['2026-10-01']}, 'shops':{'jd':['jd-shop']}}
        conn = psycopg2.connect(**self.kwargs, connection_factory=connection_factory(context))
        try:
            with conn.raw_cursor() as cur:
                cur.execute("""INSERT INTO ads.ads_promotion_expense_company_shop_daily VALUES
                    ('2026-09-01','ks','one',0),('2026-10-02','pdd','other',9)""")
            with conn.cursor() as cur:
                cur.execute('''TRUNCATE ads.ads_promotion_expense_company_shop_daily;
                    INSERT INTO ads.ads_promotion_expense_company_shop_daily(stat_date,platform_code,shop_code,amount)
                    SELECT DISTINCT d.stat_date,p.platform_code,'zero-shop',0
                    FROM dws.dws_douyin_calendar d CROSS JOIN (VALUES ('ks'),('wechat_channels'),('xhs')) p(platform_code)''')
                cur.execute('SELECT stat_date,platform_code,amount FROM ads.ads_promotion_expense_company_shop_daily ORDER BY 1,2')
                self.assertEqual([(date(2026,9,1),'ks',0),(date(2026,10,2),'ks',0),
                    (date(2026,10,2),'pdd',9),(date(2026,10,2),'wechat_channels',0),(date(2026,10,2),'xhs',0)], cur.fetchall())
        finally:
            conn.rollback(); conn.close()

    def test_pdd_undated_orders_survive_and_become_dated_without_duplicate_keys(self):
        context = {**CONTEXT, 'months':{'pdd':['2026-10-01']}, 'shops':{'pdd':['one']}}
        conn=psycopg2.connect(**self.kwargs,connection_factory=connection_factory(context))
        try:
            with conn.raw_cursor() as cur:
                cur.execute('''CREATE TABLE ods.ods_pdd_order_raw(
                        id bigint,batch_id bigint,"订单号" text,"订单成交时间" text);
                    CREATE VIEW common.v_current_pdd_order_raw AS SELECT * FROM ods.ods_pdd_order_raw;
                    CREATE TABLE dwd.dwd_pdd_gsv_order_detail(platform_code text,shop_code text,
                        order_no text,stat_date date,source_id bigint,PRIMARY KEY(platform_code,order_no));
                    UPDATE ods.ods_file_ingest_log SET platform_code='pdd',target_table='ods_pdd_order_raw';
                    INSERT INTO ods.ods_pdd_order_raw VALUES
                        (1,2,'261002-old','2026-10-02'),(2,2,'261003-unpaid','-'),(3,2,'260801-keep','-');
                    INSERT INTO dwd.dwd_pdd_gsv_order_detail VALUES
                        ('pdd','one','261002-old',NULL,99),('pdd','one','260801-keep',NULL,3)''')
            with conn.cursor() as cur:
                for _ in range(2):
                    cur.execute('''TRUNCATE dwd.dwd_pdd_gsv_order_detail;
                        INSERT INTO dwd.dwd_pdd_gsv_order_detail(platform_code,shop_code,order_no,stat_date,source_id)
                        SELECT 'pdd',c.shop_code,r."订单号",
                            NULLIF(NULLIF(r."订单成交时间",''),'-')::date,r.id
                        FROM common.v_current_pdd_order_raw r JOIN common.v_ingest_batch_shop_context c USING(batch_id)''')
                cur.execute('SELECT order_no,stat_date FROM dwd.dwd_pdd_gsv_order_detail ORDER BY 1')
                self.assertEqual([('260801-keep',None),('261002-old',date(2026,10,2)),('261003-unpaid',None)],cur.fetchall())
            conn.commit()
        finally:
            conn.rollback(); conn.close()
            with self.control.cursor() as cur:
                cur.execute('''DROP VIEW IF EXISTS common.v_current_pdd_order_raw;
                    DROP TABLE IF EXISTS ods.ods_pdd_order_raw;
                    DROP TABLE IF EXISTS dwd.dwd_pdd_gsv_order_detail;
                    UPDATE ods.ods_file_ingest_log SET platform_code='ks',target_table='ods_ks_fund_raw' ''')
            self.control.commit()

    def test_monthly_promotion_reads_zero_platforms_and_preserves_other_shops(self):
        context={**CONTEXT,'months':{'jd':['2026-10-01']},'shops':{'jd':['one']}}
        conn=psycopg2.connect(**self.kwargs,connection_factory=connection_factory(context))
        try:
            with conn.raw_cursor() as cur:
                cur.execute('''CREATE TABLE ads.ads_gsv_company_daily(
                        stat_date date,platform_code text,shop_code text,amount numeric);
                    CREATE TABLE ads.ads_gsv_promotion_expense_company_shop_monthly(
                        stat_month date,platform_code text,shop_code text,amount numeric);
                    INSERT INTO ads.ads_gsv_company_daily VALUES
                        ('2026-10-02','jd','one',8),('2026-10-02','ks','zero',7),('2026-10-02','pdd','other',9);
                    INSERT INTO ads.ads_gsv_promotion_expense_company_shop_monthly VALUES
                        ('2026-10-01','pdd','other',3),('2026-09-01','jd','one',4)''')
            with conn.cursor() as cur:
                cur.execute('''TRUNCATE ads.ads_gsv_promotion_expense_company_shop_monthly;
                    INSERT INTO ads.ads_gsv_promotion_expense_company_shop_monthly(stat_month,platform_code,shop_code,amount)
                    SELECT DATE_TRUNC('month',stat_date)::date,platform_code,shop_code,SUM(amount)
                    FROM ads.ads_gsv_company_daily GROUP BY 1,2,3''')
                cur.execute('SELECT stat_month,platform_code,amount FROM ads.ads_gsv_promotion_expense_company_shop_monthly ORDER BY 1,2')
                self.assertEqual([(date(2026,9,1),'jd',4),(date(2026,10,1),'jd',8),
                    (date(2026,10,1),'ks',7),(date(2026,10,1),'pdd',3)],cur.fetchall())
        finally:
            conn.rollback(); conn.close()

    def test_summary_zero_calendar_keeps_other_metrics_and_bank_rows(self):
        context={**CONTEXT,'months':{'jd':['2026-10-01']},'shops':{'jd':['one']}}
        conn=psycopg2.connect(**self.kwargs,connection_factory=connection_factory(context))
        try:
            with conn.raw_cursor() as cur:
                cur.execute('''CREATE TABLE ads.ads_other_finance(stat_date date,platform_code text,amount numeric);
                    CREATE TABLE ads.ads_platform_bank_total_revenue_company_daily_type(
                        stat_date date,platform_code text,metric text,amount numeric);
                    INSERT INTO ads.ads_promotion_expense_company_shop_daily VALUES
                        ('2026-10-02','jd','one',5),('2026-10-02','ks','zero',0);
                    INSERT INTO ads.ads_other_finance VALUES ('2026-10-02','ks',7),('2026-10-02','jd',10);
                    INSERT INTO ads.ads_platform_bank_total_revenue_company_daily_type VALUES
                        ('2026-10-02','bank','income',99),('2026-10-02','pdd','income',8),
                        ('2026-09-01','jd','income',1),('2026-10-02','ks','income',3)''')
            with conn.cursor() as cur:
                cur.execute('''TRUNCATE ads.ads_platform_bank_total_revenue_company_daily_type;
                    INSERT INTO ads.ads_platform_bank_total_revenue_company_daily_type(stat_date,platform_code,metric,amount)
                    SELECT stat_date,platform_code,'expense',SUM(amount)
                    FROM ads.ads_promotion_expense_company_shop_daily GROUP BY 1,2
                    UNION ALL SELECT stat_date,platform_code,'income',SUM(amount) FROM ads.ads_other_finance GROUP BY 1,2''')
                cur.execute('SELECT stat_date,platform_code,metric,amount FROM ads.ads_platform_bank_total_revenue_company_daily_type ORDER BY 1,2,3')
                self.assertEqual([(date(2026,9,1),'jd','income',1),(date(2026,10,2),'bank','income',99),
                    (date(2026,10,2),'jd','expense',5),(date(2026,10,2),'jd','income',10),
                    (date(2026,10,2),'ks','expense',0),(date(2026,10,2),'ks','income',7),
                    (date(2026,10,2),'pdd','income',8)],cur.fetchall())
        finally:
            conn.rollback(); conn.close()

    def test_schema_scripts_and_original_ods_writes_are_not_executed(self):
        self.cursor.execute('ALTER TABLE ods.ods_ks_fund_raw ADD COLUMN should_not_exist text')
        self.cursor.execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='ods' AND column_name='should_not_exist'")
        self.assertEqual(0,self.cursor.fetchone()[0])
        with self.assertRaisesRegex(ValueError, '禁止修改ODS'):
            self.cursor.execute('DELETE FROM ods.ods_ks_fund_raw')

    def test_schema_file_backfill_is_skipped_but_transaction_local_tables_work(self):
        self.cursor.execute('ALTER TABLE dwd.dwd_ks_test ADD COLUMN bad text; UPDATE dwd.dwd_ks_test SET amount=999')
        self.cursor.execute('SELECT MAX(amount) FROM dwd.dwd_ks_test')
        self.assertEqual(9,self.cursor.fetchone()[0])
        self.cursor.execute('CREATE TEMP TABLE _legacy_snapshot ON COMMIT DROP AS SELECT * FROM dwd.dwd_ks_test')
        self.cursor.execute('SELECT COUNT(*) FROM _legacy_snapshot')
        self.assertEqual(4,self.cursor.fetchone()[0])

    def test_updates_are_restricted_too(self):
        self.cursor.execute('UPDATE dwd.dwd_ks_test SET amount=amount+100')
        self.cursor.execute('SELECT amount FROM dwd.dwd_ks_test ORDER BY amount')
        self.assertEqual([4,7,9,101],[r[0] for r in self.cursor.fetchall()])

    def test_unknown_write_shapes_never_fall_back_to_unbounded_sql(self):
        for statement in ('TRUNCATE dwd.dwd_ks_test RESTART IDENTITY',
                          'INSERT INTO dwd.dwd_ks_test SELECT * FROM dwd.dwd_ks_test',
                          'DELETE FROM dwd.dwd_ks_test'):
            with self.assertRaisesRegex(ValueError, '禁止无范围刷新'):
                self.cursor.execute(statement)
        self.cursor.execute('SELECT COUNT(*) FROM dwd.dwd_ks_test')
        self.assertEqual(4, self.cursor.fetchone()[0])

    def test_rollback_restores_deleted_rows_when_calculation_fails(self):
        with self.assertRaises(psycopg2.Error):
            self.cursor.execute('''TRUNCATE dwd.dwd_ks_test;
                INSERT INTO dwd.dwd_ks_test(stat_date,platform_code,shop_code,amount,source_id)
                SELECT DATE '2026-10-02','ks','one',1/0,2''')
        self.connection.rollback()
        with self.control.cursor() as cur:
            cur.execute("SELECT amount FROM dwd.dwd_ks_test WHERE platform_code='ks' AND shop_code='one' AND stat_date='2026-10-02'")
            self.assertEqual(1,cur.fetchone()[0])


if __name__ == '__main__':
    unittest.main()
