#!/usr/bin/env python
"""商品分类配置CRUD与看板刷新冒烟测试；测试数据完成后会硬删除。"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from apps.influencer_config.product_category import ProductCategoryService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="商品分类配置CRUD冒烟测试")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    service = ProductCategoryService(args)
    with service.transaction() as cursor:
        cursor.execute(
            """
            DELETE FROM dim.dim_company_product_code_mapping
            WHERE product_id IN (
                SELECT product_id FROM dim.dim_influencer_product
                WHERE product_name LIKE 'CRUD产品%'
            )
            """
        )
        cursor.execute(
            "DELETE FROM dim.dim_influencer_product WHERE product_name LIKE 'CRUD产品%'"
        )
        cursor.execute(
            "DELETE FROM dim.dim_influencer_product_category WHERE category_level = 2 AND category_name LIKE 'CRUD二级%'"
        )
        cursor.execute(
            "DELETE FROM dim.dim_influencer_product_category WHERE category_level = 1 AND category_name LIKE 'CRUD一级%'"
        )
    suffix = str(int(time.time() * 1000))
    l1_id = None
    l2_id = None
    mapping_id = None
    product_id = None
    deleted_catalog = False
    deleted_l2 = False
    deleted_l1 = False
    mutation_durations: list[float] = []

    def mutate(callback, *values):
        started = time.perf_counter()
        result = callback(*values)
        mutation_durations.append(time.perf_counter() - started)
        return result

    try:
        l1 = mutate(service.create_category, {
            "category_level": 1,
            "category_name": f"CRUD一级-{suffix}",
        })
        l1_id = int(l1["category_id"])
        l2 = mutate(service.create_category, {
            "category_level": 2,
            "parent_category_id": l1_id,
            "category_name": f"CRUD二级-{suffix}",
        })
        l2_id = int(l2["category_id"])
        updated_l1 = mutate(service.update_category, l1_id, {
            "category_name": f"CRUD一级已改-{suffix}",
        })
        catalog_row = mutate(service.create_catalog_row, {
            "category_l2_id": l2_id,
            "product_name": f"CRUD产品-{suffix}",
            "code_pattern": f"CRUD-TEST-{suffix}",
            "match_rule": "exact",
            "code_role": "box",
        })
        mapping_id = int(catalog_row["mapping_id"])
        product_id = catalog_row["product_id"]
        updated_mapping = mutate(service.update_catalog_row, mapping_id, {
            "category_l1_id": l1_id,
            "category_l2_id": l2_id,
            "product_name": f"CRUD产品已改-{suffix}",
            "code_pattern": f"CRUD-TESTX-{suffix}",
            "match_rule": "exact",
            "code_role": "sachet",
        })
        catalog = service.list_catalog(f"CRUD产品已改-{suffix}", "all", 1, 10)
        assert catalog["pagination"]["total"] == 2
        row = next(
            item for item in catalog["rows"]
            if item["mapping_id"] == updated_mapping["mapping_id"]
        )
        assert row["category_l1_name"] == updated_l1["category_name"]
        assert row["product_name"] == f"CRUD产品已改-{suffix}"
        assert row["merchant_code"] == updated_mapping["code_pattern"]
        assert any(
            item["mapping_id"] == mapping_id for item in catalog["rows"]
        ), "公司商品编码修改后必须保留原编码为历史别名"

        mutate(service.set_catalog_row_status, mapping_id, False)
        mutate(service.set_catalog_row_status, mapping_id, True)
        assert service.wait_for_refresh(120), "看板后台刷新未在120秒内完成"
        mutate(service.delete_catalog_row, mapping_id)
        deleted_catalog = True
        mutate(service.delete_category, l2_id)
        deleted_l2 = True
        mutate(service.delete_category, l1_id)
        deleted_l1 = True
        assert service.wait_for_refresh(120), "看板后台刷新未在120秒内完成"
        refresh = service.refresh_status()
        assert refresh["status"] == "succeeded", refresh
        slowest = max(mutation_durations)
        assert slowest < 2.0, f"最慢配置写操作耗时 {slowest:.3f}s，未达到即时反馈目标"
        print("CRUD_OK")
        print(f"一级分类={l1_id}，二级分类={l2_id}，产品={product_id}，编码映射={mapping_id}")
        print(f"配置写操作最大耗时={slowest:.3f}s，看板后台刷新耗时={refresh['duration_seconds']}s")
        print("分页查询、联表新增、行内修改、停用/启用、永久删除、看板刷新均通过")
    finally:
        service.close(drain=True, timeout=120)
        with service.transaction() as cursor:
            if product_id is not None and not deleted_catalog:
                cursor.execute(
                    "DELETE FROM dim.dim_company_product_code_mapping WHERE product_id = %s",
                    (product_id,),
                )
            if product_id is not None and not deleted_catalog:
                cursor.execute(
                    "DELETE FROM dim.dim_influencer_product WHERE product_id = %s",
                    (product_id,),
                )
            if l2_id is not None and not deleted_l2:
                cursor.execute(
                    "DELETE FROM dim.dim_influencer_product_category WHERE category_id = %s",
                    (l2_id,),
                )
            if l1_id is not None and not deleted_l1:
                cursor.execute(
                    "DELETE FROM dim.dim_influencer_product_category WHERE category_id = %s",
                    (l1_id,),
                )
        print("CLEANUP_OK")


if __name__ == "__main__":
    main()
