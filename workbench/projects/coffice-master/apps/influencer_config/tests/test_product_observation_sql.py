"""Optional PostgreSQL regression: RUN_PRODUCT_OBSERVATION_DB_TESTS=1.

Uses connection-local temporary fixtures and rolls everything back.
"""
from __future__ import annotations

import os
import unittest
from decimal import Decimal
from pathlib import Path


@unittest.skipUnless(os.getenv("RUN_PRODUCT_OBSERVATION_DB_TESTS") == "1", "PostgreSQL fixture tests are opt-in")
class ProductObservationSqlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        from psycopg2.extras import RealDictCursor
        from apps.fund_split_adjust.server import build_parser, load_project_env

        load_project_env()  # Process-local .env; never prints credentials.
        args = build_parser().parse_args([])
        cls.connection = psycopg2.connect(host=args.host, port=args.pg_port,
            dbname=args.dbname, user=args.user, password=args.password)
        cls.addClassCleanup(cls.connection.close)
        cls.addClassCleanup(cls.connection.rollback)
        cls.cursor = cls.connection.cursor(cursor_factory=RealDictCursor)
        cls.addClassCleanup(cls.cursor.close)
        cls.cursor.execute("""
            CREATE TEMP TABLE observation_sources (
                product_mapping_id BIGINT, code_expression TEXT, quantity_position TEXT,
                merchant_code_component TEXT, platform_code TEXT, platform_name TEXT,
                shop_code TEXT, is_gift BOOLEAN, component_quantity NUMERIC,
                paid_quantity NUMERIC, gift_quantity NUMERIC,
                allocated_gmv_amount NUMERIC, stat_date DATE
            );
            CREATE TEMP TABLE observation_mapping (
                mapping_id BIGINT, alias_code TEXT, quantity_position TEXT,
                mapping_kind TEXT, code_pattern TEXT, product_id TEXT, is_active BOOLEAN
            );
            CREATE TEMP TABLE observation_product (
                product_id TEXT, company_product_code TEXT, product_type TEXT,
                category_id BIGINT, product_name TEXT, is_active BOOLEAN
            );
            CREATE TEMP TABLE observation_category (
                category_id BIGINT, category_name TEXT, parent_category_id BIGINT
            );
            INSERT INTO observation_category VALUES (1, 'L1', NULL), (2, 'L2', 1);
            INSERT INTO observation_product VALUES ('p', 'A', 'normal', 2, 'Product', TRUE);
            INSERT INTO observation_mapping VALUES
                (1, 'A', 'suffix', 'company_code', 'A-X', 'p', TRUE),
                (2, 'A', 'none', 'alias', 'A', 'p', TRUE),
                (3, 'OFF', 'none', 'alias', 'OFF', 'p', FALSE),
                (4, 'UNSEEN', 'prefix', 'alias', 'XUNSEEN', 'p', TRUE);
            INSERT INTO observation_sources VALUES
                (1, 'A', 'suffix', 'A-2', 'douyin', 'Douyin', 's1', FALSE, 2, 2, 0, 10.004, '2026-01-01'),
                (1, 'A', 'suffix', 'A-2', 'douyin', 'Douyin', 's1', FALSE, 2, 2, 0, 20.004, '2026-01-03'),
                (1, 'A', 'suffix', 'A-2', 'douyin', 'Douyin', 's1', TRUE, 2, 0, 2, 0, '2026-01-02'),
                (NULL, 'A', 'none', 'A', 'jd', 'JD', 's2', FALSE, 1, 1, 0, 5, '2026-01-04'),
                (NULL, 'OFF', 'none', 'OFF', 'jd', 'JD', 's2', FALSE, 1, 1, 0, 3, '2026-01-04'),
                (NULL, 'UNKNOWN', 'none', 'UNKNOWN', 'douyin', 'Douyin', 'same', FALSE, 1, 1, 0, 1.004, '2026-01-01'),
                (NULL, 'UNKNOWN', 'none', 'UNKNOWN', 'douyin', 'Douyin', 'same', TRUE, 1, 0, 1, 0, '2026-01-02'),
                (NULL, 'UNKNOWN', 'none', 'UNKNOWN', 'jd', 'JD', 'same', FALSE, 1, 1, 0, 2.004, '2026-01-05');
        """)
        path = Path(__file__).resolve().parents[3] / "sql/common/398_operating_sales_product_code_observation_view_postgres.sql"
        query = path.read_text(encoding="utf-8").split(" AS\n", 1)[1].split(";", 1)[0]
        # Route every platform to the fixture, with its original UNION ALL semantics.
        for platform in ("douyin", "wechat_channels", "jd", "ks", "xhs", "pdd", "tmall"):
            query = query.replace(f"dws.dws_{platform}_operating_sales_product_allocation",
                f"(SELECT * FROM pg_temp.observation_sources WHERE platform_code = '{platform}') fixture")
        for original, fixture in (
            ("dim.dim_company_product_code_mapping", "observation_mapping"),
            ("dim.dim_influencer_product_category", "observation_category"),
            ("dim.dim_influencer_product", "observation_product"),
        ):
            query = query.replace(original, "pg_temp." + fixture)
        cls.cursor.execute(query)
        cls.rows = list(cls.cursor.fetchall())

    def test_repeated_components_keep_counts_gifts_precision_and_dates(self):
        row = next(row for row in self.rows if row["mapping_id"] == 1)
        self.assertEqual(row["component_row_count"], 3)
        self.assertEqual(row["gift_component_row_count"], 1)
        self.assertEqual(row["parsed_quantity"], Decimal("6.00"))
        self.assertEqual(row["paid_quantity"], Decimal("4.00"))
        self.assertEqual(row["gift_quantity"], Decimal("2.00"))
        self.assertEqual(row["gmv_amount"], Decimal("30.01"))
        self.assertEqual(str(row["first_seen_date"]), "2026-01-01")
        self.assertEqual(str(row["last_seen_date"]), "2026-01-03")

    def test_unresolved_components_use_exact_quantity_rule_and_preserve_disabled(self):
        exact = next(row for row in self.rows if row["mapping_id"] == 2)
        disabled = next(row for row in self.rows if row["mapping_id"] == 3)
        unseen = next(row for row in self.rows if row["mapping_id"] == 4)
        self.assertEqual(exact["observed_source_codes"], ["A"])
        self.assertEqual(exact["gmv_amount"], Decimal("5.00"))
        self.assertEqual(disabled["mapping_status"], "inactive")
        self.assertEqual(disabled["component_row_count"], 1)
        self.assertEqual(unseen["component_row_count"], 0)
        self.assertEqual(unseen["gmv_amount"], 0)

    def test_unmapped_components_keep_platform_sets_and_distinct_shop_semantics(self):
        unmapped = [row for row in self.rows if row["mapping_status"] == "unmapped"]
        self.assertEqual(len(self.rows), 5)
        self.assertEqual(len(unmapped), 1)
        row = unmapped[0]
        self.assertEqual(row["component_row_count"], 3)
        self.assertEqual(row["gift_component_row_count"], 1)
        self.assertEqual(row["shop_count"], 1)
        self.assertEqual(row["observed_platform_codes"], ["douyin", "jd"])
        self.assertEqual(row["gmv_amount"], Decimal("3.01"))


if __name__ == "__main__":
    unittest.main()
