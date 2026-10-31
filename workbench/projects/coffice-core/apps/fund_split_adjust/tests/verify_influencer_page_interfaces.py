"""只读验证统一配置中心的达播运营页面接口。"""
from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus

from apps.fund_split_adjust.influencer_module import InfluencerModule


def main() -> None:
    args = argparse.Namespace(
        host=os.getenv("PGHOST", "192.168.77.111"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "mock_coffice"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD"),
    )
    module = InfluencerModule(args)
    routes = {
        "company_influencers": (
            "/api/influencer/company-influencers",
            "page=1&page_size=10&status=all&platform=douyin",
        ),
        "influencer_source_accounts": (
            "/api/influencer/influencer-source-accounts",
            "page=1&page_size=10&mapping_status=all&platform=douyin&gmv_min=0.01",
        ),
        "company_assignments": (
            "/api/influencer/company-influencer-assignments",
            "month=2026-08&page=1&page_size=10&platform=douyin",
        ),
        "company_products": (
            "/api/influencer/products",
            "page=1&page_size=10&status=all",
        ),
        "product_mappings": (
            "/api/influencer/product-mappings",
            "page=1&page_size=10&status=all",
        ),
        "product_source_codes": (
            "/api/influencer/product-source-codes",
            "page=1&page_size=10&mapping_status=all",
        ),
        "category_l1": (
            "/api/influencer/product-category-list",
            "level=1&page=1&page_size=10&status=all",
        ),
        "category_l2": (
            "/api/influencer/product-category-list",
            "level=2&page=1&page_size=10&status=all",
        ),
    }
    totals: dict[str, int] = {}
    try:
        for name, (path, query) in routes.items():
            response = module.dispatch("GET", path, query)
            assert response is not None, f"{path} 未被统一挂载层接管"
            data, status = response
            assert status == HTTPStatus.OK, f"{path} 返回 {status}"
            pagination = data.get("pagination") or {}
            assert {"page", "page_size", "total", "total_pages"} <= pagination.keys(), (
                f"{path} 分页字段不完整：{pagination}"
            )
            totals[name] = int(pagination["total"])
    finally:
        module.close(drain=False, timeout=2)
    print(json.dumps({"database": args.dbname, "interfaces": totals}, ensure_ascii=False))


if __name__ == "__main__":
    main()
