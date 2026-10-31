"""Read performance guards and opt-in, read-only PostgreSQL equivalence checks."""
import json
import os
import unittest
from contextlib import contextmanager
from unittest.mock import Mock

from psycopg2.extras import RealDictCursor

from apps.file_ingest.service import FileIngestService, FEE_ODS_CANDIDATE_QUERIES


class FeeReadScopeTests(unittest.TestCase):
    def test_platform_filter_does_not_read_unrelated_ods_sources(self):
        service = object.__new__(FileIngestService)
        cursor = Mock()
        cursor.fetchall.return_value = []
        service._fee_candidates(cursor, platform_code='pdd')
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertEqual(2, len(statements))
        self.assertIn('WHERE platform_code=%s', statements[0])
        self.assertIn('ods_pdd_settlement_raw', statements[1])
        self.assertFalse(any('ods_tmall' in sql or 'ods_douyin' in sql for sql in statements))


@unittest.skipUnless(os.getenv('RUN_PAGE_READ_DB_TESTS') == '1', 'opt-in read-only database checks')
class FeeReadDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from apps.fund_split_adjust.server import load_project_env, build_parser
        load_project_env()
        cls.service = FileIngestService(build_parser().parse_args([]))
        cls.connection = cls.service.connect()
        cls.connection.set_session(readonly=True, isolation_level='REPEATABLE READ')

        @contextmanager
        def transaction():
            with cls.connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor
        cls.service.transaction = transaction

    @classmethod
    def tearDownClass(cls):
        cls.connection.rollback()
        cls.connection.close()

    def test_platform_scoping_preserves_all_rules_groups_and_unmapped_candidates(self):
        with self.service.transaction() as cursor:
            all_items = self.service._fee_candidates(cursor)
            canonical = lambda rows: sorted(json.dumps(row, default=str, sort_keys=True) for row in rows)
            for platform in FEE_ODS_CANDIDATE_QUERIES:
                with self.subTest(platform=platform):
                    expected = [row for row in all_items if row['platform_code'] == platform]
                    actual = self.service._fee_candidates(cursor, platform_code=platform)
                    self.assertEqual(canonical(expected), canonical(actual))

    def test_distinct_before_cleaning_preserves_descriptions_and_candidate_identity(self):
        with self.service.transaction() as cursor:
            for platform, raw in FEE_ODS_CANDIDATE_QUERIES.items():
                with self.subTest(platform=platform):
                    source = raw.replace('%', '%%')
                    columns = 'source_document_type,source_business_type,source_description,secondary_category_name'
                    original = f'''SELECT DISTINCT source_document_type,source_business_type,source_description,
                        dim.normalize_platform_scene(%s,source_document_type,secondary_category_name,source_business_type)
                        FROM ({source}) candidate({columns})
                        WHERE NULLIF(BTRIM(secondary_category_name),'') IS NOT NULL'''
                    optimized = f'''WITH candidates AS MATERIALIZED (
                        SELECT DISTINCT {columns} FROM ({source}) candidate({columns}))
                        SELECT DISTINCT source_document_type,source_business_type,source_description,
                        dim.normalize_platform_scene(%s,source_document_type,secondary_category_name,source_business_type)
                        FROM candidates WHERE NULLIF(BTRIM(secondary_category_name),'') IS NOT NULL'''
                    cursor.execute(original, (platform,))
                    expected = {tuple(row.values()) for row in cursor.fetchall()}
                    cursor.execute(optimized, (platform,))
                    self.assertEqual(expected, {tuple(row.values()) for row in cursor.fetchall()})


if __name__ == '__main__':
    unittest.main()
