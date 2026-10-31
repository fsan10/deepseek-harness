"""Real PostgreSQL regex/finance checks, all configuration and jobs rolled back."""
import os
import unittest
from contextlib import contextmanager
from decimal import Decimal
import psycopg2
from psycopg2.extras import RealDictCursor
from apps.file_ingest.service import FileIngestService
from etl.common.settlement_sources import load_pg_env
from etl.platform_finance.operating_treatment import prepare_schema
from etl.platform_finance.scene_normalization import normalize_dwd,mapping_group
from etl.platform_finance.operating_treatment import ROOT,refresh_projection

@unittest.skipUnless(os.getenv('RUN_OPERATING_DB_TESTS')=='1','explicit transaction-only database checks')
class SceneRulesIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_pg_env()
        cls.conn=psycopg2.connect(application_name='scene_rules_rollback_test',options='-c lock_timeout=60000 -c statement_timeout=120000')
        try:
            with cls.conn.cursor() as c:
                c.execute("SET LOCAL lock_timeout='0'")
                c.execute("SET LOCAL statement_timeout='0'")
                c.execute("SELECT pg_advisory_xact_lock(hashtext('mock_coffice_global_etl'))")
                c.execute("SET LOCAL lock_timeout='10000'")
                c.execute("SET LOCAL statement_timeout='60000'")
                prepare_schema(c)
            cls.service=object.__new__(FileIngestService)
            @contextmanager
            def transaction():
                with cls.conn.cursor(cursor_factory=RealDictCursor) as c:yield c
            cls.service.transaction=transaction
        except Exception:cls.conn.rollback();cls.conn.close();raise

    @classmethod
    def tearDownClass(cls):cls.conn.rollback();cls.conn.close()
    def setUp(self):
        with self.conn.cursor() as c:c.execute('SAVEPOINT scene_test')
    def tearDown(self):
        with self.conn.cursor() as c:c.execute('ROLLBACK TO SAVEPOINT scene_test')

    def payload(self,**kwargs):
        return {'rule_name':'测试新增流水后缀','platform_code':'ks','source_document_type':'fund',
            'source_business_type':'测试业务','pattern':r'-测试流水：[0-9]+$','replacement':'','priority':100,
            'is_active':True,'note':'仅在回滚事务内验证','sample_text':'测试业务 + 测试费用-测试流水：123456',**kwargs}

    def test_seed_rules_clean_five_examples_and_preserve_business_distinctions(self):
        pairs=(
            ('货款结算 + 快手小店交易结算-订单号：2627101600173970','货款结算 + 快手小店交易结算'),
            ('货款结算 + 快手小店交易结算-订单号：','货款结算 + 快手小店交易结算'),
            ('资金冻结 + 退款-快手电商-订单编号2627101600173970','资金冻结 + 退款'),
            ('佣金/技术服务费返还 + 分账追回-超售后期-cps团长三方分佣户-退款单号：123456','佣金/技术服务费返还 + 分账追回-超售后期'),
            ('佣金/技术服务费返还 + 分账追回-超售后期-平台服务费-退款单号：123456','佣金/技术服务费返还 + 分账追回-超售后期-平台服务费'))
        with self.conn.cursor() as c:
            for before,after in pairs:
                c.execute("SELECT dim.normalize_platform_scene('ks','fund',%s)",(before,))
                self.assertEqual(after,c.fetchone()[0])
                c.execute("SELECT dim.normalize_platform_scene('jd','fund',%s)",(before,))
                self.assertEqual(before,c.fetchone()[0])

    def test_preview_has_no_configuration_or_job_writes(self):
        with self.conn.cursor() as c:
            c.execute('SELECT (SELECT count(*) FROM dim.dim_platform_scene_normalization_rule),(SELECT count(*) FROM ops.etl_run),(SELECT count(*) FROM ops.operation_log)')
            before=c.fetchone()
        proof=self.service.preview_scene_rule(self.payload())
        self.assertTrue(proof['can_save'])
        self.assertIn('测试业务 + 测试费用',[x['after'] for x in proof['examples']])
        with self.conn.cursor() as c:
            c.execute('SELECT (SELECT count(*) FROM dim.dim_platform_scene_normalization_rule),(SELECT count(*) FROM ops.etl_run),(SELECT count(*) FROM ops.operation_log)')
            self.assertEqual(before,c.fetchone())

    def test_save_requires_exact_preview_and_queues_refresh(self):
        payload=self.payload()
        with self.assertRaisesRegex(ValueError,'重新预览'):self.service.save_scene_rule(payload,'scene_transaction_test',None)
        proof=self.service.preview_scene_rule(payload)
        result=self.service.save_scene_rule({**payload,'preview_token':proof['preview_token']},'scene_transaction_test',None)
        self.assertEqual('queued',result['etl_run']['status'])
        with self.conn.cursor() as c:
            c.execute("SELECT dim.normalize_platform_scene('ks','fund','测试业务 + 测试费用-测试流水：123456','测试业务')")
            self.assertEqual('测试业务 + 测试费用',c.fetchone()[0])
        old=result['rule']
        disabled={**old,'is_active':False,'sample_text':payload['sample_text']}
        proof=self.service.preview_scene_rule(disabled)
        self.service.save_scene_rule({**disabled,'preview_token':proof['preview_token']},'scene_transaction_test',None)
        with self.conn.cursor() as c:
            c.execute("SELECT dim.normalize_platform_scene('ks','fund','测试业务 + 测试费用-测试流水：123456','测试业务')")
            self.assertEqual('测试业务 + 测试费用-测试流水：123456',c.fetchone()[0])

    def test_overbroad_rule_is_blocked_when_financial_policies_differ(self):
        payload=self.payload(pattern='^.*$',replacement='合并后的场景',source_business_type=None)
        proof=self.service.preview_scene_rule(payload)
        self.assertTrue(proof['conflicts'])
        with self.assertRaisesRegex(ValueError,'不同的场景'):
            self.service.save_scene_rule({**payload,'preview_token':proof['preview_token']},'scene_transaction_test',None)

    def test_invalid_regex_and_non_idempotent_rule_are_rejected(self):
        for changes,message in (({'pattern':'('},'正则无效'),({'pattern':'$','replacement':'_继续追加'},'重复执行')):
            with self.assertRaisesRegex(ValueError,message):self.service.preview_scene_rule(self.payload(**changes))
        with self.conn.cursor() as c:
            c.execute('SELECT 1');self.assertEqual(1,c.fetchone()[0])

    def test_stale_preview_cannot_save_a_different_pattern(self):
        payload=self.payload();proof=self.service.preview_scene_rule(payload)
        with self.assertRaisesRegex(ValueError,'重新预览'):
            self.service.save_scene_rule({**payload,'pattern':'-其他流水：[0-9]+$','preview_token':proof['preview_token']},'scene_transaction_test',None)

    def test_configuration_names_are_clean_and_same_unfreeze_has_one_entry(self):
        rows=self.service.list_fee_mappings({'platform_code':'ks','page_size':200})['items']
        self.assertFalse(any('订单号' in r['secondary_category_name'] or '退款单号' in r['secondary_category_name'] or '订单编号' in r['secondary_category_name'] for r in rows))
        matches=[r for r in rows if r['secondary_category_name']=='资金解冻 + 退款']
        self.assertEqual(1,len(matches))
        self.assertGreaterEqual(len(matches[0]['group_mapping_ids']),2)
        self.assertIn('货款结算 + 快手小店交易结算',[r['secondary_category_name'] for r in rows])

    def test_jd_and_tmall_transaction_labels_have_one_effective_type(self):
        jd=self.service.list_fee_mappings({'platform_code':'jd','page_size':200})['items']
        refund=[r for r in jd if r['secondary_category_name']=='结算后售后退款（销售退款）']
        self.assertEqual(1,len(refund))
        self.assertTrue({11105,11106,11107}<=set(refund[0]['group_mapping_ids']))
        tmall=self.service.list_fee_mappings({'platform_code':'tmall','page_size':200})['items']
        commission=[r for r in tmall if r['secondary_category_name']=='转账 + 天猫佣金-百补订单激励前返']
        self.assertEqual(1,len(commission))
        self.assertTrue({5298,9142}<=set(commission[0]['group_mapping_ids']))
        with self.conn.cursor(cursor_factory=RealDictCursor) as c:
            self.assertEqual({11105,11106,11107},{r['mapping_id'] for r in mapping_group(c,11105)})

    def test_group_edit_and_clear_apply_to_all_equivalent_mappings(self):
        with self.conn.cursor(cursor_factory=RealDictCursor) as c:members=mapping_group(c,12006)
        self.assertGreaterEqual(len(members),2)
        self.service.assign_fee_mappings({'items':[members[0]],'operating_treatment':'income'},'scene_transaction_test',None)
        with self.conn.cursor() as c:
            c.execute('SELECT DISTINCT operating_treatment FROM dim.dim_platform_fee_mapping WHERE mapping_id=ANY(%s)',([m['mapping_id'] for m in members],))
            self.assertEqual([('income',)],c.fetchall())
        self.service.delete_fee_mapping(members[0]['mapping_id'],'scene_transaction_test',None)
        with self.conn.cursor() as c:
            c.execute('SELECT DISTINCT primary_category_code,operating_treatment FROM dim.dim_platform_fee_mapping WHERE mapping_id=ANY(%s)',([m['mapping_id'] for m in members],))
            self.assertEqual([('unmapped','income')],c.fetchall())

    def test_dwd_cleaning_preserves_native_identity_description_and_money(self):
        with self.conn.cursor() as c:
            query="SELECT source_document_type,source_id,source_description,directional_expense_amount,flow_no,order_no FROM dwd.dwd_ks_platform_expense_source_detail ORDER BY source_document_type,source_id,directional_expense_amount,flow_no,order_no,source_description"
            c.execute(query);before=c.fetchall()
            normalize_dwd(c,'ks')
            c.execute(query);self.assertEqual(before,c.fetchall())
            c.execute("SELECT count(DISTINCT secondary_category_name) FROM dwd.dwd_ks_platform_expense_source_detail WHERE source_business_type='货款结算' AND source_description LIKE '快手小店交易结算-订单号：%'")
            self.assertEqual(1,c.fetchone()[0])

    def test_all_types_reports_daily_record_count_separately_from_scene_count(self):
        result=self.service.list_operating_details({})
        self.assertGreater(result['summary']['total'],result['summary']['scene_total'])
        self.assertEqual(result['summary']['total'],result['pagination']['total'])

    def test_all_types_merge_formula_codes_but_preserve_money(self):
        with self.conn.cursor() as c:
            c.execute('''INSERT INTO ads.ads_platform_operating_flow_company_shop_daily_scene
                SELECT (jsonb_populate_record(NULL::ads.ads_platform_operating_flow_company_shop_daily_scene,
                    to_jsonb(d)||jsonb_build_object('secondary_category_code','scene_aggregation_test_code'))).*
                FROM ads.ads_platform_operating_flow_company_shop_daily_scene d WHERE platform_code='jd' LIMIT 1''')
            c.execute("SELECT sum(income_amount),sum(expense_amount) FROM ads.ads_platform_operating_flow_company_shop_daily_scene WHERE platform_code='jd'")
            income,expense=c.fetchone()
        result=self.service.list_operating_details({'platform_code':'jd','page_size':200})
        self.assertEqual((income,expense),(result['summary']['income_amount'],result['summary']['expense_amount']))
        self.assertGreater(result['summary']['published_scene_rows'],result['pagination']['total'])

    def test_saved_rule_reaches_historical_dwd_and_published_ads_without_money_change(self):
        old=next(r for r in self.service.list_scene_rules()['items'] if r['rule_code']=='ks_order_number_suffix')
        payload={**old,'replacement':'-已清洗'}
        proof=self.service.preview_scene_rule(payload)
        self.assertTrue(proof['can_save'])
        self.service.save_scene_rule({**payload,'preview_token':proof['preview_token']},'scene_transaction_test',None)
        with self.conn.cursor() as c:
            c.execute("SELECT sum(source_amount),sum(directional_expense_amount),count(*) FROM dwd.dwd_ks_platform_expense_source_detail")
            before=c.fetchone()
            c.execute((ROOT/'sql/ks/platform_expense/316_refresh_dwd_ks_platform_expense_source_detail_postgres.sql').read_text(encoding='utf-8'))
            normalize_dwd(c,'ks')
            c.execute("SELECT sum(source_amount),sum(directional_expense_amount),count(*) FROM dwd.dwd_ks_platform_expense_source_detail")
            self.assertEqual(before,c.fetchone())
            c.execute((ROOT/'sql/ks/platform_expense/317_refresh_dws_ks_platform_expense_shop_daily_category_postgres.sql').read_text(encoding='utf-8'))
            refresh_projection(c,('ks',))
            c.execute("SELECT count(*) FROM ads.ads_platform_operating_flow_company_shop_daily_scene WHERE platform_code='ks' AND secondary_category_name='货款结算 + 快手小店交易结算-已清洗'")
            self.assertGreater(c.fetchone()[0],0)
            c.execute("SELECT sum(income_amount),sum(expense_amount) FROM ads.ads_platform_operating_flow_company_shop_daily_scene WHERE platform_code='ks' AND shop_code='123456789' AND stat_date>='2026-09-01' AND stat_date<'2026-10-01'")
            self.assertEqual((Decimal('133806.50'),Decimal('61377.73')),c.fetchone())

    def test_tmall_reconciliation_uses_the_same_cleaned_scene_match(self):
        from etl.tmall.run_tmall_main_business_finance_etl import validate_results
        with self.conn.cursor() as c:
            normalize_dwd(c,'tmall')
            c.execute((ROOT/'sql/tmall/platform_expense/335_refresh_dws_tmall_platform_expense_shop_daily_category_postgres.sql').read_text(encoding='utf-8'))
            refresh_projection(c,('tmall',))
            for path in ('ads/platform_expense/312_refresh_ads_platform_expense_company_shop_daily_category_postgres.sql',
                         'ads/main_business_income/328_refresh_ads_platform_main_business_income_company_shop_daily_category_postgres.sql'):
                c.execute((ROOT/'sql'/path).read_text(encoding='utf-8'))
            result=validate_results(c)
            self.assertEqual(Decimal('0.00'),result['reconciliation_difference'])

    def test_automatic_note_follows_inline_changes_and_custom_note_is_preserved(self):
        from etl.platform_finance.operating_policy import automatic_classification_note
        with self.conn.cursor(cursor_factory=RealDictCursor) as c:
            c.execute('SELECT * FROM dim.dim_platform_fee_mapping WHERE mapping_id=12002')
            row=dict(c.fetchone())
            c.execute('UPDATE dim.dim_platform_fee_mapping SET classification_note=%s WHERE mapping_id=12002',
                (automatic_classification_note(row,row['operating_treatment'],row['primary_category_name']),))
        row.pop('updated_at',None)
        self.service.assign_fee_mappings({'items':[row],'operating_treatment':'income'},'scene_transaction_test',None)
        with self.conn.cursor() as c:
            c.execute('SELECT classification_note FROM dim.dim_platform_fee_mapping WHERE mapping_id=12002')
            self.assertIn('计入经营收入',c.fetchone()[0])
        self.service.delete_fee_mapping(12002,'scene_transaction_test',None)
        with self.conn.cursor() as c:
            c.execute('SELECT classification_note FROM dim.dim_platform_fee_mapping WHERE mapping_id=12002')
            self.assertIn('一级分类：未映射',c.fetchone()[0])
            c.execute("UPDATE dim.dim_platform_fee_mapping SET classification_note='财务自定义业务说明' WHERE mapping_id=12002")
        self.service.assign_fee_mappings({'items':[row],'operating_treatment':'excluded'},'scene_transaction_test',None)
        with self.conn.cursor() as c:
            c.execute('SELECT classification_note FROM dim.dim_platform_fee_mapping WHERE mapping_id=12002')
            self.assertEqual('财务自定义业务说明',c.fetchone()[0])
