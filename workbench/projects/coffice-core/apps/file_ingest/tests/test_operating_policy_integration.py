"""Real service and financial projection checks; every change is rolled back."""
import os
import unittest
from contextlib import contextmanager
from decimal import Decimal
import psycopg2
from psycopg2.extras import RealDictCursor
from apps.file_ingest.service import FileIngestService
from etl.common.settlement_sources import load_pg_env
from etl.platform_finance.operating_treatment import prepare_schema,refresh_projection,ROOT
from etl.platform_finance.operating_policy import default_treatment

@unittest.skipUnless(os.getenv('RUN_OPERATING_DB_TESTS')=='1','explicit transaction-only database checks')
class OperatingPolicyIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_pg_env()
        cls.conn=psycopg2.connect(application_name='operating_policy_rollback_test',options='-c lock_timeout=60000 -c statement_timeout=120000')
        try:
            with cls.conn.cursor() as c:
                c.execute("SET LOCAL lock_timeout='0'")
                c.execute("SET LOCAL statement_timeout='0'")
                c.execute("SELECT pg_advisory_xact_lock(hashtext('mock_coffice_global_etl'))")
                c.execute("SET LOCAL lock_timeout='10000'")
                c.execute("SET LOCAL statement_timeout='60000'")
                prepare_schema(c)
                refresh_projection(c)
            cls.service=object.__new__(FileIngestService)
            @contextmanager
            def transaction():
                with cls.conn.cursor(cursor_factory=RealDictCursor) as c:yield c
            cls.service.transaction=transaction
        except Exception:
            cls.conn.rollback();cls.conn.close();raise

    @classmethod
    def tearDownClass(cls):
        cls.conn.rollback();cls.conn.close()

    def setUp(self):
        with self.conn.cursor() as c:c.execute('SAVEPOINT policy_test')

    def tearDown(self):
        with self.conn.cursor() as c:c.execute('ROLLBACK TO SAVEPOINT policy_test')

    def item(self,ident):
        with self.conn.cursor(cursor_factory=RealDictCursor) as c:
            c.execute('SELECT * FROM dim.dim_platform_fee_mapping WHERE mapping_id=%s',(ident,))
            return dict(c.fetchone())

    def save(self,ident,**changes):
        return self.service.assign_fee_mappings({'items':[self.item(ident)],**changes},'policy_transaction_test',None)

    def project(self,p):
        with self.conn.cursor() as c:refresh_projection(c,(p,))

    def amount(self,scene):
        with self.conn.cursor() as c:
            c.execute('SELECT sum(income_amount),sum(expense_amount),sum(excluded_amount) FROM dws.dws_wechat_channels_operating_flow_shop_daily_scene WHERE secondary_category_name=%s',(scene,))
            return c.fetchone()

    def test_both_video_advances_can_roundtrip_all_three_treatments(self):
        for ident,scene,signed in ((745,'极速退款垫资',Decimal('1703')),(746,'回补极速退款垫资',Decimal('-1703'))):
            self.assertTrue(self.service.fee_mapping_source(ident)['rule']['treatment_editable'])
            for treatment,expected in (('income',(signed,Decimal(0),Decimal(0))),('expense',(Decimal(0),-signed,Decimal(0))),('excluded',(Decimal(0),Decimal(0),signed))):
                preview=self.service.preview_fee_mappings({'items':[self.item(ident)],'operating_treatment':treatment})
                self.assertGreater(preview['source_rows'],0)
                self.save(ident,operating_treatment=treatment)
                self.project('wechat_channels')
                self.assertEqual(expected,self.amount(scene))

    def test_category_can_be_changed_while_nature_remains_pending(self):
        self.save(18792,operating_treatment='pending')
        result=self.save(18792,primary_category_code='other_platform_expense',primary_category_name='其他平台费用')
        self.assertIsNone(result['items'][0]['operating_treatment'])
        with self.conn.cursor() as c:prepare_schema(c)
        self.assertIsNone(self.item(18792)['operating_treatment'])

    def test_business_exclusion_can_be_reversed_despite_old_snapshot(self):
        self.assertEqual('excluded',self.item(745)['canonical_operating_treatment'])
        self.save(745,operating_treatment='income')
        self.save(745,operating_treatment='excluded')
        self.save(745,operating_treatment='expense')
        self.assertEqual('expense',self.item(745)['operating_treatment'])

    def test_confirmed_already_accounted_source_is_visible_and_protected(self):
        detail=self.service.fee_mapping_source(138)
        self.assertFalse(detail['rule']['treatment_editable'])
        self.assertGreater(detail['evidence']['matched_rows'],0)
        with self.assertRaisesRegex(ValueError,'结算单'):
            self.save(138,operating_treatment='income')
        with self.assertRaisesRegex(ValueError,'已统计关联'):
            self.save(138,source_usage='independent',source_correction_reason='财务申请核对来源',operating_treatment='income')
        with self.conn.cursor() as c:
            c.execute("SELECT count(*) FROM ops.operation_log WHERE operation_type='fee_mapping_rejected' AND operator='policy_transaction_test'")
            self.assertGreater(c.fetchone()[0],0)

    def test_missing_primary_source_does_not_unlock_a_verified_contract(self):
        with self.conn.cursor() as c:
            c.execute("DELETE FROM dwd.dwd_ks_main_business_income_source_detail WHERE source_document_type='settlement'")
        proof=self.service.fee_mapping_source(138)['evidence']
        self.assertEqual(0,proof['matched_rows'])
        self.assertFalse(proof['correction_available'])

    def test_changed_money_requires_a_new_preview(self):
        payload={'items':[self.item(745)],'operating_treatment':'income'}
        proof=self.service.preview_fee_mappings(payload)
        with self.conn.cursor() as c:
            c.execute("UPDATE ads.ads_platform_operating_flow_company_shop_daily_scene SET source_signed_amount=source_signed_amount+1 WHERE platform_code='wechat_channels' AND secondary_category_name='极速退款垫资'")
        with self.assertRaisesRegex(ValueError,'重新预览'):
            self.service.assign_fee_mappings({**payload,'preview_token':proof['preview_token']},'policy_transaction_test',None)

    def test_alias_has_one_effective_configuration_entry(self):
        result=self.service.list_fee_mappings({'platform_code':'xhs','page_size':200})
        self.assertNotIn(4803,[r['mapping_id'] for r in result['items']])
        target=next(r for r in result['items'] if r['mapping_id']==11113)
        self.assertIn('申诉调账',target['aliases'])
        with self.assertRaisesRegex(Exception,'统一配置入口'):
            self.save(4803,operating_treatment='excluded')

    def test_unproven_accounted_label_can_be_corrected_with_evidence(self):
        with self.conn.cursor() as c:
            c.execute('''INSERT INTO dim.dim_platform_fee_mapping(platform_code,platform_name,source_document_type,
                secondary_category_code,secondary_category_name,source_business_type,
                source_description_match_type,source_description_match_value,mapping_priority,
                primary_category_code,primary_category_name,operating_treatment,canonical_operating_treatment,
                source_role,metric_role,source_treatment_initialized,source_usage,source_usage_note,policy_initialized)
                VALUES('ks','快手','fund','test_source_review','货款结算 + 独立来源核对测试','货款结算',
                'exact','独立来源核对测试',9999,'unmapped','未映射','excluded',NULL,
                'RECONCILIATION','RECONCILIATION',TRUE,'accounted','待更正的来源判定',TRUE) RETURNING mapping_id''')
            ident=c.fetchone()[0]
            c.execute("UPDATE dwd.dwd_ks_platform_expense_source_detail SET source_description='独立来源核对测试',secondary_category_name='货款结算 + 独立来源核对测试',order_no='policy_test_order_not_in_primary' WHERE (source_document_type,source_id,secondary_category_name)=(SELECT source_document_type,source_id,secondary_category_name FROM dwd.dwd_ks_platform_expense_source_detail WHERE source_document_type='fund' AND source_business_type='货款结算' LIMIT 1)")
        detail=self.service.fee_mapping_source(ident)
        self.assertTrue(detail['evidence']['correction_available'])
        self.save(ident,source_usage='independent',source_correction_reason='已核对为独立业务金额')
        self.assertTrue(self.service.fee_mapping_source(ident)['rule']['treatment_editable'])
        self.save(ident,operating_treatment='income')
        self.assertEqual('income',self.item(ident)['operating_treatment'])

    def test_pending_filter_and_category_are_independent(self):
        result=self.service.list_fee_mappings({'operating_treatment':'pending','page_size':200})
        self.assertIn(18792,[r['mapping_id'] for r in result['items']])
        details=self.service.list_operating_details({'operating_treatment':'pending'})
        self.assertGreater(details['summary']['pending_total'],0)
        self.assertEqual(Decimal(0),details['summary']['income_amount'])
        self.assertEqual(Decimal(0),details['summary']['expense_amount'])

    def test_confirmed_manual_nature_survives_schema_and_classification_refresh(self):
        self.save(8756,operating_treatment='income')
        with self.conn.cursor() as c:prepare_schema(c)
        self.assertEqual('manual',self.item(8756)['treatment_origin'])
        self.project('xhs')
        with self.conn.cursor() as c:
            c.execute("SELECT sum(income_amount),sum(expense_amount) FROM dws.dws_xhs_operating_flow_shop_daily_scene WHERE secondary_category_name='小额收款'")
            self.assertEqual((Decimal('11'),Decimal(0)),c.fetchone())

    def test_source_role_cleanup_does_not_enable_a_second_formula_branch(self):
        for ident,role in ((12004,'REFUND_SUPPLEMENT'),(23003,'EXPENSE_OFFSET'),(23004,'SUPPLEMENT')):
            row=self.item(ident)
            self.assertEqual(role,row['source_role'])
            self.assertFalse(row['include_in_platform_expense'])
            self.assertIsNone(row['canonical_operating_treatment'])
        self.project('ks')
        with self.conn.cursor() as c:
            c.execute("SELECT sum(income_amount),sum(expense_amount) FROM dws.dws_ks_operating_flow_shop_daily_scene WHERE shop_code='123456789' AND stat_date>='2026-09-01' AND stat_date<'2026-10-01'")
            self.assertEqual((Decimal('133806.50'),Decimal('61377.73')),c.fetchone())

    def test_configuration_save_exposes_queued_refresh(self):
        result=self.save(745,operating_treatment='excluded')
        self.assertEqual('queued',result['etl_run']['status'])
        item=next(r for r in self.service.list_fee_mappings({'platform_code':'wechat_channels'})['items'] if r['mapping_id']==745)
        self.assertEqual('等待重算',item['configuration_status_label'])
        self.assertIsNotNone(item['last_etl_run_id'])

    def test_unknown_xhs_income_type_is_visible_pending_and_can_be_confirmed(self):
        from etl.platform_finance.operating_treatment import prepare_fee_scenes
        with self.conn.cursor() as c:
            c.execute('''INSERT INTO dwd.dwd_xhs_main_business_income_source_detail
                SELECT (jsonb_populate_record(NULL::dwd.dwd_xhs_main_business_income_source_detail,
                    to_jsonb(d)||jsonb_build_object('source_id',-99999999,'source_business_type','新增待确认交易',
                    'secondary_category_name','新增待确认交易','restored_income_amount',25.50))).*
                FROM dwd.dwd_xhs_main_business_income_source_detail d LIMIT 1''')
            prepare_fee_scenes(c,'xhs')
            c.execute((ROOT/'sql/xhs/main_business_finance/352_refresh_dws_xhs_main_business_finance_shop_daily_category_postgres.sql').read_text(encoding='utf-8'))
        self.project('xhs')
        item=next(r for r in self.service.list_fee_mappings({'platform_code':'xhs','operating_treatment':'pending'})['items'] if r['source_business_type']=='新增待确认交易')
        self.assertIsNone(item['operating_treatment'])
        self.save(item['mapping_id'],operating_treatment='income')
        self.project('xhs')
        with self.conn.cursor() as c:
            c.execute("SELECT sum(income_amount),sum(expense_amount) FROM dws.dws_xhs_operating_flow_shop_daily_scene WHERE secondary_category_name='订单结算交易 + 新增待确认交易'")
            self.assertEqual((Decimal('25.50'),Decimal(0)),c.fetchone())

class DefaultTreatmentTests(unittest.TestCase):
    def test_unknown_other_service_and_negative_flow_do_not_become_expenses(self):
        self.assertIsNone(default_treatment('xhs','settlement','新服务款'))
        self.assertIsNone(default_treatment('ks','fund','资金扣减 + 新金额','资金扣减','新金额'))
        self.assertEqual('expense',default_treatment('xhs','settlement','平台佣金'))
        self.assertEqual('expense',default_treatment('ks','fund','返还','佣金/技术服务费返还','分账追回-MCN'))

if __name__=='__main__':unittest.main()
