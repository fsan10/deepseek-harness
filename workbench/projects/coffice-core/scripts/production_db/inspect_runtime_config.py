"""Read-only inspection for configuration data required by the web console."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor

from db_connection import add_connection_arguments, connection_kwargs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="只读核对经营配置中心必需配置")
    add_connection_arguments(parser)
    return parser


def json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def fetch_all(cursor, query: str) -> list[dict]:
    cursor.execute(query)
    return [dict(row) for row in cursor.fetchall()]


def main() -> None:
    args = build_parser().parse_args()
    kwargs = connection_kwargs(args)
    connection = psycopg2.connect(
        **kwargs,
        application_name="coffice_runtime_config_inspection",
    )
    connection.set_session(readonly=True, autocommit=True)
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT current_database() AS database_name")
            database_name = cursor.fetchone()["database_name"]
            result = {
                "database_name": database_name,
                "business_owners": fetch_all(
                    cursor,
                    """
                    SELECT business_owner_id, business_owner_name, is_active
                    FROM dim.dim_business_owner
                    ORDER BY business_owner_id
                    """,
                ),
                "assignment_summary": fetch_all(
                    cursor,
                    """
                    SELECT effective_month, assignment_source, is_active, COUNT(*) AS row_count
                    FROM dim.dim_influencer_business_assignment_monthly
                    GROUP BY effective_month, assignment_source, is_active
                    ORDER BY effective_month, assignment_source, is_active
                    """,
                ),
                "target_rows": fetch_all(
                    cursor,
                    """
                    SELECT target.target_month, owner.business_owner_name,
                           target.gmv_target, target.note
                    FROM dim.dim_business_gmv_target_monthly target
                    JOIN dim.dim_business_owner owner
                      ON owner.business_owner_id = target.business_owner_id
                    ORDER BY target.target_month, owner.business_owner_name
                    """,
                ),
                "product_summary": fetch_all(
                    cursor,
                    """
                    SELECT
                        (SELECT COUNT(*) FROM dim.dim_influencer_product_category) AS categories,
                        (SELECT COUNT(*) FROM dim.dim_influencer_product_category WHERE is_active) AS active_categories,
                        (SELECT COUNT(*) FROM dim.dim_influencer_product) AS products,
                        (SELECT COUNT(*) FROM dim.dim_influencer_product WHERE is_active) AS active_products,
                        (SELECT COUNT(*) FROM dim.dim_company_product_code_mapping) AS mappings,
                        (SELECT COUNT(*) FROM dim.dim_company_product_code_mapping WHERE is_active) AS active_mappings,
                        (SELECT COUNT(*)
                           FROM dim.dim_influencer_product product
                           LEFT JOIN dim.dim_company_product_code_mapping mapping
                             ON mapping.product_id = product.product_id
                          WHERE mapping.product_id IS NULL) AS products_without_mapping
                    """,
                )[0],
                "product_source_summary": {
                    "categories": fetch_all(
                        cursor,
                        """
                        SELECT maintenance_source, is_active, COUNT(*) AS row_count
                        FROM dim.dim_influencer_product_category
                        GROUP BY maintenance_source, is_active
                        ORDER BY maintenance_source, is_active
                        """,
                    ),
                    "products": fetch_all(
                        cursor,
                        """
                        SELECT maintenance_source, is_active, COUNT(*) AS row_count
                        FROM dim.dim_influencer_product
                        GROUP BY maintenance_source, is_active
                        ORDER BY maintenance_source, is_active
                        """,
                    ),
                    "mappings": fetch_all(
                        cursor,
                        """
                        SELECT mapping_source, is_active, COUNT(*) AS row_count
                        FROM dim.dim_company_product_code_mapping
                        GROUP BY mapping_source, is_active
                        ORDER BY mapping_source, is_active
                        """,
                    ),
                },
            }
    finally:
        connection.close()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=json_default))


if __name__ == "__main__":
    main()
