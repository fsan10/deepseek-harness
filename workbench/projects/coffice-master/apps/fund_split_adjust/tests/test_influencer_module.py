from __future__ import annotations

import argparse
import unittest
from datetime import date
from http import HTTPStatus
from pathlib import Path

from apps.fund_split_adjust.influencer_module import InfluencerModule


class FakeInfluencerDatabase:
    def __init__(self):
        self.calls = []

    def health(self):
        return {"database_name": "mock_coffice"}

    def list_businesses(self):
        return [{"business_owner_id": 1}]

    def list_influencers(self, *args):
        self.calls.append(("list_influencers", args))
        return {"rows": [], "pagination": {"total": 0}}

    def refresh_status(self):
        return {"status": "succeeded", "completed_revision": 1}

    def close(self, **_kwargs):
        return True

    def list_targets(self, month):
        self.calls.append(("list_targets", month))
        return {"rows": []}

    def create_business(self, name):
        return {"business_owner_name": name}

    def update_business(self, business_owner_id, name):
        self.calls.append(("update_business", business_owner_id, name))
        return {"business_owner_id": business_owner_id, "business_owner_name": name}

    def delete_business(self, business_owner_id):
        self.calls.append(("delete_business", business_owner_id))
        return {"business_owner_id": business_owner_id, "is_active": False}

    def save_assignment(self, payload):
        return payload

    def save_target(self, payload):
        return payload

    def delete_influencer(self, platform, influencer_id, month):
        return {"platform": platform, "influencer_id": influencer_id, "month": month}

    def toggle_influencer_status(self, platform, influencer_id, month, is_active):
        self.calls.append(("toggle_influencer_status", platform, influencer_id, month, is_active))
        return {"platform": platform, "influencer_id": influencer_id, "month": month, "is_active": is_active}


class FakeProductCategories:
    def refresh_status(self):
        return {"status": "queued", "requested_revision": 2}

    def close(self, **_kwargs):
        return True

    def health(self):
        return {
            "product_category_ready": True,
            "product_ready": True,
            "product_mapping_ready": True,
        }

    def migrate(self):
        return "sql/dim/183_dim_influencer_product_category_postgres.sql"

    def list_categories(self):
        return {"categories": [{"category_id": 1}], "summary": {"category_total": 1}}

    def list_products(self, category_id, search, page, page_size, status="all"):
        return {"category_id": category_id, "search": search, "page": page, "page_size": page_size}

    def list_mappings(self, search, status, platform, page, page_size):
        return {"rows": [], "pagination": {"total": 0}, "query": (search, status, platform, page, page_size)}

    def list_normalization_rules(self, search, status, page, page_size):
        return {
            "rows": [{"normalization_rule_id": 6}],
            "pagination": {"total": 1},
            "query": (search, status, page, page_size),
        }

    def list_source_codes(self, search, status, platform, page, page_size):
        return {"rows": [], "pagination": {"total": 0}, "query": (search, status, platform, page, page_size)}

    def list_catalog(self, search, status, page, page_size):
        return {"search": search, "status": status, "page": page, "page_size": page_size}

    def list_category_page(self, level, search, status, page, page_size):
        return {
            "level": level,
            "search": search,
            "status": status,
            "page": page,
            "page_size": page_size,
        }

    def create_category(self, payload):
        return {"category_id": 1, **payload}

    def update_category(self, category_id, payload):
        return {"category_id": category_id, **payload}

    def set_category_status(self, category_id, is_active):
        return {"category_id": category_id, "is_active": is_active}

    def delete_category(self, category_id):
        return {"category_id": category_id, "deleted": True}

    def create_catalog_row(self, payload):
        return {"mapping_id": 9, **payload}

    def update_catalog_row(self, mapping_id, payload):
        return {"mapping_id": mapping_id, **payload}

    def set_catalog_row_status(self, mapping_id, is_active):
        return {"mapping_id": mapping_id, "is_active": is_active}

    def delete_catalog_row(self, mapping_id):
        return {"mapping_id": mapping_id, "deleted": True}

    def create_product(self, payload):
        return payload

    def update_product(self, product_id, payload):
        return {"product_id": product_id, **payload}

    def set_product_status(self, product_id, is_active):
        return {"product_id": product_id, "is_active": is_active}

    def create_mapping(self, payload):
        return {"mapping_id": 8, **payload}

    def batch_map_source_codes(self, payload):
        return {"created": len(payload.get("items", []))}

    def create_normalization_rule(self, payload):
        return {"normalization_rule_id": 6, **payload}

    def update_mapping(self, mapping_id, payload):
        return {"mapping_id": mapping_id, **payload}

    def set_mapping_status(self, mapping_id, is_active):
        return {"mapping_id": mapping_id, "is_active": is_active}

    def update_normalization_rule(self, rule_id, payload):
        return {"normalization_rule_id": rule_id, **payload}

    def set_normalization_rule_status(self, rule_id, is_active):
        return {"normalization_rule_id": rule_id, "is_active": is_active}

    def delete_mapping(self, mapping_id):
        return {"mapping_id": mapping_id, "deleted": True}

    def delete_normalization_rule(self, rule_id):
        return {"normalization_rule_id": rule_id, "deleted": True}

    def delete_product(self, product_id):
        return {"product_id": product_id, "deleted": True}


class FakeInfluencerMaster:
    def __init__(self):
        self.calls = []

    def health(self):
        return {"company_influencer_ready": True}

    def migrate(self):
        return "sql/dim/394_dim_company_influencer_postgres.sql"

    def list_company_influencers(self, *args):
        self.calls.append(("list_company_influencers", args))
        return {"rows": [], "pagination": {"total": 0}}

    def list_source_accounts(self, *args):
        self.calls.append(("list_source_accounts", args))
        return {"rows": [], "pagination": {"total": 0}}

    def list_assignments(self, *args):
        self.calls.append(("list_assignments", args))
        return {"rows": [], "pagination": {"total": 0}}

    def create_company_influencer(self, payload):
        return {"company_influencer_id": 11, **payload}

    def update_company_influencer(self, influencer_id, payload):
        return {"company_influencer_id": influencer_id, **payload}

    def set_company_influencer_status(self, influencer_id, is_active):
        return {"company_influencer_id": influencer_id, "is_active": is_active}

    def delete_company_influencer(self, influencer_id):
        return {"company_influencer_id": influencer_id, "deleted": True}

    def save_source_mappings(self, payload):
        return {"created": len(payload.get("items", []))}

    def set_source_mapping_status(self, mapping_id, is_active):
        return {"mapping_id": mapping_id, "is_active": is_active}

    def delete_source_mapping(self, mapping_id):
        return {"mapping_id": mapping_id, "deleted": True}

    def save_assignment(self, payload, month):
        return {"company_influencer_id": payload["company_influencer_id"], "effective_month": month}

    def delete_assignment(self, influencer_id, month):
        return {"company_influencer_id": influencer_id, "effective_month": month, "deleted": True}


class InfluencerModuleTest(unittest.TestCase):
    def setUp(self):
        self.database = FakeInfluencerDatabase()
        self.product_categories = FakeProductCategories()
        self.influencer_master = FakeInfluencerMaster()
        self.module = InfluencerModule(
            argparse.Namespace(),
            database=self.database,
            product_categories=self.product_categories,
            influencer_master=self.influencer_master,
        )

    def test_static_resources_remain_in_influencer_app(self):
        index = self.module.static_file("/influencer/")
        stylesheet = self.module.static_file("/influencer/styles.css")

        self.assertEqual(index.name, "index.html")
        self.assertEqual(stylesheet.name, "styles.css")
        self.assertIn("influencer_config", str(index))
        self.assertIsNone(self.module.static_file("/styles.css"))

    def test_module_switching_uses_shared_permission_navigation(self):
        project_root = Path(__file__).resolve().parents[3]
        bank_html = (project_root / "apps/fund_split_adjust/static/index.html").read_text(encoding="utf-8")
        influencer_html = (project_root / "apps/influencer_config/static/index.html").read_text(encoding="utf-8")

        self.assertIn('src="/identity-assets/shell.js"', bank_html)
        self.assertIn('src="/identity-assets/shell.js"', influencer_html)
        self.assertIn('href="/influencer/#assignmentPanel"', bank_html)
        self.assertIn('href="/influencer/#productMappingPanel"', bank_html)
        self.assertNotIn('href="/influencer/#productSourceCodePanel"', bank_html)
        self.assertIn('data-tab="productMappingPanel"', influencer_html)
        self.assertNotIn('data-tab="productSourceCodePanel"', influencer_html)
        self.assertIn('href="/#statement"', influencer_html)

    def test_product_pages_are_split_and_use_reference_pagination(self):
        project_root = Path(__file__).resolve().parents[3]
        script = (project_root / "apps/influencer_config/static/master-config.js").read_text(
            encoding="utf-8"
        )
        stylesheet = (project_root / "apps/influencer_config/static/master-config.css").read_text(
            encoding="utf-8"
        )

        self.assertIn('data-product-view="products"', script)
        self.assertIn('data-product-view="l1"', script)
        self.assertIn('data-product-view="l2"', script)
        self.assertIn('data-product-view="mappings"', script)
        self.assertIn('data-product-view="normalizations"', script)
        self.assertNotIn('data-product-view="source"', script)
        self.assertIn('window.productMappingModule', script)
        self.assertNotIn('window.productSourceCodeModule', script)
        self.assertIn('class="pagination-pages"', script)
        self.assertIn('class="pagination-page-btn', script)
        self.assertIn('pageSize: 10', script)
        self.assertIn('已取消编辑', script)
        self.assertIn('已取消新增商品操作', script)
        self.assertIn('influencerGmvFilter', script)
        self.assertIn('data-action="select-all-source"', script)
        self.assertIn('<th>公司达人ID</th>', script)
        self.assertIn('function syncPager(scope, loader)', script)
        self.assertIn('ensurePager("product", loadProduct)', script)
        self.assertIn('ensurePager("influencer", loadInfluencer)', script)
        self.assertIn('beginTableLoad("productMasterTable")', script)
        self.assertIn('beginTableLoad("influencerMasterTable")', script)
        self.assertIn('已${enabled ? "启用" : "停用"}', script)
        self.assertNotIn('app().toast("操作成功")', script)
        self.assertNotIn('document.getElementById("productMasterPager").innerHTML = pager("product")', script)
        self.assertNotIn('document.getElementById("influencerMasterPager").innerHTML = pager("influencer")', script)
        self.assertIn(".master-table th, .assignment-table th, .target-table th { height: 44px; padding: 0 16px;", stylesheet)
        self.assertIn(".master-table td { padding: 8px 16px; }", stylesheet)
        self.assertIn(".assignment-table td, .target-table td { padding: 8px 16px; }", stylesheet)
        self.assertIn(".product-table-shell.is-loading", stylesheet)
        self.assertIn(".icon-action.warning", stylesheet)
        self.assertIn("#fa8c16", stylesheet)

    def test_assignment_query_is_forwarded_without_bank_dependencies(self):
        data, status = self.module.dispatch(
            "GET",
            "/api/influencer/influencers",
            "month=2026-07&platform=douyin&business_owner_id=7&status=assigned&search=test&page=2&page_size=50",
        )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(data["rows"], [])
        name, args = self.database.calls[-1]
        self.assertEqual(name, "list_influencers")
        self.assertEqual(args, (date(2026, 7, 1), "douyin", 7, "assigned", "test", 2, 50, None))

    def test_active_status_filter_and_toggle_route_are_forwarded(self):
        self.module.dispatch(
            "GET",
            "/api/influencer/influencers",
            "month=2026-07&active_status=disabled",
        )
        toggled, status = self.module.dispatch(
            "POST",
            "/api/influencer/influencers/toggle-status",
            "",
            {
                "platform_code": "douyin",
                "influencer_id": "1001",
                "effective_month": "2026-07",
                "is_active": False,
            },
        )

        self.assertEqual(self.database.calls[0][1][-1], "disabled")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertFalse(toggled["is_active"])
        self.assertIn(
            ("toggle_influencer_status", "douyin", "1001", date(2026, 7, 1), False),
            self.database.calls,
        )

    def test_refresh_status_is_namespaced_and_module_closes_workers(self):
        result, status = self.module.dispatch("GET", "/api/influencer/refresh-status", "")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(result["metrics"]["status"], "succeeded")
        self.assertEqual(result["product_dashboard"]["status"], "queued")
        self.assertTrue(self.module.close())

    def test_mutations_use_namespaced_routes(self):
        created, create_status = self.module.dispatch(
            "POST", "/api/influencer/businesses", "", {"business_owner_name": "王商务"}
        )
        deleted, delete_status = self.module.dispatch(
            "DELETE",
            "/api/influencer/influencers",
            "month=2026-07&platform=douyin&influencer_id=1001",
        )

        self.assertEqual(create_status, HTTPStatus.CREATED)
        self.assertEqual(created["business_owner_name"], "王商务")
        self.assertEqual(delete_status, HTTPStatus.OK)
        self.assertEqual(deleted["month"], date(2026, 7, 1))

    def test_product_code_normalization_routes_are_available_from_unified_service(self):
        listed, list_status = self.module.dispatch(
            "GET",
            "/api/influencer/product-code-normalizations",
            "search=RYKK&status=active&page=2&page_size=20",
        )
        created, create_status = self.module.dispatch(
            "POST",
            "/api/influencer/product-code-normalizations",
            "",
            {"source_code_component": "A1B", "normalized_code_expression": "A-1+B-1"},
        )
        updated, update_status = self.module.dispatch(
            "PUT",
            "/api/influencer/product-code-normalizations/6",
            "",
            {"source_code_component": "A1B", "normalized_code_expression": "A-1+B-2"},
        )
        disabled, disable_status = self.module.dispatch(
            "PUT",
            "/api/influencer/product-code-normalizations/6/status",
            "",
            {"is_active": False},
        )
        deleted, delete_status = self.module.dispatch(
            "DELETE", "/api/influencer/product-code-normalizations/6", ""
        )

        self.assertEqual(list_status, HTTPStatus.OK)
        self.assertEqual(listed["query"], ("RYKK", "active", 2, 20))
        self.assertEqual(create_status, HTTPStatus.CREATED)
        self.assertEqual(created["normalization_rule_id"], 6)
        self.assertEqual(update_status, HTTPStatus.OK)
        self.assertEqual(updated["normalized_code_expression"], "A-1+B-2")
        self.assertEqual(disable_status, HTTPStatus.OK)
        self.assertFalse(disabled["is_active"])
        self.assertEqual(delete_status, HTTPStatus.OK)
        self.assertTrue(deleted["deleted"])

    def test_business_name_update_and_delete_use_namespaced_routes(self):
        updated, update_status = self.module.dispatch(
            "PUT", "/api/influencer/businesses/7", "", {"business_owner_name": "新姓名"}
        )
        deleted, delete_status = self.module.dispatch(
            "DELETE", "/api/influencer/businesses/7", ""
        )

        self.assertEqual(update_status, HTTPStatus.OK)
        self.assertEqual(updated["business_owner_name"], "新姓名")
        self.assertEqual(delete_status, HTTPStatus.OK)
        self.assertFalse(deleted["is_active"])
        self.assertIn(("update_business", 7, "新姓名"), self.database.calls)
        self.assertIn(("delete_business", 7), self.database.calls)

    def test_product_category_routes_remain_inside_influencer_namespace(self):
        categories, status = self.module.dispatch("GET", "/api/influencer/product-categories", "")
        products, _ = self.module.dispatch(
            "GET", "/api/influencer/product-categories/1/products", "search=latte&page=2&page_size=50"
        )
        updated, _ = self.module.dispatch(
            "PUT", "/api/influencer/products/LT-001/status", "", {"is_active": False}
        )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(categories["summary"]["category_total"], 1)
        self.assertEqual(products, {"category_id": 1, "search": "latte", "page": 2, "page_size": 50})
        self.assertEqual(updated, {"product_id": "LT-001", "is_active": False})

    def test_hierarchical_catalog_and_mapping_routes(self):
        catalog, catalog_status = self.module.dispatch(
            "GET",
            "/api/influencer/product-catalog",
            "search=拿铁&status=active&page=2&page_size=50",
        )
        created, create_status = self.module.dispatch(
            "POST",
            "/api/influencer/product-mappings",
            "",
            {
                "product_id": "PRD-1",
                "code_pattern": "M-NXSY-X",
                "match_rule": "suffix_quantity",
                "code_role": "box",
            },
        )
        deleted, delete_status = self.module.dispatch(
            "DELETE", "/api/influencer/product-mappings/8", ""
        )

        self.assertEqual(catalog_status, HTTPStatus.OK)
        self.assertEqual(
            catalog,
            {"search": "拿铁", "status": "active", "page": 2, "page_size": 50},
        )
        self.assertEqual(create_status, HTTPStatus.CREATED)
        self.assertEqual(created["mapping_id"], 8)
        self.assertEqual(delete_status, HTTPStatus.OK)
        self.assertTrue(deleted["deleted"])

    def test_one_to_one_catalog_and_category_page_routes(self):
        category_page, page_status = self.module.dispatch(
            "GET",
            "/api/influencer/product-category-list",
            "level=2&search=拿铁&status=active&page=1&page_size=20",
        )
        created, create_status = self.module.dispatch(
            "POST",
            "/api/influencer/product-catalog",
            "",
            {"product_name": "测试产品", "code_pattern": "TEST-CODE-X"},
        )
        updated, update_status = self.module.dispatch(
            "PUT",
            "/api/influencer/product-catalog/9",
            "",
            {
                "category_l1_id": 1,
                "category_l2_id": 2,
                "product_name": "测试产品已改",
                "code_pattern": "TEST-CODE-X",
            },
        )
        deleted, delete_status = self.module.dispatch(
            "DELETE", "/api/influencer/product-catalog/9", ""
        )

        self.assertEqual(page_status, HTTPStatus.OK)
        self.assertEqual(category_page["level"], 2)
        self.assertEqual(category_page["search"], "拿铁")
        self.assertEqual(create_status, HTTPStatus.CREATED)
        self.assertEqual(created["mapping_id"], 9)
        self.assertEqual(update_status, HTTPStatus.OK)
        self.assertEqual(updated["product_name"], "测试产品已改")
        self.assertEqual(delete_status, HTTPStatus.OK)
        self.assertTrue(deleted["deleted"])

    def test_health_includes_product_category_readiness(self):
        health, status = self.module.dispatch("GET", "/api/influencer/health", "")

        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(health["product_category_ready"])
        self.assertTrue(health["product_ready"])
        self.assertTrue(health["product_mapping_ready"])
        self.assertTrue(health["company_influencer_ready"])

    def test_new_page_queries_are_forwarded_in_integrated_namespace(self):
        company, company_status = self.module.dispatch(
            "GET", "/api/influencer/company-influencers", "page=1&page_size=10&status=active&platform=douyin&search=99"
        )
        mappings, mapping_status = self.module.dispatch(
            "GET", "/api/influencer/product-mappings", "search=&page=1&page_size=10&status=all&platform="
        )
        source_codes, source_status = self.module.dispatch(
            "GET", "/api/influencer/product-source-codes", "search=&page=1&page_size=10&mapping_status=all&platform="
        )

        self.assertEqual((company_status, mapping_status, source_status), (HTTPStatus.OK,) * 3)
        self.assertEqual(company["pagination"]["total"], 0)
        self.assertEqual(mappings["query"], ("", "all", "", 1, 10))
        self.assertEqual(source_codes["query"], ("", "all", "", 1, 10))
        self.assertEqual(self.influencer_master.calls[0], ("list_company_influencers", ("99", "active", 1, 10, "douyin")))

    def test_influencer_page_filters_and_default_page_size_are_forwarded(self):
        source, source_status = self.module.dispatch(
            "GET",
            "/api/influencer/influencer-source-accounts",
            "mapping_status=all&platform=ks&gmv_min=10000&page=2&page_size=10",
        )
        assignments, assignment_status = self.module.dispatch(
            "GET",
            "/api/influencer/company-influencer-assignments",
            "month=2026-08&business_owner_id=7&platform=tmall&search=99&page=1&page_size=10",
        )

        self.assertEqual((source_status, assignment_status), (HTTPStatus.OK, HTTPStatus.OK))
        self.assertEqual(source["pagination"]["total"], 0)
        self.assertEqual(assignments["pagination"]["total"], 0)
        self.assertEqual(
            self.influencer_master.calls[-2],
            ("list_source_accounts", ("", "all", "ks", 2, 10, "10000")),
        )
        self.assertEqual(
            self.influencer_master.calls[-1],
            ("list_assignments", (date(2026, 8, 1), "99", 7, 1, 10, "tmall")),
        )

    def test_company_influencer_mapping_and_assignment_crud_routes(self):
        created, created_status = self.module.dispatch(
            "POST", "/api/influencer/company-influencers", "", {"company_influencer_name": "测试达人"}
        )
        mapped, mapped_status = self.module.dispatch(
            "POST", "/api/influencer/influencer-source-mappings/batch", "",
            {"company_influencer_id": 11, "items": [{"platform_code": "douyin", "source_influencer_id": "1"}]},
        )
        assigned, assigned_status = self.module.dispatch(
            "POST", "/api/influencer/company-influencer-assignments", "",
            {"company_influencer_id": 11, "effective_month": "2026-08"},
        )
        deleted, deleted_status = self.module.dispatch(
            "DELETE", "/api/influencer/company-influencer-assignments/11/2026-08", ""
        )

        self.assertEqual(created_status, HTTPStatus.CREATED)
        self.assertEqual(created["company_influencer_id"], 11)
        self.assertEqual(mapped_status, HTTPStatus.OK)
        self.assertEqual(mapped["created"], 1)
        self.assertEqual(assigned_status, HTTPStatus.OK)
        self.assertEqual(assigned["effective_month"], date(2026, 8, 1))
        self.assertEqual(deleted_status, HTTPStatus.OK)
        self.assertTrue(deleted["deleted"])

    def test_unrelated_or_unknown_routes_are_not_claimed(self):
        self.assertIsNone(self.module.dispatch("GET", "/api/health", ""))
        self.assertIsNone(self.module.dispatch("GET", "/api/influencer/unknown", ""))


if __name__ == "__main__":
    unittest.main()
