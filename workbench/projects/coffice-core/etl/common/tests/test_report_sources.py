"""Version-selection regressions. Database tests require an isolated test database."""
from __future__ import annotations

import os
import tempfile
import unittest
import uuid
from pathlib import Path

import psycopg2
from psycopg2 import sql
from etl.common.report_sources import pdd_settlement_period, prepare_report_sources


class SettlementHeaderTests(unittest.TestCase):
    def parse(self, start, end):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'bill.csv'
            path.write_text(f'起始时间：{start} 终止时间：{end}\n',encoding='utf-8')
            return pdd_settlement_period(path,'utf-8')

    def test_whole_month_coverage(self):
        period = self.parse('2026-09-01 00:00:00','2026-09-30 23:59:59')
        self.assertEqual(tuple(map(str,period)),('2026-09-01','2026-09-30'))

    def test_partial_day_does_not_replace_whole_day(self):
        self.assertIsNone(self.parse('2026-09-01 01:00:00','2026-09-30 23:59:59'))

    def test_inverted_period_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'倒置'):
            self.parse('2026-09-30 00:00:00','2026-09-01 23:59:59')

    def test_excel_input_keeps_unknown_coverage_without_decoding_binary(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bill.xlsx'
            path.write_bytes(b'PK\x03\x04\xff')
            self.assertIsNone(pdd_settlement_period(path,None))


@unittest.skipUnless(os.getenv('REPORT_SOURCE_TEST_DB'),'requires isolated REPORT_SOURCE_TEST_DB')
class ReportSourceDatabaseTests(unittest.TestCase):
    platforms = ('douyin','tmall','jd','ks','pdd','xhs','wechat_channels')

    @classmethod
    def setUpClass(cls):
        dbname = os.environ['REPORT_SOURCE_TEST_DB']
        if dbname in {'mock_coffice','coffice'} or 'test' not in dbname.lower():
            raise RuntimeError('Report source tests must use an isolated test database')
        cls.connection = psycopg2.connect(host=os.environ['PGHOST'],port=os.getenv('PGPORT','5432'),
                                         dbname=dbname,user=os.environ['PGUSER'],password=os.environ['PGPASSWORD'])
        with cls.connection.cursor() as cur:
            cur.execute((Path(__file__).resolve().parents[3]/'sql/common/434_report_source_selection_postgres.sql').read_text(encoding='utf-8'))
        cls.connection.commit()

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def setUp(self):
        self.cursor = self.connection.cursor()
        self.token = 'TEST_'+uuid.uuid4().hex

    def tearDown(self):
        self.connection.rollback()
        self.cursor.close()

    def batch(self, platform, date, kind='order', run=None, shop=None, period=None):
        cur = self.cursor
        if run:
            cur.execute("""INSERT INTO ops.ingest_run(run_id,source,idempotency_key,expected_file_count,
                           auto_refresh,status,operator) VALUES(%s,'manual',%s,2,false,'draft','source_test')
                           ON CONFLICT(run_id) DO NOTHING""",(run,run))
        cur.execute("""SELECT shop_code,shop_name,shop_identity_key FROM dim.dim_platform_shop_company
                       WHERE platform_code=%s AND is_active AND valid_from<=CURRENT_DATE
                         AND (valid_to IS NULL OR valid_to>=CURRENT_DATE) ORDER BY shop_code""",(platform,))
        shops = cur.fetchall()
        selected = shops[shop or 0]
        filename = date+'_'+self.token+'_'+kind+'.csv'
        cur.execute("""INSERT INTO ods.ods_file_ingest_log(platform_code,shop_code,shop_name,shop_identity_key,
                       shop_mapping_status,shop_mapping_source,data_domain,source_file_path,source_file_name,
                       target_schema,target_table,ingest_status,ingest_run_id,report_period_start,report_period_end)
                       VALUES(%s,%s,%s,%s,'mapped','manual_selected',%s,'test-no-source-file',%s,'ods',%s,'success',%s,%s,%s)
                       RETURNING batch_id""",(platform,*selected,kind,filename,f'ods_{platform}_{kind}_raw',
                                              run,*(period or (None,None))))
        return cur.fetchone()[0]

    def raw(self, platform,batch,values,kind='order'):
        cols = ['batch_id','source_file_name','source_sheet_name','source_row_no','row_hash',*values]
        data = [batch,self.token+'.csv','CSV',1,uuid.uuid4().hex*2,*values.values()]
        self.cursor.execute(sql.SQL('INSERT INTO ods.{} ({}) VALUES ({}) RETURNING id').format(
            sql.Identifier(f'ods_{platform}_{kind}_raw'),sql.SQL(',').join(map(sql.Identifier,cols)),
            sql.SQL(',').join(sql.Placeholder() for _ in cols)),data)
        return self.cursor.fetchone()[0]

    def test_latest_whole_order_and_older_reimport_for_all_platforms(self):
        for platform in self.platforms:
            with self.subTest(platform=platform):
                main = '主订单编号' if platform in {'douyin','tmall'} else '订单号'
                values = {main:self.token+platform}
                if platform in {'douyin','tmall'}:
                    values['子订单编号']=self.token+'old'
                old = self.batch(platform,'202608')
                self.raw(platform,old,values)
                new = self.batch(platform,'202609')
                ids=[]
                for child in ('A','B'):
                    detail=dict(values)
                    if platform in {'douyin','tmall'}:
                        detail['子订单编号']=self.token+child
                    else:
                        product={'pdd':'商品id','wechat_channels':'商品编码(平台)'}.get(platform,'商品ID')
                        detail[product]=child
                    ids.append(self.raw(platform,new,detail))
                reimport = self.batch(platform,'202608')
                self.raw(platform,reimport,values)
                self.cursor.execute(sql.SQL('SELECT id,business_detail_key FROM common.{} WHERE {}=%s ORDER BY id').format(
                    sql.Identifier(f'v_current_{platform}_order_raw'),sql.Identifier(main)),(values[main],))
                rows=self.cursor.fetchall()
                self.assertEqual([r[0] for r in rows],ids)
                self.assertEqual(len({r[1] for r in rows}),2)

    def test_one_submission_keeps_order_fragments_across_files(self):
        run=str(uuid.uuid4())
        ids=[]
        for product in ('A','B'):
            batch=self.batch('jd','202609',run=run)
            ids.append(self.raw('jd',batch,{'订单号':self.token,'商品ID':product}))
        self.cursor.execute('SELECT id FROM common.v_current_jd_order_raw WHERE "订单号"=%s ORDER BY id',(self.token,))
        self.assertEqual([r[0] for r in self.cursor.fetchall()],ids)

    def test_invalid_kuaishou_account_identity_is_still_rejected(self):
        from etl.ks.run_ks_settlement_metrics_etl import validate_batch_shop_mapping
        batch=self.batch('ks','209912',kind='settlement')
        self.raw('ks',batch,{'商家ID':'invalid-test-account'},kind='settlement')
        with self.assertRaisesRegex(RuntimeError,'DIM平台账号ID冲突'):
            validate_batch_shop_mapping(self.cursor)

    def test_same_order_in_different_shops_is_independent(self):
        for shop in (0,1):
            batch=self.batch('pdd','202609',shop=shop)
            self.raw('pdd',batch,{'订单号':self.token,'商品id':'A'})
        self.cursor.execute('SELECT COUNT(*) FROM common.v_current_pdd_order_raw WHERE "订单号"=%s',(self.token,))
        self.assertEqual(self.cursor.fetchone()[0],2)

    def test_unmapped_historical_batch_cannot_be_hidden_by_new_version(self):
        batch=self.batch('pdd','202608')
        self.raw('pdd',batch,{'订单号':self.token})
        new=self.batch('pdd','202609')
        self.raw('pdd',new,{'订单号':self.token})
        self.cursor.execute("UPDATE ods.ods_file_ingest_log SET shop_mapping_status='unmapped' WHERE batch_id=%s",(batch,))
        with self.assertRaisesRegex(RuntimeError,'未成功、未映射或冲突批次'):
            prepare_report_sources(self.cursor,('pdd',))

    def test_settlement_replacement_preserves_legitimate_identical_flows(self):
        # Test shops get unique ranges far from production fixture dates.
        old=self.batch('pdd','20991227',kind='settlement',period=('2099-12-27','2099-12-27'))
        flow={'发生时间':'2099-12-27 17:58:20','收入金额（+元）':'0','支出金额（-元）':'-5',
              '账务类型':'扣款','业务描述':'0040006|售后费用-缺货'}
        self.raw('pdd',old,flow,kind='settlement')
        new=self.batch('pdd','209912',kind='settlement',period=('2099-12-01','2099-12-31'))
        ids=[self.raw('pdd',new,flow,kind='settlement') for _ in range(2)]
        self.cursor.execute('SELECT id FROM common.v_current_pdd_settlement_raw WHERE batch_id=ANY(%s) ORDER BY id',([old,new],))
        self.assertEqual([r[0] for r in self.cursor.fetchall()],ids)

    def test_settlement_fragments_in_one_submission_are_preserved(self):
        run=str(uuid.uuid4())
        batches=[]
        for _ in range(2):
            batch=self.batch('pdd','209912',kind='settlement',run=run,period=('2099-12-01','2099-12-31'))
            batches.append(batch)
            self.raw('pdd',batch,{'发生时间':'2099-12-27 10:00:00'},kind='settlement')
        self.cursor.execute('SELECT COUNT(*) FROM common.v_current_pdd_settlement_raw WHERE batch_id=ANY(%s)',(batches,))
        self.assertEqual(self.cursor.fetchone()[0],2)
