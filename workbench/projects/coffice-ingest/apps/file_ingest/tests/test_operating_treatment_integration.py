"""Run against configured PG settings; every fixture and audit change rolls back."""
from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor

from apps.file_ingest.service import FileIngestService
from etl.common.settlement_sources import load_pg_env
from etl.platform_finance.operating_treatment import prepare_schema, refresh_projection, validate_projection


@unittest.skipUnless(os.getenv('RUN_OPERATING_DB_TESTS') == '1', 'explicit transaction-only database test')
class OperatingTreatmentIntegrationTests(unittest.TestCase):
    def test_category_clear_routing_and_excluded_detail_are_independent(self):
        load_pg_env()
        connection = psycopg2.connect(host=os.getenv('PGHOST'),port=os.getenv('PGPORT'),
            dbname=os.getenv('PGDATABASE'),user=os.getenv('PGUSER'),password=os.getenv('PGPASSWORD'),
            options='-c lock_timeout=60000 -c statement_timeout=120000')
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout='0'")
                cursor.execute("SET LOCAL statement_timeout='0'")
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext('mock_coffice_global_etl'))")
                cursor.execute("SET LOCAL lock_timeout='5000'")
                cursor.execute("SET LOCAL statement_timeout='30000'")
                prepare_schema(cursor)
                refresh_projection(cursor)
                def totals():
                    cursor.execute("SELECT SUM(income_amount),SUM(expense_amount) FROM dws.dws_pdd_operating_flow_shop_daily_scene WHERE shop_code='116694910' AND stat_date>=DATE '2026-09-01' AND stat_date<DATE '2026-10-01'")
                    return cursor.fetchone()
                initial = totals()
                self.assertEqual((Decimal('233496.90'),Decimal('5302.45')), initial)
                cursor.execute("UPDATE dim.dim_platform_fee_mapping SET primary_category_code='unmapped',primary_category_name='未映射' WHERE mapping_id=725")
                refresh_projection(cursor,('pdd',))
                self.assertEqual(initial,totals())
                cursor.execute("SELECT SUM(expense_amount) FROM dws.dws_pdd_operating_flow_shop_daily_scene WHERE secondary_category_code='pdd_basic_technology_fee' AND mapping_status='unmapped' AND shop_code='116694910' AND stat_date>=DATE '2026-09-01' AND stat_date<DATE '2026-10-01'")
                self.assertEqual(Decimal('1437.22'),cursor.fetchone()[0])
                cursor.execute("UPDATE dim.dim_platform_fee_mapping SET operating_treatment='income' WHERE mapping_id=725")
                refresh_projection(cursor,('pdd',))
                rerouted = totals()
                self.assertEqual(initial[0]-initial[1],rerouted[0]-rerouted[1])
                self.assertEqual((Decimal('232059.68'),Decimal('3865.23')),rerouted)
                cursor.execute("SELECT -SUM(excluded_amount) FROM dws.dws_pdd_operating_flow_shop_daily_scene WHERE operating_treatment='excluded' AND shop_code='116694910' AND stat_date>=DATE '2026-09-01' AND stat_date<DATE '2026-10-01'")
                self.assertEqual(Decimal('230210.00'),cursor.fetchone()[0])
                cursor.execute("SELECT COUNT(*) FROM dws.dws_pdd_operating_flow_shop_daily_scene WHERE income_amount-expense_amount+excluded_amount<>source_signed_amount")
                self.assertEqual(0,cursor.fetchone()[0])
                from etl.platform_finance.operating_treatment import ROOT
                for path in ('ads/platform_expense/312_refresh_ads_platform_expense_company_shop_daily_category_postgres.sql','ads/main_business_income/328_refresh_ads_platform_main_business_income_company_shop_daily_category_postgres.sql'):
                    cursor.execute((ROOT/'sql'/path).read_text(encoding='utf-8'))
                self.assertEqual((0,0),validate_projection(cursor,'pdd'))
                # A genuine application mutation is also transaction-only here.
                service = FileIngestService.__new__(FileIngestService)
                @contextmanager
                def transaction():
                    with connection.cursor(cursor_factory=RealDictCursor) as q:
                        yield q
                service.transaction = transaction
                with transaction() as q:
                    q.execute('SELECT * FROM dim.dim_platform_fee_mapping WHERE mapping_id=719')
                    item = dict(q.fetchone())
                result = service.assign_fee_mappings({'items':[item], 'primary_category_code':'unmapped',
                    'primary_category_name':'未映射'},'transaction_test',None)
                self.assertEqual('income',result['items'][0]['operating_treatment'])
                self.assertFalse(result['items'][0]['include_in_platform_expense'])
                cursor.execute('SAVEPOINT old_boolean_client')
                with self.assertRaises(psycopg2.errors.RaiseException):
                    cursor.execute('UPDATE dim.dim_platform_fee_mapping SET include_in_platform_expense=TRUE WHERE mapping_id=719')
                cursor.execute('ROLLBACK TO SAVEPOINT old_boolean_client')
                with transaction() as q:
                    q.execute('SELECT * FROM dim.dim_platform_fee_mapping WHERE mapping_id=722')
                    refund = dict(q.fetchone())
                updated = service.assign_fee_mappings({'items':[refund], 'operating_treatment':'excluded'},
                    'transaction_test',None)['items'][0]
                self.assertEqual('sales_refund',updated['primary_category_code'])
                self.assertEqual('excluded',updated['operating_treatment'])
                refresh_projection(cursor,('pdd',))
                before_clear = totals()
                service.delete_fee_category('platform_service_fee','transaction_test',None)
                refresh_projection(cursor,('pdd',))
                self.assertEqual(before_clear,totals())
                # A brand-new confirmed scene is routed even though the historical
                # formula never knew its category. Repeat schema initialization.
                with transaction() as q:
                    q.execute('SELECT * FROM dim.dim_platform_fee_mapping WHERE mapping_id=723')
                    transfer = dict(q.fetchone())
                    q.execute('DELETE FROM dim.dim_platform_fee_mapping WHERE mapping_id=723')
                transfer['mapping_id'] = None
                created = service.assign_fee_mappings({'items':[transfer], 'operating_treatment':'income',
                    'primary_category_code':'unmapped','primary_category_name':'未映射'},
                    'transaction_test',None)['items'][0]
                self.assertIsNone(created['canonical_operating_treatment'])
                prepare_schema(cursor)
                refresh_projection(cursor,('pdd',))
                cursor.execute("SELECT SUM(income_amount) FROM dws.dws_pdd_operating_flow_shop_daily_scene WHERE secondary_category_name='提现 + 0080001|提现-提现申请' AND shop_code='116694910' AND stat_date>=DATE '2026-09-01' AND stat_date<DATE '2026-10-01'")
                self.assertEqual(Decimal('-165000.00'),cursor.fetchone()[0])
                category_update = service.update_fee_category('sales_refund',{
                    'primary_category_name':'销售退款','is_active':False},'transaction_test',None)
                self.assertEqual('queued',category_update['etl_run']['status'])
        finally:
            connection.rollback()
            connection.close()


if __name__ == '__main__':
    unittest.main()
