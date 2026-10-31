"""Real SQL coverage tests in a disposable database; no production fixtures."""
import hashlib
import os
import tempfile
import unittest
import uuid
from pathlib import Path

import psycopg2
from psycopg2 import sql

from etl.common.settlement_sources import (
    TABLES, backfill_receipts, ensure_schema, load_pg_env, prepare_settlement_sources, register_source,
)


class SettlementCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_pg_env()
        cls.name = 'codex_settlement_test_' + uuid.uuid4().hex[:12]
        cls.admin = psycopg2.connect()
        cls.admin.autocommit = True
        with cls.admin.cursor() as c:
            c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        try:
            cls.conn = psycopg2.connect(dbname=cls.name)
            cls.temp = tempfile.TemporaryDirectory()
            cls.path = Path(cls.temp.name) / 'fixture.csv'
            cls.path.write_text('test fixture', encoding='utf-8')
            cls.file_hash = hashlib.sha256(cls.path.read_bytes()).hexdigest()
            with cls.conn.cursor() as c:
                c.execute('''CREATE SCHEMA ods; CREATE SCHEMA common;
                    CREATE TABLE ods.ods_file_ingest_log (
                        batch_id BIGINT PRIMARY KEY,platform_code TEXT,target_table TEXT,
                        shop_identity_key TEXT,shop_code TEXT,source_file_name TEXT,source_sheet_name TEXT,
                        source_file_path TEXT,file_hash TEXT,started_at TIMESTAMPTZ,
                        ingest_status TEXT,shop_mapping_status TEXT,company_code TEXT,
                        parsed_rows BIGINT,failed_rows BIGINT);
                    CREATE VIEW common.v_ingest_batch_shop_context AS SELECT * FROM ods.ods_file_ingest_log;''')
                dates = ['结算时间','实际结算时间','结算时间','结算时间','入帐日期','发生时间']
                for table, col in zip([t for ts in TABLES.values() for t in ts],dates):
                    c.execute(sql.SQL('CREATE TABLE ods.{} (id BIGINT,batch_id BIGINT,{} TEXT,amount NUMERIC)').format(sql.Identifier(table),sql.Identifier(col)))
                ensure_schema(c)
            cls.conn.commit()
        except Exception:
            cls._cleanup()
            raise

    @classmethod
    def _cleanup(cls):
        if hasattr(cls, 'conn'):
            cls.conn.close()
        if hasattr(cls, 'temp'):
            cls.temp.cleanup()
        with cls.admin.cursor() as c:
            c.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))
        cls.admin.close()

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    def setUp(self):
        self.cur = self.conn.cursor()

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()

    def batch(self, ident, days=('2026-09-27',), *, table='ods_douyin_settlement_raw', shop='douyin|one', file_path=None):
        platform = next(p for p, ts in TABLES.items() if table in ts)
        path = file_path or self.path
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.cur.execute('''INSERT INTO ods.ods_file_ingest_log (
            batch_id,platform_code,target_table,shop_identity_key,source_file_name,
            source_sheet_name,source_file_path,file_hash,started_at,ingest_status,
            shop_mapping_status,company_code,parsed_rows,failed_rows) VALUES
            (%s,%s,%s,%s,'fixture.csv','sheet',%s,%s,'2026-10-01'::timestamp+(%s*INTERVAL '1 minute'),
                'success','mapped','company',%s,0)''',(ident,platform,table,shop,str(path),digest,ident,len(days)))
        col={'ks':'实际结算时间','tmall':'入帐日期' if 'aggregate' in table else '发生时间'}.get(platform,'结算时间')
        for n, day in enumerate(days):
            day = day.replace('-','') if col=='入帐日期' else day+' 12:00:00'
            self.cur.execute(sql.SQL('INSERT INTO ods.{} VALUES (%s,%s,%s,1)').format(sql.Identifier(table)),(ident*100+n,ident,day))

    def register(self, ident, start='2026-09-01', end='2026-09-30', group=None):
        # Seed pre-workflow historical approvals explicitly in this disposable
        # database. Production register_source cannot create these anymore.
        self.cur.execute('''INSERT INTO common.settlement_source_registry
            (batch_id,source_group_key,period_start,period_end,file_hash,evidence_type,evidence)
            SELECT batch_id,%s,%s,%s,file_hash,'user_confirmed','{"confirmation":"legacy fixture"}'::jsonb
            FROM ods.ods_file_ingest_log WHERE batch_id=%s ON CONFLICT DO NOTHING''',
            (group or f'batch:{ident}',start,end,ident))
        register_source(self.cur,ident,start,end,'user_confirmed',{'confirmation':'unit fixture'},group_key=group)

    def receipt(self, batch_id, *, platform='xhs', shop='one', file_hash=None):
        self.cur.execute('''CREATE SCHEMA ops;
            CREATE TABLE ops.automation_step_run (step_run_id INT,platform_code TEXT,shop_code TEXT,
                business_date_start DATE,business_date_end DATE);
            CREATE TABLE ops.automation_artifact (artifact_id INT,batch_id BIGINT,file_hash TEXT,
                step_run_id INT,coverage_verified BOOLEAN,business_date_start DATE,business_date_end DATE);
            UPDATE ods.ods_file_ingest_log SET shop_code=split_part(shop_identity_key,'|',2);''')
        self.cur.execute('''INSERT INTO ops.automation_step_run VALUES
            (1,%s,%s,'2026-09-01','2026-09-30')''',(platform,shop))
        self.cur.execute('''INSERT INTO ops.automation_artifact VALUES
            (1,%s,%s,1,TRUE,'2026-09-01','2026-09-30')''',(batch_id,file_hash or self.file_hash))

    def selected(self):
        self.cur.execute('SELECT batch_id,id FROM common.v_current_douyin_settlement_raw ORDER BY 1,2')
        return self.cur.fetchall()

    def test_complete_month_covers_old_day_preserves_identical_flows(self):
        self.batch(1); self.batch(2,('2026-09-27','2026-09-27'))
        self.register(2); prepare_settlement_sources(self.cur,'douyin')
        self.assertEqual(self.selected(),[(2,200),(2,201)])

    def test_new_manual_registration_is_rejected_without_changing_registry(self):
        self.batch(1)
        with self.assertRaisesRegex(ValueError,'禁止新增人工范围登记旁路'):
            register_source(self.cur,1,'2026-09-01','2026-09-30','user_confirmed',{'complete_export':True})
        self.cur.execute('SELECT count(*) FROM common.settlement_source_registry')
        self.assertEqual(self.cur.fetchone()[0],0)

    def test_automation_label_alone_cannot_authorize_registration(self):
        self.batch(1)
        with self.assertRaisesRegex(ValueError,'真实、已验证'):
            register_source(self.cur,1,'2026-09-01','2026-09-30','automation_receipt',{'artifact_id':1})

    def test_direct_receipt_registration_revalidates_request_range_and_hash(self):
        self.batch(1);self.receipt(1,platform='douyin')
        self.cur.execute("UPDATE ops.automation_step_run SET business_date_start='2026-09-02'")
        with self.assertRaisesRegex(ValueError,'不一致'):
            register_source(self.cur,1,'2026-09-01','2026-09-30','automation_receipt',{'artifact_id':1})
        self.cur.execute("UPDATE ops.automation_step_run SET business_date_start='2026-09-01'")
        self.cur.execute("UPDATE ops.automation_artifact SET file_hash='incorrect'")
        with self.assertRaisesRegex(ValueError,'不一致'):
            register_source(self.cur,1,'2026-09-01','2026-09-30','automation_receipt',{'artifact_id':1})

    def test_newest_same_range(self):
        self.batch(1); self.batch(2); self.register(1); self.register(2)
        prepare_settlement_sources(self.cur,'douyin')
        self.assertEqual(self.selected(),[(2,200)])

    def test_range_outside_month_survives(self):
        self.batch(1,('2026-08-31','2026-09-27')); self.batch(2); self.register(2)
        prepare_settlement_sources(self.cur,'douyin')
        self.assertEqual(self.selected(),[(1,100),(2,200)])

    def test_unknown_overlap_stops(self):
        self.batch(1); self.batch(2)
        with self.assertRaisesRegex(RuntimeError,'覆盖不明'):
            prepare_settlement_sources(self.cur,'douyin')

    def test_partial_overlap_stops(self):
        self.batch(1,('2026-09-15',)); self.batch(2,('2026-09-15',))
        self.register(1,'2026-09-01','2026-09-20'); self.register(2,'2026-09-10','2026-09-30')
        with self.assertRaisesRegex(RuntimeError,'范围交叉'):
            prepare_settlement_sources(self.cur,'douyin')

    def test_explicit_shards_preserved(self):
        self.batch(1); self.batch(2); self.register(1,group='export-one'); self.register(2,group='export-one')
        prepare_settlement_sources(self.cur,'douyin')
        self.assertEqual(len(self.selected()),2)

    def test_two_shops_independent(self):
        self.batch(1,shop='douyin|one'); self.batch(2,shop='douyin|two'); self.register(2)
        prepare_settlement_sources(self.cur,'douyin')
        self.assertEqual(len(self.selected()),2)

    def test_interleaved_shards_choose_whole_group(self):
        for ident in (1,2,3,4): self.batch(ident)
        self.register(1,group='group-a'); self.register(4,group='group-a')
        self.register(2,group='group-b'); self.register(3,group='group-b')
        prepare_settlement_sources(self.cur,'douyin')
        self.assertEqual(self.selected(),[(1,100),(4,400)])

    def test_registration_idempotence_and_reject_different_range(self):
        self.batch(1); self.register(1); self.register(1)
        with self.assertRaisesRegex(ValueError,'禁止静默覆盖'):
            self.register(1,'2026-09-02','2026-09-30')

    def test_reject_rows_outside_declared_period(self):
        self.batch(1,('2026-08-31',))
        with self.assertRaisesRegex(ValueError,'超出声明'):
            self.register(1)

    def test_incomplete_import_cannot_cover_old_source(self):
        self.batch(1)
        self.cur.execute('UPDATE ods.ods_file_ingest_log SET parsed_rows=2 WHERE batch_id=1')
        with self.assertRaisesRegex(ValueError,'导入行数不完整'):
            self.register(1)

    def test_unmapped_history_cannot_be_hidden(self):
        self.batch(1); self.batch(2); self.register(2)
        self.cur.execute("UPDATE ods.ods_file_ingest_log SET shop_mapping_status='unmapped' WHERE batch_id=1")
        with self.assertRaisesRegex(RuntimeError,'未映射'):
            prepare_settlement_sources(self.cur,'douyin')

    def test_unbound_verified_automation_receipt_uses_hash_and_shop(self):
        self.batch(1)
        self.receipt(None,platform='douyin')
        prepare_settlement_sources(self.cur,'douyin')
        self.cur.execute('SELECT evidence_type FROM common.settlement_source_registry WHERE batch_id=1')
        self.assertEqual(self.cur.fetchone(),('automation_receipt',))

    def test_new_unknown_version_requires_confirmation(self):
        self.batch(1); self.register(1); self.batch(2)
        with self.assertRaisesRegex(RuntimeError,'覆盖不明'):
            prepare_settlement_sources(self.cur,'douyin')

    def test_tmall_accounts_do_not_cover_each_other(self):
        self.batch(1,table='ods_tmall_aggregate_fund_raw',shop='tmall|one')
        self.batch(2,table='ods_tmall_alipay_fund_raw',shop='tmall|one'); self.register(2)
        prepare_settlement_sources(self.cur,'tmall')
        self.cur.execute("SELECT COUNT(*) FROM common.v_effective_settlement_source WHERE platform_code='tmall'")
        self.assertEqual(self.cur.fetchone(),(2,))

    def test_xhs_requires_both_sheets_including_empty_sheet(self):
        self.batch(1,table='ods_xhs_settlement_income_raw',shop='xhs|one')
        with self.assertRaisesRegex(RuntimeError,'配套表缺失'):
            prepare_settlement_sources(self.cur,'xhs')
        self.batch(2,days=(),table='ods_xhs_settlement_expense_raw',shop='xhs|one')
        self.register(1,group='workbook'); self.register(2,group='workbook')
        prepare_settlement_sources(self.cur,'xhs')

    def test_xhs_bound_receipt_registers_empty_companion_idempotently(self):
        self.batch(1,table=TABLES['xhs'][0],shop='xhs|one')
        self.batch(2,days=(),table=TABLES['xhs'][1],shop='xhs|one')
        self.receipt(1)
        prepare_settlement_sources(self.cur,'xhs')
        prepare_settlement_sources(self.cur,'xhs')
        self.cur.execute('''SELECT batch_id,period_start::text,period_end::text,evidence_type
            FROM common.settlement_source_registry ORDER BY batch_id''')
        self.assertEqual(self.cur.fetchall(),[
            (1,'2026-09-01','2026-09-30','automation_receipt'),
            (2,'2026-09-01','2026-09-30','automation_receipt'),
        ])
        self.cur.execute('SELECT COUNT(*) FROM ods.ods_xhs_settlement_expense_raw')
        self.assertEqual(self.cur.fetchone(),(0,))

    def test_xhs_bound_receipt_registers_both_nonempty_sheets(self):
        for ident,table in enumerate(TABLES['xhs'],1):
            self.batch(ident,table=table,shop='xhs|one')
        self.receipt(1)
        prepare_settlement_sources(self.cur,'xhs')
        self.cur.execute('SELECT COUNT(*) FROM common.settlement_source_registry')
        self.assertEqual(self.cur.fetchone(),(2,))

    def test_xhs_expense_bound_receipt_also_registers_empty_income(self):
        self.batch(1,days=(),table=TABLES['xhs'][0],shop='xhs|one')
        self.batch(2,table=TABLES['xhs'][1],shop='xhs|one')
        self.receipt(2)
        prepare_settlement_sources(self.cur,'xhs')
        self.cur.execute('SELECT COUNT(*) FROM common.settlement_source_registry')
        self.assertEqual(self.cur.fetchone(),(2,))

    def test_xhs_both_empty_sheets_retain_workbook_range(self):
        for ident,table in enumerate(TABLES['xhs'],1):
            self.batch(ident,days=(),table=table,shop='xhs|one')
        self.receipt(1)
        prepare_settlement_sources(self.cur,'xhs')
        self.cur.execute('SELECT COUNT(*) FROM common.settlement_source_registry')
        self.assertEqual(self.cur.fetchone(),(2,))

    def test_xhs_unbound_receipt_also_registers_both_sheets(self):
        for ident,table in enumerate(TABLES['xhs'],1):
            self.batch(ident,table=table,shop='xhs|one')
        self.receipt(None)
        prepare_settlement_sources(self.cur,'xhs')
        self.cur.execute('SELECT COUNT(*) FROM common.settlement_source_registry')
        self.assertEqual(self.cur.fetchone(),(2,))

    def test_xhs_conflicting_companion_range_still_stops(self):
        for ident,table in enumerate(TABLES['xhs'],1):
            self.batch(ident,table=table,shop='xhs|one')
        self.register(2,'2026-09-27','2026-09-27')
        self.receipt(1)
        with self.assertRaisesRegex(RuntimeError,'配套表缺失或覆盖范围不一致'):
            prepare_settlement_sources(self.cur,'xhs')

    def test_xhs_bound_receipt_cannot_conceal_missing_sheet(self):
        self.batch(1,table=TABLES['xhs'][0],shop='xhs|one')
        self.receipt(1)
        with self.assertRaisesRegex(RuntimeError,'配套表缺失'):
            prepare_settlement_sources(self.cur,'xhs')

    def test_xhs_incomplete_empty_companion_still_stops(self):
        self.batch(1,table=TABLES['xhs'][0],shop='xhs|one')
        self.batch(2,days=(),table=TABLES['xhs'][1],shop='xhs|one')
        self.cur.execute('UPDATE ods.ods_file_ingest_log SET parsed_rows=1 WHERE batch_id=2')
        self.receipt(1)
        with self.assertRaisesRegex(ValueError,'导入行数不完整'):
            prepare_settlement_sources(self.cur,'xhs')

    def test_xhs_bound_receipt_does_not_cross_shops(self):
        self.batch(1,table=TABLES['xhs'][0],shop='xhs|other')
        for ident,table in enumerate(TABLES['xhs'],2):
            self.batch(ident,table=table,shop='xhs|one')
        self.receipt(1)
        backfill_receipts(self.cur,'xhs')
        self.cur.execute('SELECT COUNT(*) FROM common.settlement_source_registry')
        self.assertEqual(self.cur.fetchone(),(0,))

    def test_xhs_bound_receipt_does_not_cross_file_versions(self):
        self.batch(1,table=TABLES['xhs'][0],shop='xhs|one')
        changed = Path(self.temp.name) / 'different-workbook.csv'
        changed.write_text('different workbook',encoding='utf-8')
        for ident,table in enumerate(TABLES['xhs'],2):
            self.batch(ident,table=table,shop='xhs|one',file_path=changed)
        self.receipt(1,file_hash=hashlib.sha256(changed.read_bytes()).hexdigest())
        backfill_receipts(self.cur,'xhs')
        self.cur.execute('SELECT COUNT(*) FROM common.settlement_source_registry')
        self.assertEqual(self.cur.fetchone(),(0,))

    def test_bound_receipts_do_not_expand_other_platform_batches(self):
        for platform in ('douyin','ks','tmall'):
            with self.subTest(platform=platform):
                self.cur.execute('SAVEPOINT platform_receipt')
                tables = TABLES[platform]
                for ident in (1,2):
                    self.batch(ident,table=tables[min(ident-1,len(tables)-1)],shop=platform+'|one')
                self.receipt(1,platform=platform)
                backfill_receipts(self.cur,platform)
                self.cur.execute('SELECT batch_id FROM common.settlement_source_registry ORDER BY batch_id')
                self.assertEqual(self.cur.fetchall(),[(1,)])
                self.cur.execute('ROLLBACK TO SAVEPOINT platform_receipt')

    def test_xhs_new_empty_expense_covers_old_nonempty_version(self):
        for ident,table in enumerate(TABLES['xhs'],1):
            self.batch(ident,table=table,shop='xhs|one')
            self.register(ident,group='old-workbook')
        changed = Path(self.temp.name) / 'new-workbook.csv'
        changed.write_text('new empty expense workbook',encoding='utf-8')
        self.batch(3,table=TABLES['xhs'][0],shop='xhs|one',file_path=changed)
        self.batch(4,days=(),table=TABLES['xhs'][1],shop='xhs|one',file_path=changed)
        self.receipt(3,file_hash=hashlib.sha256(changed.read_bytes()).hexdigest())
        prepare_settlement_sources(self.cur,'xhs')
        self.cur.execute('SELECT batch_id FROM common.v_current_xhs_settlement_income_raw')
        self.assertEqual(self.cur.fetchall(),[(3,)])
        self.cur.execute('SELECT COUNT(*) FROM common.v_current_xhs_settlement_expense_raw')
        self.assertEqual(self.cur.fetchone(),(0,))


if __name__ == '__main__':
    unittest.main()
