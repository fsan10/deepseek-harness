"""Execute native flow selection and rejection gates in a disposable database."""
import hashlib
import tempfile
import unittest
import uuid
from pathlib import Path

import psycopg2
from psycopg2 import sql

from etl.common.finance_sources import NATIVE_SOURCES, SOURCE_SQL, ROOT, validate_native_source, verify_fund_files
from etl.common.settlement_sources import load_pg_env


class FinanceSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_pg_env()
        cls.name = 'codex_finance_source_test_' + uuid.uuid4().hex[:12]
        cls.admin = psycopg2.connect()
        cls.admin.autocommit = True
        with cls.admin.cursor() as c:
            c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        try:
            cls.conn = psycopg2.connect(dbname=cls.name)
            cls.temp = tempfile.TemporaryDirectory()
            cls.path = Path(cls.temp.name) / 'fixture.csv'
            cls.path.write_text('native flow fixture', encoding='utf-8')
            cls.digest = hashlib.sha256(cls.path.read_bytes()).hexdigest()
            with cls.conn.cursor() as c:
                c.execute('''CREATE SCHEMA ods; CREATE SCHEMA common;
                    CREATE TABLE ods.ods_file_ingest_log (
                        batch_id BIGINT PRIMARY KEY,platform_code TEXT,target_table TEXT,
                        shop_identity_key TEXT,shop_code TEXT,company_code TEXT,
                        source_file_path TEXT,file_hash TEXT,parsed_rows BIGINT,failed_rows BIGINT,
                        ingest_status TEXT,shop_mapping_status TEXT);
                    CREATE VIEW common.v_ingest_batch_shop_context AS SELECT * FROM ods.ods_file_ingest_log;''')
                for table, key, account in NATIVE_SOURCES.values():
                    extra = sql.SQL(', {} TEXT').format(sql.Identifier(account)) if account else sql.SQL('')
                    c.execute(sql.SQL('''CREATE TABLE ods.{} (
                        id BIGINT PRIMARY KEY,batch_id BIGINT,source_file_name TEXT,
                        source_sheet_name TEXT,source_row_no INT,row_hash TEXT,ingest_time TIMESTAMPTZ,
                        {} TEXT,amount NUMERIC,order_no TEXT,event_type TEXT {})''').format(
                        sql.Identifier(table), sql.Identifier(key), extra))
                c.execute('ALTER TABLE ods.ods_douyin_fund_raw ADD COLUMN "动账时间" TEXT DEFAULT \'2026-10-01\'')
                c.execute((ROOT / 'sql/common/468_ingest_source_day_selection_postgres.sql').read_text(encoding='utf-8'))
                c.execute((ROOT / 'sql' / SOURCE_SQL).read_text(encoding='utf-8'))
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

    def batch(self, ident, flows=('flow',), *, platform='ks', shop='one', account='wallet', amount=10):
        table, key, account_column = NATIVE_SOURCES[platform]
        self.cur.execute('''INSERT INTO ods.ods_file_ingest_log VALUES
            (%s,%s,%s,%s,%s,'company',%s,%s,%s,0,'success','mapped')''',
            (ident,platform,table,platform+'|'+shop,shop,str(self.path),self.digest,len(flows)))
        for n, flow in enumerate(flows):
            columns = ['id','batch_id','source_file_name','source_sheet_name','source_row_no',
                       'row_hash','ingest_time',key,'amount','order_no','event_type']
            values = [ident*100+n,ident,str(ident)+'.csv','CSV',n+2,str(ident*100+n),
                      f'2026-10-{ident:02d}T00:00:00Z',flow,amount,'same-order','event']
            if account_column:
                columns.append(account_column)
                values.append(account)
            self.cur.execute(sql.SQL('INSERT INTO ods.{} ({}) VALUES ({})').format(
                sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,columns)),
                sql.SQL(',').join(sql.Placeholder() for _ in values)),values)

    def count(self, platform):
        validate_native_source(self.cur,platform)
        table = NATIVE_SOURCES[platform][0]
        self.cur.execute(sql.SQL('SELECT COUNT(*) FROM common.{}').format(
            sql.Identifier('v_current_'+table.removeprefix('ods_'))))
        return self.cur.fetchone()[0]

    def test_identical_flow_across_exports_selected_once_for_each_platform(self):
        for platform in NATIVE_SOURCES:
            self.batch(1,platform=platform)
            self.batch(2,platform=platform)
            self.assertEqual(self.count(platform),1)
            table=NATIVE_SOURCES[platform][0]
            self.cur.execute(sql.SQL('DELETE FROM ods.{}').format(sql.Identifier(table)))
            self.cur.execute('DELETE FROM ods.ods_file_ingest_log')

    def test_same_flow_in_different_shops_is_not_combined(self):
        self.batch(1,shop='one'); self.batch(2,shop='two')
        self.assertEqual(self.count('ks'),2)

    def test_douyin_accounts_are_independent(self):
        self.batch(1,platform='douyin',account='one')
        self.batch(2,platform='douyin',account='two')
        self.assertEqual(self.count('douyin'),2)

    def test_same_order_and_amount_with_distinct_flows_all_remain(self):
        self.batch(1,flows=('freeze','unfreeze','deduct'))
        self.assertEqual(self.count('ks'),3)

    def test_conflicting_flow_versions_stop(self):
        self.batch(1); self.batch(2,amount=11)
        with self.assertRaisesRegex(RuntimeError,'业务字段冲突'):
            self.count('ks')

    def test_duplicate_identity_inside_file_stops_without_deleting_rows(self):
        self.batch(1,flows=('flow','flow'))
        with self.assertRaisesRegex(RuntimeError,'同一批次'):
            self.count('ks')

    def test_missing_identity_stops(self):
        self.batch(1,flows=('',))
        with self.assertRaisesRegex(RuntimeError,'身份缺失'):
            self.count('ks')

    def test_incomplete_import_stops(self):
        self.batch(1)
        self.cur.execute('UPDATE ods.ods_file_ingest_log SET parsed_rows=2')
        with self.assertRaisesRegex(RuntimeError,'不完整'):
            self.count('ks')

    def test_unmapped_historical_batch_cannot_be_hidden(self):
        self.batch(1); self.batch(2)
        self.cur.execute("UPDATE ods.ods_file_ingest_log SET shop_mapping_status='unmapped' WHERE batch_id=1")
        with self.assertRaisesRegex(RuntimeError,'未映射'):
            self.count('ks')

    def test_overlapping_export_hash_must_match(self):
        self.batch(1); self.batch(2)
        self.cur.execute("UPDATE ods.ods_file_ingest_log SET file_hash='wrong' WHERE batch_id=1")
        with self.assertRaisesRegex(RuntimeError,'SHA256'):
            self.count('ks')

    def test_existing_jd_and_tmall_keys_migrate_without_losing_other_shop(self):
        self.cur.execute('CREATE SCHEMA dwd')
        for platform,document in (('jd','source_document_type'),('tmall','source_account_type')):
            for metric in ('main_business_income','platform_expense'):
                table=f'dwd_{platform}_{metric}_source_detail'
                self.cur.execute(sql.SQL('''CREATE TABLE dwd.{} (
                    shop_identity_key TEXT,{} TEXT,source_event_key TEXT,amount NUMERIC,
                    PRIMARY KEY ({},source_event_key))''').format(
                        sql.Identifier(table),sql.Identifier(document),sql.Identifier(document)))
                self.cur.execute(sql.SQL("INSERT INTO dwd.{} VALUES ('one','source','same-flow',10)").format(sql.Identifier(table)))
        migration=(ROOT/'sql/common/461_finance_source_shop_identity_postgres.sql').read_text(encoding='utf-8')
        self.cur.execute(migration)
        self.cur.execute(migration)
        for platform in ('jd','tmall'):
            for metric in ('main_business_income','platform_expense'):
                table=f'dwd_{platform}_{metric}_source_detail'
                self.cur.execute(sql.SQL("INSERT INTO dwd.{} VALUES ('two','source','same-flow',20)").format(sql.Identifier(table)))
                self.cur.execute(sql.SQL('SELECT COUNT(*),SUM(amount) FROM dwd.{}').format(sql.Identifier(table)))
                self.assertEqual(self.cur.fetchone(),(2,30))

    def test_missing_local_fund_import_is_not_accepted_as_zero(self):
        with self.assertRaisesRegex(RuntimeError,'缺少唯一完整资金导入批次'):
            verify_fund_files(self.cur,[{'platform_code':'ks','shop_code':'one','path':str(self.path)}])

    def test_fund_reference_checks_all_business_fields_and_rows(self):
        import csv
        from etl.ks.load_ks_fund_ods import CONFIG
        path=Path(self.temp.name)/'fund-reference.csv'
        values=['flow','order','2026-09-01 00:00:00','支','10','20','资金扣减','快手小店退款','remark']
        with path.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream); writer.writerow(CONFIG.expected_columns); writer.writerow(values)
        self.batch(1)
        for column in CONFIG.expected_columns[1:]:
            self.cur.execute(sql.SQL('ALTER TABLE ods.ods_ks_fund_raw ADD COLUMN {} TEXT').format(sql.Identifier(column)))
        self.cur.execute('UPDATE ods.ods_file_ingest_log SET file_hash=%s',
                         (hashlib.sha256(path.read_bytes()).hexdigest(),))
        assignments=sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(k)) for k in CONFIG.expected_columns)
        self.cur.execute(sql.SQL('UPDATE ods.ods_ks_fund_raw SET {}').format(assignments),values)
        entry={'platform_code':'ks','shop_code':'one','path':str(path)}
        self.assertTrue(verify_fund_files(self.cur,[entry])[0]['all_raw_fields_equal'])
        self.cur.execute('UPDATE ods.ods_ks_fund_raw SET "发生额（元）"=\'11\'')
        with self.assertRaisesRegex(RuntimeError,'原始字段与ODS不一致'):
            verify_fund_files(self.cur,[entry])


if __name__ == '__main__':
    unittest.main()
