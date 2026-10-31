"""真实测试库上的公司商品与公司达人配置冒烟验收。

测试只写入带随机标识的DIM配置，finally中按外键反向硬删除；不修改ODS。
"""
from __future__ import annotations

import argparse
import os
import uuid
from datetime import date

import psycopg2

from apps.influencer_config.influencer_master import (
    InfluencerMasterConflictError,
    InfluencerMasterService,
)
from apps.influencer_config.product_category import (
    ProductCategoryConflictError,
    ProductCategoryService,
)


def database_args() -> argparse.Namespace:
    return argparse.Namespace(
        host=os.getenv("PGHOST", "192.168.77.111"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "mock_coffice"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD"),
    )


def scalar(cursor, query: str, params: tuple = ()):  # noqa: ANN001
    cursor.execute(query, params)
    return cursor.fetchone()[0]


def main() -> None:
    args = database_args()
    token = uuid.uuid4().hex[:12].upper()
    product_ids = [f"PRD-SMOKE-A-{token}", f"PRD-SMOKE-B-{token}"]
    source_ids = [f"smoke-source-a-{token}", f"smoke-source-b-{token}"]
    mapping_ids: list[int] = []
    company_ids: list[int] = []
    product_service = ProductCategoryService(args)
    # CRUD测试验证数据库写入本身；显式调用一次全链路刷新，避免每个动作重复刷新。
    product_service._queue_dashboard_refresh = lambda result, reason: result  # type: ignore[method-assign]
    influencer_service = InfluencerMasterService(args, refresh_request=None)
    connection = psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        user=args.user,
        password=args.password,
        application_name="company_master_smoke_test",
    )
    try:
        with connection.cursor() as cursor:
            category_id = scalar(
                cursor,
                """
                SELECT category_id
                FROM dim.dim_influencer_product_category
                WHERE category_level = 2 AND is_active
                ORDER BY category_id
                LIMIT 1
                """,
            )
            cursor.execute(
                """
                SELECT business_owner_id
                FROM dim.dim_business_owner
                WHERE is_active
                ORDER BY business_owner_id
                LIMIT 2
                """
            )
            owner_ids = [row[0] for row in cursor.fetchall()]
            assert category_id is not None, "缺少启用的二级分类"
            assert len(owner_ids) == 2, "商务归属冲突测试至少需要两个启用商务"
            gmv_before = scalar(
                cursor,
                "SELECT COALESCE(SUM(gmv_amount), 0) FROM ads.ads_operating_sales_product_company_shop_daily",
            )
            unmapped_before = scalar(
                cursor,
                """
                SELECT COALESCE(SUM(gmv_amount), 0)
                FROM ads.ads_operating_sales_product_company_shop_daily
                WHERE product_name = '未配置'
                """,
            )
        connection.commit()

        for product_id, suffix in zip(product_ids, ("A", "B"), strict=True):
            product_service.create_product(
                {
                    "product_id": product_id,
                    "product_name": f"冒烟公司商品{suffix}-{token}",
                    "category_id": category_id,
                }
            )

        code_a = f"中文 code / {token} ? # 1"
        code_b = f"SKU::{token}::B"
        for platform, code in (("douyin", code_a), ("douyin", code_b), ("tmall", code_a)):
            row = product_service.create_mapping(
                {
                    "product_id": product_ids[0],
                    "platform_code": platform,
                    "source_product_code": code,
                }
            )
            mapping_ids.append(int(row["mapping_id"]))

        product_rows = product_service.list_mappings(
            token, "active", None, page=1, page_size=10
        )["rows"]
        assert len(product_rows) == 3, product_rows
        assert len({row["product_id"] for row in product_rows}) == 1
        assert {row["platform_code"] for row in product_rows} == {"douyin", "tmall"}

        try:
            product_service.batch_map_source_codes(
                {
                    "product_id": product_ids[1],
                    "items": [{"platform_code": "douyin", "source_product_code": code_a}],
                }
            )
            raise AssertionError("编码改配未要求明确确认")
        except ProductCategoryConflictError as exc:
            assert exc.details and len(exc.details.get("conflicts", [])) == 1

        refresh_result = product_service._refresh_dashboard_now()
        assert refresh_result["refreshed"] is True, refresh_result
        with connection.cursor() as cursor:
            gmv_after = scalar(
                cursor,
                "SELECT COALESCE(SUM(gmv_amount), 0) FROM ads.ads_operating_sales_product_company_shop_daily",
            )
            unmapped_after = scalar(
                cursor,
                """
                SELECT COALESCE(SUM(gmv_amount), 0)
                FROM ads.ads_operating_sales_product_company_shop_daily
                WHERE product_name = '未配置'
                """,
            )
        connection.commit()
        assert gmv_after == gmv_before, (gmv_before, gmv_after)
        assert unmapped_before > 0 and unmapped_after == unmapped_before

        for suffix in ("A", "B"):
            row = influencer_service.create_company_influencer(
                {
                    "company_influencer_name": f"冒烟公司达人{suffix}-{token}",
                    "note": "自动化测试，结束后硬删除",
                }
            )
            company_ids.append(int(row["company_influencer_id"]))

        influencer_service.save_source_mappings(
            {
                "company_influencer_id": company_ids[0],
                "items": [
                    {
                        "platform_code": "douyin",
                        "source_influencer_id": source_ids[0],
                        "source_influencer_name": f"平台昵称A-{token}",
                    },
                    {
                        "platform_code": "tmall",
                        "source_influencer_id": source_ids[1],
                        "source_influencer_name": f"平台昵称B-{token}",
                    },
                ],
            }
        )
        test_month = date(2099, 1, 1)
        influencer_service.save_assignment(
            {
                "company_influencer_id": company_ids[0],
                "business_owner_id": owner_ids[0],
            },
            test_month,
        )
        influencer_service.save_assignment(
            {
                "company_influencer_id": company_ids[1],
                "business_owner_id": owner_ids[1],
            },
            test_month,
        )
        move_payload = {
            "company_influencer_id": company_ids[1],
            "items": [
                {
                    "platform_code": "douyin",
                    "source_influencer_id": source_ids[0],
                    "source_influencer_name": f"改名后的平台昵称-{token}",
                }
            ],
        }
        try:
            influencer_service.save_source_mappings(move_payload)
            raise AssertionError("达人合并未要求明确确认")
        except InfluencerMasterConflictError as exc:
            assert exc.details and len(exc.details.get("moves", [])) == 1
        try:
            influencer_service.save_source_mappings({**move_payload, "confirm_move": True})
            raise AssertionError("同月商务冲突未要求明确选择")
        except InfluencerMasterConflictError as exc:
            assert exc.details and len(exc.details.get("assignment_conflicts", [])) == 1
        influencer_service.save_source_mappings(
            {**move_payload, "confirm_move": True, "assignment_resolution": "use_source"}
        )

        with connection.cursor() as cursor:
            resolved_owner = scalar(
                cursor,
                """
                SELECT business_owner_id
                FROM dim.dim_company_influencer_business_assignment_monthly
                WHERE company_influencer_id = %s AND effective_month = %s
                """,
                (company_ids[1], test_month),
            )
            source_target = scalar(
                cursor,
                """
                SELECT company_influencer_id
                FROM dim.dim_company_influencer_source_mapping
                WHERE platform_code = 'douyin' AND source_influencer_id = %s
                """,
                (source_ids[0],),
            )
            identity_errors = scalar(
                cursor,
                """
                SELECT COUNT(*)
                FROM dws.v_influencer_identity_resolved
                WHERE influencer_identity_key <> CASE
                    WHEN company_influencer_id IS NOT NULL
                    THEN 'company:' || company_influencer_id::text
                    ELSE 'source:' || platform_code || ':' || source_influencer_id
                END
                """,
            )
            daily_duplicates = scalar(
                cursor,
                """
                SELECT COUNT(*)
                FROM (
                    SELECT stat_date, platform_code, company_code, shop_code,
                           influencer_identity_key
                    FROM ads.ads_influencer_company_shop_daily
                    GROUP BY stat_date, platform_code, company_code, shop_code,
                             influencer_identity_key
                    HAVING COUNT(*) > 1
                ) duplicate_rows
                """,
            )
            monthly_duplicates = scalar(
                cursor,
                """
                SELECT COUNT(*)
                FROM (
                    SELECT stat_month, platform_code, company_code, shop_code,
                           influencer_identity_key
                    FROM ads.ads_influencer_company_shop_monthly_ranking
                    GROUP BY stat_month, platform_code, company_code, shop_code,
                             influencer_identity_key
                    HAVING COUNT(*) > 1
                ) duplicate_rows
                """,
            )
            missing_comments = scalar(
                cursor,
                """
                WITH targets(relation_name) AS (
                    VALUES
                        ('dim.dim_company_product_code_mapping'::regclass),
                        ('dim.dim_company_influencer'::regclass),
                        ('dim.dim_company_influencer_source_mapping'::regclass),
                        ('dim.dim_company_influencer_business_assignment_monthly'::regclass),
                        ('dws.v_influencer_identity_resolved'::regclass),
                        ('common.v_operating_sales_product_code_observation'::regclass),
                        ('ads.ads_influencer_company_shop_daily'::regclass),
                        ('ads.ads_influencer_company_shop_monthly_ranking'::regclass)
                ), missing AS (
                    SELECT relation_name::text AS object_name
                    FROM targets
                    WHERE OBJ_DESCRIPTION(relation_name, 'pg_class') IS NULL
                    UNION ALL
                    SELECT relation_name::text || '.' || attribute.attname
                    FROM targets
                    JOIN pg_attribute attribute
                      ON attribute.attrelid = relation_name
                     AND attribute.attnum > 0
                     AND NOT attribute.attisdropped
                    WHERE COL_DESCRIPTION(relation_name, attribute.attnum) IS NULL
                )
                SELECT COUNT(*) FROM missing
                """,
            )
        connection.commit()
        assert resolved_owner == owner_ids[0]
        assert source_target == company_ids[1]
        assert identity_errors == daily_duplicates == monthly_duplicates == 0
        assert missing_comments == 0
        print(
            {
                "database": args.dbname,
                "product_multi_code": "passed",
                "unmapped_gmv_preserved": str(unmapped_after),
                "total_gmv_unchanged": str(gmv_after),
                "influencer_merge_conflict": "passed",
                "stable_identity_duplicates": [daily_duplicates, monthly_duplicates],
                "missing_object_or_column_comments": missing_comments,
            }
        )
    finally:
        connection.rollback()
        with connection.cursor() as cursor:
            if company_ids:
                cursor.execute(
                    "DELETE FROM dim.dim_company_influencer_business_assignment_monthly WHERE company_influencer_id = ANY(%s)",
                    (company_ids,),
                )
                cursor.execute(
                    "DELETE FROM dim.dim_company_influencer_source_mapping WHERE company_influencer_id = ANY(%s)",
                    (company_ids,),
                )
                cursor.execute(
                    "DELETE FROM dim.dim_company_influencer WHERE company_influencer_id = ANY(%s)",
                    (company_ids,),
                )
            if mapping_ids:
                cursor.execute(
                    "DELETE FROM dim.dim_company_product_code_mapping WHERE mapping_id = ANY(%s)",
                    (mapping_ids,),
                )
            cursor.execute(
                "DELETE FROM dim.dim_company_product_code_mapping WHERE product_id = ANY(%s)",
                (product_ids,),
            )
            cursor.execute(
                "DELETE FROM dim.dim_influencer_product WHERE product_id = ANY(%s)",
                (product_ids,),
            )
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM dim.dim_company_influencer
                     WHERE company_influencer_id = ANY(%s))
                  + (SELECT COUNT(*) FROM dim.dim_company_influencer_source_mapping
                     WHERE source_influencer_id = ANY(%s))
                  + (SELECT COUNT(*) FROM dim.dim_influencer_product
                     WHERE product_id = ANY(%s))
                  + (SELECT COUNT(*) FROM dim.dim_company_product_code_mapping
                     WHERE product_id = ANY(%s))
                """,
                (company_ids or [-1], source_ids, product_ids, product_ids),
            )
            assert cursor.fetchone()[0] == 0, "冒烟测试DIM数据未完全硬删除"
        connection.commit()
        connection.close()
        product_service.close(drain=False, timeout=2)


if __name__ == "__main__":
    main()
