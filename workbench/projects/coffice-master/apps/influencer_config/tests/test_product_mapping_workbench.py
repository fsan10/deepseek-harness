"""PostgreSQL integration tests. Enable RUN_PRODUCT_OBSERVATION_DB_TESTS=1.

All fixture mutations, refreshes and generated snapshots are rolled back.
Requires the initial workbench migration/backfill to have completed.
"""
from __future__ import annotations

import os
import unittest
import threading
from contextlib import contextmanager

from apps.influencer_config.product_category import ProductCategoryService
from etl.common.product_mapping_workbench import lock_product_refresh, publish_workbench


@unittest.skipUnless(os.getenv('RUN_PRODUCT_OBSERVATION_DB_TESTS') == '1', 'PostgreSQL integration is opt-in')
class ProductMappingWorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        from apps.fund_split_adjust.server import load_project_env, build_parser
        load_project_env()
        args = build_parser().parse_args([])
        cls.connect_kwargs = dict(host=args.host, port=args.pg_port, dbname=args.dbname,
                                  user=args.user, password=args.password)
        cls.psycopg2 = psycopg2

    def setUp(self):
        from psycopg2.extras import RealDictCursor
        self.connection = self.psycopg2.connect(**self.connect_kwargs)
        self.addCleanup(self.connection.close)
        self.addCleanup(self.connection.rollback)
        self.cursor = self.connection.cursor(cursor_factory=RealDictCursor)
        self.addCleanup(self.cursor.close)
        self.cursor.execute("SET LOCAL statement_timeout = '30s'")
        self.cursor.execute("SET LOCAL lock_timeout = '3s'")
        lock_product_refresh(self.cursor)
        self.service = ProductCategoryService.__new__(ProductCategoryService)
        self.service.connect_kwargs = self.connect_kwargs

        @contextmanager
        def transaction():
            yield self.cursor
        self.service.transaction = transaction

    def current_snapshot(self):
        self.cursor.execute("SELECT summary->>'snapshot_id' AS id FROM ops.refresh_watermark WHERE watermark_key='product_code_mapping'")
        return self.cursor.fetchone()['id']

    def test_full_payload_matches_authoritative_observation_and_query_only_scans_ads(self):
        data = self.service.list_mappings('', 'all', '', 1, 100)
        self.cursor.execute("""
            SELECT TO_JSONB(o) || JSONB_BUILD_OBJECT(
                'product_id', o.current_product_id, 'category_l2_name', o.product_category_l2,
                'category_l1_name', o.large_product_category, 'code_role', m.code_role,
                'mapping_source', m.mapping_source, 'match_rule', m.match_rule,
                'is_active', o.mapping_status = 'mapped') AS payload
            FROM common.v_operating_sales_product_code_observation o
            LEFT JOIN dim.dim_company_product_code_mapping m ON m.mapping_id=o.mapping_id
            ORDER BY CASE o.mapping_status WHEN 'unmapped' THEN 0 WHEN 'inactive' THEN 1 ELSE 2 END,
                o.gmv_amount DESC, o.source_product_code, o.quantity_position
        """)
        self.assertEqual(data['rows'], [row['payload'] for row in self.cursor.fetchall()])
        self.assertTrue(data['snapshot']['snapshot_id'])
        self.cursor.execute("""EXPLAIN (FORMAT JSON)
            SELECT * FROM ads.ads_product_code_mapping_workbench
            WHERE snapshot_id=(SELECT (summary->>'snapshot_id')::UUID FROM ops.refresh_watermark
                               WHERE watermark_key='product_code_mapping')""")
        plan = str(self.cursor.fetchone())
        self.assertNotIn('product_allocation', plan)

    def test_repeated_publication_keeps_business_payload_and_retains_two_versions(self):
        baseline = self.service.list_mappings('', 'all', '', 1, 100)
        one = publish_workbench(self.cursor)
        two = publish_workbench(self.cursor)
        self.assertNotEqual(one['snapshot_id'], two['snapshot_id'])
        self.assertEqual(two['previous_snapshot_id'], one['snapshot_id'])
        current = self.service.list_mappings('', 'all', '', 1, 100)
        self.assertEqual(baseline['rows'], current['rows'])
        self.assertEqual(baseline['pagination'], current['pagination'])
        self.cursor.execute('SELECT COUNT(DISTINCT snapshot_id) AS n FROM ads.ads_product_code_mapping_workbench')
        self.assertEqual(self.cursor.fetchone()['n'], 2)

    def test_readers_see_old_complete_result_while_new_version_is_uncommitted(self):
        old = self.current_snapshot()
        publish_workbench(self.cursor)
        reader = self.psycopg2.connect(**self.connect_kwargs)
        try:
            with reader.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '500ms'")
                cursor.execute("""SELECT summary->>'snapshot_id',
                    (SELECT COUNT(*) FROM ads.ads_product_code_mapping_workbench a
                     WHERE a.snapshot_id=(summary->>'snapshot_id')::UUID)
                    FROM ops.refresh_watermark WHERE watermark_key='product_code_mapping'""")
                snapshot_id, count = cursor.fetchone()
                self.assertEqual(snapshot_id, old)
                self.assertGreater(count, 0)
        finally:
            reader.rollback()
            reader.close()

    def test_failed_transaction_keeps_previous_published_version(self):
        old = self.current_snapshot()
        self.cursor.execute('SAVEPOINT failed_publish')
        publish_workbench(self.cursor)
        with self.assertRaises(self.psycopg2.Error):
            self.cursor.execute('SELECT 1/0')
        self.cursor.execute('ROLLBACK TO SAVEPOINT failed_publish')
        self.assertEqual(self.current_snapshot(), old)

    def test_configuration_change_is_durable_and_full_refresh_acknowledges_it(self):
        self.cursor.execute("SELECT requested_revision FROM ops.product_mapping_refresh_state WHERE state_key='product_mapping'")
        before = self.cursor.fetchone()['requested_revision']
        self.cursor.execute("""UPDATE dim.dim_company_product_code_mapping SET updated_at=updated_at
            WHERE mapping_id=(SELECT MIN(mapping_id) FROM dim.dim_company_product_code_mapping)""")
        self.assertTrue(self.service._has_pending_refresh())
        self.cursor.execute("SELECT requested_revision FROM ops.product_mapping_refresh_state WHERE state_key='product_mapping'")
        self.assertGreater(self.cursor.fetchone()['requested_revision'], before)
        result = self.service._refresh_dashboard_transaction()
        self.assertTrue(result['refreshed'])
        self.assertFalse(self.service._has_pending_refresh())
        self.assertEqual(result['workbench']['total'], self.service.list_mappings('', 'all', '', 1, 100)['pagination']['total'])

    def test_configuration_waits_for_domain_lock_before_locking_dimension_rows(self):
        errors = []
        finished = threading.Event()

        def writer():
            service = ProductCategoryService.__new__(ProductCategoryService)
            service.connect_kwargs = dict(self.connect_kwargs, options='-c lock_timeout=200ms')
            try:
                with service.configuration_transaction() as cursor:
                    cursor.execute('SELECT * FROM dim.dim_company_product_code_mapping FOR UPDATE')
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        self.assertTrue(finished.wait(3))
        thread.join(1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], self.psycopg2.errors.LockNotAvailable)
        # A waiting configuration writer must not own any DIM row lock.
        self.cursor.execute('SELECT * FROM dim.dim_company_product_code_mapping FOR UPDATE NOWAIT')

    def test_new_tables_have_complete_business_comments(self):
        for relation in ('ads.ads_product_code_mapping_workbench', 'ops.product_mapping_refresh_state'):
            self.cursor.execute("""SELECT OBJ_DESCRIPTION(%s::regclass) AS table_comment,
                COUNT(*) FILTER (WHERE COL_DESCRIPTION(a.attrelid, a.attnum) IS NULL) AS missing
                FROM pg_attribute a WHERE a.attrelid=%s::regclass AND a.attnum>0 AND NOT a.attisdropped""",
                (relation, relation))
            result = self.cursor.fetchone()
            self.assertTrue(result['table_comment'])
            self.assertEqual(result['missing'], 0)

    def test_search_platform_status_and_out_of_range_pages(self):
        all_rows = self.service.list_mappings('', 'all', '', 1, 100)
        unmatched = self.service.list_mappings('', 'unmapped', '', 1, 100)
        self.assertEqual(unmatched['pagination']['total'], all_rows['pagination']['unmapped_total'])
        self.assertTrue(all(row['mapping_status']=='unmapped' for row in unmatched['rows']))
        empty = self.service.list_mappings('no-match-integration-fixture', 'all', '', 1, 100)
        self.assertEqual(empty['rows'], [])
        self.assertEqual(empty['pagination']['total'], 0)
        self.assertEqual(self.service.list_mappings('', 'all', '', 9999, 10)['rows'], [])
        for platform in ('douyin', 'jd', 'ks', 'xhs', 'pdd', 'tmall', 'wechat_channels'):
            data = self.service.list_mappings('', 'all', platform, 1, 100)
            self.assertTrue(all(platform in row['observed_platform_codes'] for row in data['rows']))


if __name__ == '__main__':
    unittest.main()
