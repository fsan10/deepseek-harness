"""达播运营配置台在统一配置中心中的挂载适配层。

本文件只负责 URL 与独立达播模块之间的映射。达人业务、SQL 调用、前端页面
仍全部位于 ``apps.influencer_config``，避免与银行资金配置代码耦合。
"""
from __future__ import annotations

import argparse
import re
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, unquote

from apps.influencer_config.influencer_master import InfluencerMasterService
from apps.influencer_config.product_category import ProductCategoryService
from apps.influencer_config.server import Database as InfluencerDatabase
from apps.influencer_config.server import parse_month


class InfluencerModule:
    """向统一 HTTP 服务暴露达播运营模块的静态资源和 API。"""

    page_prefix = "/influencer"
    api_prefix = "/api/influencer"
    static_dir = Path(__file__).resolve().parents[1] / "influencer_config" / "static"

    def __init__(
        self,
        args: argparse.Namespace,
        database=None,
        product_categories=None,
        influencer_master=None,
    ):
        self.database = database or InfluencerDatabase(args)
        self.product_categories = product_categories or ProductCategoryService(args)
        self.influencer_master = influencer_master or InfluencerMasterService(
            args,
            refresh_request=self.database.request_metrics_refresh,
        )

    def migrate(self) -> str:
        return f"{self.product_categories.migrate()}\n{self.influencer_master.migrate()}"

    def close(self, *, drain: bool = True, timeout: float = 30.0) -> bool:
        database_closed = self.database.close(drain=drain, timeout=timeout)
        product_closed = self.product_categories.close(drain=drain, timeout=timeout)
        return database_closed and product_closed

    def static_file(self, request_path: str) -> Path | None:
        """解析达播模块静态文件；越界路径和非本模块路径均返回 ``None``。"""
        if request_path == f"{self.page_prefix}/":
            relative = "index.html"
        elif request_path.startswith(f"{self.page_prefix}/"):
            relative = request_path[len(self.page_prefix) + 1 :] or "index.html"
        else:
            return None

        root = self.static_dir.resolve()
        target = (root / relative).resolve()
        if target != root and root not in target.parents:
            return None
        if not target.is_file():
            target = root / "index.html"
        return target

    def dispatch(self, method: str, request_path: str, query_string: str, payload: dict | None = None):
        """执行达播 API，返回 ``(响应数据, HTTP 状态)``。"""
        if not request_path.startswith(f"{self.api_prefix}/"):
            return None

        route = request_path[len(self.api_prefix) :]
        query = parse_qs(query_string)
        payload = payload or {}

        if method == "GET" and route == "/health":
            health = self.database.health()
            health.update(self.product_categories.health())
            health.update(self.influencer_master.health())
            return health, HTTPStatus.OK
        if method == "GET" and route == "/refresh-status":
            return {
                "metrics": self.database.refresh_status(),
                "product_dashboard": self.product_categories.refresh_status(),
            }, HTTPStatus.OK
        if method == "GET" and route == "/businesses":
            return self.database.list_businesses(), HTTPStatus.OK
        if method == "GET" and route == "/company-influencers":
            return self.influencer_master.list_company_influencers(
                query.get("search", [""])[0],
                query.get("status", ["all"])[0],
                int(query.get("page", ["1"])[0]),
                int(query.get("page_size", ["10"])[0]),
                query.get("platform", [""])[0],
            ), HTTPStatus.OK
        if method == "GET" and route == "/influencer-source-accounts":
            return self.influencer_master.list_source_accounts(
                query.get("search", [""])[0],
                query.get("mapping_status", ["all"])[0],
                query.get("platform", [""])[0],
                int(query.get("page", ["1"])[0]),
                int(query.get("page_size", ["10"])[0]),
                query.get("gmv_min", [""])[0],
            ), HTTPStatus.OK
        if method == "GET" and route == "/company-influencer-assignments":
            owner_value = query.get("business_owner_id", [""])[0].strip()
            return self.influencer_master.list_assignments(
                parse_month(query.get("month", [""])[0]),
                query.get("search", [""])[0],
                int(owner_value) if owner_value else None,
                int(query.get("page", ["1"])[0]),
                int(query.get("page_size", ["10"])[0]),
                query.get("platform", [""])[0],
            ), HTTPStatus.OK
        if method == "GET" and route == "/influencers":
            month = parse_month(query.get("month", [""])[0])
            platform = query.get("platform", [""])[0].strip() or None
            owner_value = query.get("business_owner_id", [""])[0].strip()
            owner_id = int(owner_value) if owner_value else None
            status = query.get("status", [""])[0].strip() or None
            active_status = query.get("active_status", [""])[0].strip() or None
            search = query.get("search", [""])[0].strip() or None
            page = int(query.get("page", ["1"])[0])
            page_size = int(query.get("page_size", ["10"])[0])
            return self.database.list_influencers(
                month, platform, owner_id, status, search, page, page_size, active_status
            ), HTTPStatus.OK
        if method == "GET" and route == "/targets":
            month = parse_month(query.get("month", [""])[0])
            return self.database.list_targets(month), HTTPStatus.OK
        if method == "GET" and route == "/product-categories":
            return self.product_categories.list_categories(), HTTPStatus.OK
        if method == "GET" and route == "/product-catalog":
            return self.product_categories.list_catalog(
                query.get("search", [""])[0],
                query.get("status", ["all"])[0],
                int(query.get("page", ["1"])[0]),
                int(query.get("page_size", ["10"])[0]),
            ), HTTPStatus.OK
        if method == "GET" and route == "/product-category-list":
            return self.product_categories.list_category_page(
                int(query.get("level", ["1"])[0]),
                query.get("search", [""])[0],
                query.get("status", ["all"])[0],
                int(query.get("page", ["1"])[0]),
                int(query.get("page_size", ["10"])[0]),
            ), HTTPStatus.OK
        if method == "GET" and route == "/products":
            category_value = query.get("category_id", [""])[0].strip()
            return self.product_categories.list_products(
                int(category_value) if category_value else None,
                query.get("search", [""])[0],
                int(query.get("page", ["1"])[0]),
                int(query.get("page_size", ["10"])[0]),
                query.get("status", ["all"])[0],
            ), HTTPStatus.OK
        if method == "GET" and route == "/product-mappings":
            return self.product_categories.list_mappings(
                query.get("search", [""])[0],
                query.get("status", ["all"])[0],
                query.get("platform", [""])[0],
                int(query.get("page", ["1"])[0]),
                int(query.get("page_size", ["10"])[0]),
            ), HTTPStatus.OK
        if method == "GET" and route == "/product-code-normalizations":
            return self.product_categories.list_normalization_rules(
                query.get("search", [""])[0],
                query.get("status", ["all"])[0],
                int(query.get("page", ["1"])[0]),
                int(query.get("page_size", ["10"])[0]),
            ), HTTPStatus.OK
        if method == "GET" and route == "/product-source-codes":
            return self.product_categories.list_source_codes(
                query.get("search", [""])[0],
                query.get("mapping_status", ["all"])[0],
                query.get("platform", [""])[0],
                int(query.get("page", ["1"])[0]),
                int(query.get("page_size", ["10"])[0]),
            ), HTTPStatus.OK
        product_list_match = re.fullmatch(r"/product-categories/(\d+)/products", route)
        if method == "GET" and product_list_match:
            return self.product_categories.list_products(
                int(product_list_match.group(1)),
                query.get("search", [""])[0],
                int(query.get("page", ["1"])[0]),
                int(query.get("page_size", ["10"])[0]),
            ), HTTPStatus.OK

        if method == "POST" and route == "/businesses":
            return self.database.create_business(payload.get("business_owner_name", "")), HTTPStatus.CREATED
        if method == "POST" and route == "/company-influencers":
            return self.influencer_master.create_company_influencer(payload), HTTPStatus.CREATED
        if method == "POST" and route in (
            "/influencer-source-mappings",
            "/influencer-source-mappings/batch",
        ):
            return self.influencer_master.save_source_mappings(payload), HTTPStatus.OK
        if method == "POST" and route == "/company-influencer-assignments":
            return self.influencer_master.save_assignment(
                payload,
                parse_month(str(payload.get("effective_month") or "")),
            ), HTTPStatus.OK
        if method == "POST" and route == "/influencers/toggle-status":
            return self.database.toggle_influencer_status(
                str(payload.get("platform_code") or "").strip(),
                str(payload.get("influencer_id") or "").strip(),
                parse_month(str(payload.get("effective_month") or "")),
                payload.get("is_active"),
            ), HTTPStatus.OK
        if method == "POST" and route == "/assignments":
            return self.database.save_assignment(payload), HTTPStatus.OK
        if method == "POST" and route == "/targets":
            return self.database.save_target(payload), HTTPStatus.OK
        if method == "POST" and route == "/product-categories":
            return self.product_categories.create_category(payload), HTTPStatus.CREATED
        if method == "POST" and route == "/product-catalog":
            return self.product_categories.create_catalog_row(payload), HTTPStatus.CREATED
        if method == "POST" and route == "/products":
            return self.product_categories.create_product(payload), HTTPStatus.CREATED
        if method == "POST" and route == "/product-mappings":
            return self.product_categories.create_mapping(payload), HTTPStatus.CREATED
        if method == "POST" and route == "/product-mappings/batch":
            return self.product_categories.batch_map_source_codes(payload), HTTPStatus.OK
        if method == "POST" and route == "/product-mappings/refresh":
            return self.product_categories.retry_refresh(), HTTPStatus.OK
        if method == "POST" and route == "/product-code-normalizations":
            return self.product_categories.create_normalization_rule(payload), HTTPStatus.CREATED

        category_match = re.fullmatch(r"/product-categories/(\d+)", route)
        category_status_match = re.fullmatch(r"/product-categories/(\d+)/status", route)
        business_match = re.fullmatch(r"/businesses/(\d+)", route)
        product_match = re.fullmatch(r"/products/([^/]+)", route)
        product_status_match = re.fullmatch(r"/products/([^/]+)/status", route)
        mapping_match = re.fullmatch(r"/product-mappings/(\d+)", route)
        mapping_status_match = re.fullmatch(r"/product-mappings/(\d+)/status", route)
        normalization_match = re.fullmatch(r"/product-code-normalizations/(\d+)", route)
        normalization_status_match = re.fullmatch(
            r"/product-code-normalizations/(\d+)/status", route
        )
        company_influencer_match = re.fullmatch(r"/company-influencers/(\d+)", route)
        company_influencer_status_match = re.fullmatch(
            r"/company-influencers/(\d+)/status", route
        )
        influencer_mapping_match = re.fullmatch(
            r"/influencer-source-mappings/(\d+)", route
        )
        influencer_mapping_status_match = re.fullmatch(
            r"/influencer-source-mappings/(\d+)/status", route
        )
        company_assignment_match = re.fullmatch(
            r"/company-influencer-assignments/(\d+)/(\d{4}-\d{2})", route
        )
        catalog_match = re.fullmatch(r"/product-catalog/(\d+)", route)
        catalog_status_match = re.fullmatch(r"/product-catalog/(\d+)/status", route)
        if method == "PUT" and company_influencer_status_match:
            return self.influencer_master.set_company_influencer_status(
                int(company_influencer_status_match.group(1)), payload.get("is_active")
            ), HTTPStatus.OK
        if method == "PUT" and company_influencer_match:
            return self.influencer_master.update_company_influencer(
                int(company_influencer_match.group(1)), payload
            ), HTTPStatus.OK
        if method == "PUT" and influencer_mapping_status_match:
            return self.influencer_master.set_source_mapping_status(
                int(influencer_mapping_status_match.group(1)), payload.get("is_active")
            ), HTTPStatus.OK
        if method == "PUT" and business_match:
            return self.database.update_business(
                int(business_match.group(1)), payload.get("business_owner_name", "")
            ), HTTPStatus.OK
        if method == "PUT" and category_match:
            return self.product_categories.update_category(int(category_match.group(1)), payload), HTTPStatus.OK
        if method == "PUT" and category_status_match:
            return self.product_categories.set_category_status(
                int(category_status_match.group(1)), payload.get("is_active")
            ), HTTPStatus.OK
        if method == "PUT" and product_match:
            return self.product_categories.update_product(unquote(product_match.group(1)), payload), HTTPStatus.OK
        if method == "PUT" and product_status_match:
            return self.product_categories.set_product_status(
                unquote(product_status_match.group(1)), payload.get("is_active")
            ), HTTPStatus.OK
        if method == "PUT" and mapping_match:
            return self.product_categories.update_mapping(
                int(mapping_match.group(1)), payload
            ), HTTPStatus.OK
        if method == "PUT" and mapping_status_match:
            return self.product_categories.set_mapping_status(
                int(mapping_status_match.group(1)), payload.get("is_active")
            ), HTTPStatus.OK
        if method == "PUT" and normalization_status_match:
            return self.product_categories.set_normalization_rule_status(
                int(normalization_status_match.group(1)), payload.get("is_active")
            ), HTTPStatus.OK
        if method == "PUT" and normalization_match:
            return self.product_categories.update_normalization_rule(
                int(normalization_match.group(1)), payload
            ), HTTPStatus.OK
        if method == "PUT" and catalog_match:
            return self.product_categories.update_catalog_row(
                int(catalog_match.group(1)), payload
            ), HTTPStatus.OK
        if method == "PUT" and catalog_status_match:
            return self.product_categories.set_catalog_row_status(
                int(catalog_status_match.group(1)), payload.get("is_active")
            ), HTTPStatus.OK

        if method == "DELETE" and company_influencer_match:
            return self.influencer_master.delete_company_influencer(
                int(company_influencer_match.group(1))
            ), HTTPStatus.OK
        if method == "DELETE" and influencer_mapping_match:
            return self.influencer_master.delete_source_mapping(
                int(influencer_mapping_match.group(1))
            ), HTTPStatus.OK
        if method == "DELETE" and company_assignment_match:
            return self.influencer_master.delete_assignment(
                int(company_assignment_match.group(1)),
                parse_month(company_assignment_match.group(2)),
            ), HTTPStatus.OK
        if method == "DELETE" and route == "/influencers":
            platform = query.get("platform", [""])[0].strip()
            influencer_id = query.get("influencer_id", [""])[0].strip()
            month = parse_month(query.get("month", [""])[0])
            return self.database.delete_influencer(platform, influencer_id, month), HTTPStatus.OK
        if method == "DELETE" and business_match:
            return self.database.delete_business(int(business_match.group(1))), HTTPStatus.OK
        if method == "DELETE" and category_match:
            return self.product_categories.delete_category(int(category_match.group(1))), HTTPStatus.OK
        if method == "DELETE" and catalog_match:
            return self.product_categories.delete_catalog_row(
                int(catalog_match.group(1))
            ), HTTPStatus.OK
        if method == "DELETE" and product_match:
            return self.product_categories.delete_product(
                unquote(product_match.group(1))
            ), HTTPStatus.OK
        if method == "DELETE" and mapping_match:
            return self.product_categories.delete_mapping(
                int(mapping_match.group(1))
            ), HTTPStatus.OK
        if method == "DELETE" and normalization_match:
            return self.product_categories.delete_normalization_rule(
                int(normalization_match.group(1))
            ), HTTPStatus.OK

        return None
