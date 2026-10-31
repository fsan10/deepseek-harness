"""Exercise category migration and subsequent refreshes in a disposable DB."""
import unittest
import uuid
from contextlib import contextmanager

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from etl.common.settlement_sources import load_pg_env
from etl.platform_finance.category_catalog import (
    ROOT, category_for_scene, ensure_catalog, ensure_category, rebuild_catalog,
)


class CategoryCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_pg_env()
        cls.database = 'codex_category_catalog_test_' + uuid.uuid4().hex[:12]
        cls.admin = psycopg2.connect()
        cls.admin.autocommit = True
        with cls.admin.cursor() as c:
            c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.database)))
        try:
            cls.conn = psycopg2.connect(dbname=cls.database)
            with cls.conn.cursor() as c:
                for path in (
                    'dim/305_dim_platform_fee_mapping_postgres.sql',
                    'dim/373_dim_platform_finance_source_policy_postgres.sql',
                    'dim/464_platform_scene_normalization_postgres.sql',
                    'dim/439_dim_platform_operating_treatment_postgres.sql',
                    'dim/369_dim_platform_fee_primary_category_postgres.sql',
                    'dim/426_dim_platform_fee_primary_category_auto_code_postgres.sql',
                    'dim/463_platform_operating_policy_postgres.sql',
                ):
                    c.execute((ROOT/'sql'/path).read_text(encoding='utf-8'))
            cls.conn.commit()
        except Exception:
            cls._cleanup()
            raise

    @classmethod
    def _cleanup(cls):
        if hasattr(cls, 'conn'):
            cls.conn.close()
        with cls.admin.cursor() as c:
            c.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.database)))
        cls.admin.close()

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    def setUp(self):
        self.cur = self.conn.cursor()

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()

    def scene(self, code, name, description, *, treatment='expense', component=None,
              source_role='PRIMARY', canonical='expense', include=True):
        self.cur.execute('''INSERT INTO dim.dim_platform_fee_primary_category(
            primary_category_code,primary_category_name) VALUES(%s,%s) ON CONFLICT DO NOTHING''',(code,name))
        self.cur.execute('''INSERT INTO dim.dim_platform_fee_mapping(
            platform_code,platform_name,source_document_type,secondary_category_code,
            secondary_category_name,primary_category_code,primary_category_name,
            operating_treatment,canonical_operating_treatment,include_in_platform_expense,
            source_role,metric_role,source_component_code,source_treatment_initialized)
            VALUES('ks','快手','fund',%s,%s,%s,%s,%s,%s,%s,%s,'RECONCILIATION',%s,TRUE)
            RETURNING mapping_id''',
            ('scene_'+uuid.uuid4().hex[:8],description,code,name,treatment,canonical,include,source_role,component))
        return self.cur.fetchone()[0]

    def test_duplicate_names_and_synonyms_are_migrated_then_hard_deleted(self):
        self.scene('after_sale_compensation','售后赔付','消费者赔付')
        self.scene('after_sales_compensation_expense','售后赔付','直赔退款代扣')
        self.scene('reverse_logistics_expense','退货物流费','上门取件运费')
        self.scene('return_logistics_fee','退货物流费用','售后费用-运费补偿')
        result=rebuild_catalog(self.cur)
        self.cur.execute('SELECT count(*) FROM dim.dim_platform_fee_mapping')
        self.assertEqual(self.cur.fetchone()[0],4)
        self.cur.execute('SELECT primary_category_code FROM dim.dim_platform_fee_primary_category ORDER BY 1')
        self.assertEqual(self.cur.fetchall(),[('after_sale_compensation',),('return_shipping_expense',)])
        self.assertEqual(len(result['deleted_categories']),3)

    def test_refund_reclassification_preserves_treatment_sign_contract_and_role(self):
        ident=self.scene('after_sales_compensation_expense','售后赔付','资金扣减 + 快手小店退款-超售后期',
                         treatment='income',canonical=None,include=False,source_role='RECONCILIATION')
        rebuild_catalog(self.cur)
        self.cur.execute('''SELECT primary_category_code,operating_treatment,
            canonical_operating_treatment,include_in_platform_expense,source_role
            FROM dim.dim_platform_fee_mapping WHERE mapping_id=%s''',(ident,))
        self.assertEqual(self.cur.fetchone(),('sales_refund','income',None,False,'RECONCILIATION'))

    def test_fee_returns_and_charges_use_same_business_category(self):
        for text in ('扣款 + 品牌新享新品孵化软件服务费扣款','交易分账 + 品牌新享新品孵化软件服务费退款'):
            self.assertEqual(category_for_scene({'operating_treatment':'expense',
                'primary_category_code':'other_platform_expense','secondary_category_name':text}),'platform_service_fee')
        for text in ('百亿补贴软件服务费扣款','百亿补贴软件服务费退款'):
            self.assertEqual(category_for_scene({'operating_treatment':'expense',
                'primary_category_code':'platform_service_fee','secondary_category_name':text}),'baiyibutie')

    def test_normalized_duplicate_name_is_rejected_across_platforms(self):
        self.scene('shipping_insurance','运费保险','运费险')
        rebuild_catalog(self.cur)
        with self.assertRaises(psycopg2.IntegrityError):
            self.cur.execute('''INSERT INTO dim.dim_platform_fee_primary_category(
                primary_category_code,primary_category_name,platform_code)
                VALUES('PDD_99',' 运费　保 险 ','pdd')''')

    def test_human_category_override_survives_later_discovery(self):
        ident=self.scene('shipping_insurance','运费保险','运费险')
        rebuild_catalog(self.cur)
        self.cur.execute("INSERT INTO dim.dim_platform_fee_primary_category(primary_category_code,primary_category_name) VALUES('KS_90','财务自定义分类')")
        self.cur.execute("UPDATE dim.dim_platform_fee_mapping SET primary_category_code='KS_90',primary_category_name='财务自定义分类' WHERE mapping_id=%s",(ident,))
        ensure_catalog(self.cur)
        self.cur.execute('SELECT primary_category_code FROM dim.dim_platform_fee_mapping WHERE mapping_id=%s',(ident,))
        self.assertEqual(self.cur.fetchone(),('KS_90',))

    def test_old_seed_reference_cannot_recreate_deleted_same_name_category(self):
        self.scene('freight_insurance_expense','运费保险','原运费保险')
        rebuild_catalog(self.cur)
        self.cur.execute('''INSERT INTO dim.dim_platform_fee_mapping(
            platform_code,platform_name,source_document_type,secondary_category_code,
            secondary_category_name,primary_category_code,primary_category_name,
            operating_treatment,source_role,metric_role)
            VALUES('wechat_channels','视频号','settlement','new_insurance','新运费保险',
                'shipping_insurance','运费保险','expense','PRIMARY','PLATFORM_EXPENSE')''')
        self.cur.execute((ROOT/'sql/dim/369_dim_platform_fee_primary_category_postgres.sql').read_text(encoding='utf-8'))
        ensure_catalog(self.cur)
        self.cur.execute("SELECT primary_category_code FROM dim.dim_platform_fee_mapping WHERE secondary_category_code='new_insurance'")
        self.assertEqual(self.cur.fetchone(),('freight_insurance_expense',))
        self.cur.execute("SELECT count(*) FROM dim.dim_platform_fee_primary_category WHERE primary_category_name='运费保险'")
        self.assertEqual(self.cur.fetchone()[0],1)

    def test_clearing_classification_is_not_undone_by_normal_refresh(self):
        ident=self.scene('freight_insurance_expense','运费保险','实际运费保险')
        rebuild_catalog(self.cur)
        self.cur.execute("UPDATE dim.dim_platform_fee_mapping SET primary_category_code='unmapped',primary_category_name='未映射',updated_by='finance' WHERE mapping_id=%s",(ident,))
        ensure_catalog(self.cur)
        self.cur.execute('SELECT primary_category_code,operating_treatment FROM dim.dim_platform_fee_mapping WHERE mapping_id=%s',(ident,))
        self.assertEqual(self.cur.fetchone(),('unmapped','expense'))

    def test_old_synonym_seed_is_removed_even_when_its_spelling_differs(self):
        self.scene('return_shipping_expense','退货物流费','商责退运费')
        rebuild_catalog(self.cur)
        with self.assertRaises(psycopg2.IntegrityError):
            self.cur.execute("INSERT INTO dim.dim_platform_fee_primary_category(primary_category_code,primary_category_name) VALUES('PDD_90','退货物流费用')")

    def test_new_scene_can_reuse_a_manual_synonym_category_with_its_stable_code(self):
        self.cur.execute("INSERT INTO dim.dim_platform_fee_primary_category(primary_category_code,primary_category_name) VALUES('KS_90','退货物流费用')")
        rebuild_catalog(self.cur)
        self.assertEqual(ensure_category(self.cur,'return_shipping_expense'),('KS_90','退货物流费用'))

    def test_source_policy_no_longer_changes_initialized_roles_after_category_merge(self):
        ident=self.scene('non_expense_refund_reconciliation','非费用-退款勾稽','实际资金退款',
            treatment='income',canonical='income',include=False,source_role='REFUND_SUPPLEMENT')
        self.cur.execute("UPDATE dim.dim_platform_fee_mapping SET metric_role='MAIN_REFUND',dedup_rule_code='RELATED_ORDER_REFUND_GUARD' WHERE mapping_id=%s",(ident,))
        rebuild_catalog(self.cur)
        self.cur.execute((ROOT/'sql/dim/373_dim_platform_finance_source_policy_postgres.sql').read_text(encoding='utf-8'))
        self.cur.execute('SELECT source_role,metric_role,dedup_rule_code FROM dim.dim_platform_fee_mapping WHERE mapping_id=%s',(ident,))
        self.assertEqual(self.cur.fetchone(),('REFUND_SUPPLEMENT','MAIN_REFUND','RELATED_ORDER_REFUND_GUARD'))

    def test_source_policy_preserves_legacy_initialized_exclude_metric_metadata(self):
        ident=self.scene('non_expense_goods_payment','非费用-货款','货款',
            treatment='income',canonical='income',include=False,source_role='PRIMARY')
        self.cur.execute("UPDATE dim.dim_platform_fee_mapping SET metric_role='EXCLUDE' WHERE mapping_id=%s",(ident,))
        rebuild_catalog(self.cur)
        self.cur.execute((ROOT/'sql/dim/373_dim_platform_finance_source_policy_postgres.sql').read_text(encoding='utf-8'))
        self.cur.execute('SELECT source_role,metric_role FROM dim.dim_platform_fee_mapping WHERE mapping_id=%s',(ident,))
        self.assertEqual(self.cur.fetchone(),('PRIMARY','EXCLUDE'))

    def test_income_formula_seed_does_not_recreate_merged_or_renamed_classification(self):
        from etl.platform_finance.operating_treatment import seed_income_components
        rebuild_catalog(self.cur)
        self.cur.execute('''CREATE SCHEMA dws; CREATE TABLE dws.dws_ks_main_business_income_shop_daily_category(
            platform_code TEXT,platform_name TEXT,source_document_type TEXT,
            secondary_category_code TEXT,secondary_category_name TEXT,
            primary_category_code TEXT,primary_category_name TEXT);
            INSERT INTO dws.dws_ks_main_business_income_shop_daily_category VALUES(
                'ks','快手','settlement','order_paid','订单实付(元)','product_sales_income','商品销售收入');''')
        seed_income_components(self.cur,'ks')
        self.cur.execute("UPDATE dim.dim_platform_fee_primary_category SET primary_category_name='财务销售收入' WHERE primary_category_code='sales_income'")
        self.cur.execute("UPDATE dim.dim_platform_fee_mapping SET primary_category_name='财务销售收入' WHERE primary_category_code='sales_income'")
        seed_income_components(self.cur,'ks')
        self.cur.execute('SELECT primary_category_code,primary_category_name FROM dim.dim_platform_fee_mapping')
        self.assertEqual(self.cur.fetchall(),[('sales_income','财务销售收入')])
        self.cur.execute('SELECT count(*) FROM dim.dim_platform_fee_primary_category')
        self.assertEqual(self.cur.fetchone()[0],1)

    def test_unconfirmed_balance_refund_keeps_unconfirmed_nature(self):
        ident=self.scene('unmapped','未映射','余额退款',treatment=None,canonical=None,include=False)
        rebuild_catalog(self.cur)
        self.cur.execute('SELECT primary_category_code,operating_treatment FROM dim.dim_platform_fee_mapping WHERE mapping_id=%s',(ident,))
        self.assertEqual(self.cur.fetchone(),('pending_nature',None))

    def test_new_fee_scene_is_classified_without_rewriting_its_signed_contract(self):
        from etl.platform_finance.operating_treatment import prepare_fee_scenes
        rebuild_catalog(self.cur)
        self.cur.execute('''CREATE SCHEMA dwd;
            CREATE TABLE dwd.dwd_ks_platform_expense_source_detail(
                platform_name TEXT,source_document_type TEXT,source_business_type TEXT,
                source_description TEXT,secondary_category_name TEXT,directional_expense_amount NUMERIC);
            INSERT INTO dwd.dwd_ks_platform_expense_source_detail VALUES
                ('快手','fund','佣金/技术服务费返还','分账追回-MCN',
                 '佣金/技术服务费返还 + 分账追回-MCN',-2.25)''')
        prepare_fee_scenes(self.cur,'ks')
        self.cur.execute('''SELECT primary_category_code,operating_treatment,
            include_in_platform_expense,source_role FROM dim.dim_platform_fee_mapping''')
        self.assertEqual(self.cur.fetchall(),[('influencer_commission','expense',True,'EXPENSE_OFFSET')])

    def test_category_page_counts_current_treatment_instead_of_legacy_boolean(self):
        from apps.file_ingest.service import FileIngestService
        self.scene('freight_insurance_expense','运费保险','实际运费保险',
                   treatment='expense',canonical=None,include=False)
        rebuild_catalog(self.cur)
        service=object.__new__(FileIngestService)
        @contextmanager
        def transaction():
            with self.conn.cursor(cursor_factory=RealDictCursor) as c:
                yield c
        service.transaction=transaction
        result=service.list_fee_categories({})
        self.assertEqual(len(result['items']),1)
        self.assertEqual(result['items'][0]['included_mapping_count'],1)


if __name__=='__main__':
    unittest.main()
