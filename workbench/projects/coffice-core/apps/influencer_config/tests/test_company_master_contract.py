from __future__ import annotations

import unittest
from pathlib import Path

from apps.influencer_config.product_category import ProductCategoryService


ROOT = Path(__file__).resolve().parents[3]


class CompanyMasterContractTests(unittest.TestCase):
    def test_new_company_product_ids_use_short_shared_format(self):
        product_id = ProductCategoryService._new_product_id()
        self.assertRegex(product_id, r"^PRD-CODE-[0-9A-F]{16}$")
        self.assertNotIn("PRD-MANUAL-", product_id)

    def test_code_expression_is_quantity_rule_not_full_platform_code(self):
        alias, pattern, prefix, rule, role, position = ProductCategoryService._mapping_values(
            {"source_product_code": "M-MGNT", "quantity_position": "suffix"}
        )
        self.assertEqual(alias, "M-MGNT")
        self.assertEqual(pattern, "M-MGNT-X")
        self.assertEqual(prefix, "M-MGNT-")
        self.assertEqual((rule, role, position), ("suffix_quantity", "box", "suffix"))

    def test_product_mapping_uses_global_alias_identity(self):
        sql_text = (ROOT / "sql/dim/427_refactor_company_product_identity_postgres.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("uq_company_product_alias_rule", sql_text)
        self.assertIn("company_product_code", sql_text)
        self.assertIn("quantity_position", sql_text)
        self.assertNotIn("uq_company_product_mapping_platform_code\n    ON", sql_text)

    def test_unmapped_product_is_preserved_as_unconfigured(self):
        helper = (ROOT / "sql/common/276_operating_sales_product_allocation_refresh_helper_postgres.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("'未配置'", helper)
        self.assertIn("rule.alias_code", helper)
        self.assertIn("paid_quantity", helper)
        self.assertIn("WHEN r.paid_quantity = 0 THEN 0", helper)
        self.assertNotIn("candidate.platform_code IN", helper)

    def test_required_quantity_alias_bundle_and_gift_contracts_are_explicit(self):
        migration = (ROOT / "sql/dim/427_refactor_company_product_identity_postgres.sql").read_text(
            encoding="utf-8"
        )
        aliases = (ROOT / "sql/dim/428_seed_company_product_alias_rules_postgres.sql").read_text(
            encoding="utf-8"
        )
        helper = (ROOT / "sql/common/276_operating_sales_product_allocation_refresh_helper_postgres.sql").read_text(
            encoding="utf-8"
        )
        observation = (ROOT / "sql/common/398_operating_sales_product_code_observation_view_postgres.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("parse_company_product_component", migration)
        self.assertIn("M-MGNT", aliases)
        self.assertIn("('MG', 'M-MGNT', 'prefix'", aliases)
        self.assertIn("REGEXP_SPLIT_TO_TABLE", helper)
        self.assertIn("gift_quantity", helper)
        self.assertIn("SUM(m.paid_quantity)", helper)
        self.assertIn("mapped已映射、unmapped未映射、inactive", observation)
        self.assertNotIn("'partial'", observation)

    def test_influencer_ads_group_by_stable_identity(self):
        daily = (ROOT / "sql/ads/influencer_performance/399_refresh_ads_influencer_company_shop_daily_company_identity_postgres.sql").read_text(
            encoding="utf-8"
        )
        monthly = (ROOT / "sql/ads/influencer_performance/400_refresh_ads_influencer_monthly_ranking_company_identity_postgres.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("influencer_identity_key", daily)
        self.assertIn("influencer_identity_key", monthly)
        self.assertNotIn("GROUP BY\n        source.influencer_name", daily)
        self.assertNotIn("GROUP BY\n        daily.influencer_name", monthly)

    def test_configuration_page_exposes_required_tabs(self):
        script = (ROOT / "apps/influencer_config/static/master-config.js").read_text(
            encoding="utf-8"
        )
        index = (ROOT / "apps/influencer_config/static/index.html").read_text(
            encoding="utf-8"
        )
        for label in ("公司达人库", "平台达人映射", "商务归属", "公司商品", "一级分类", "二级分类"):
            self.assertIn(label, script)
        self.assertIn("商品编码映射", index)
        self.assertNotIn('data-title="原始商品编码"', index)
        self.assertNotIn('id="productSourceCodePanel"', index)

    def test_query_reset_buttons_stay_next_to_search_in_all_master_toolbars(self):
        script = (ROOT / "apps/influencer_config/static/master-config.js").read_text(
            encoding="utf-8"
        )
        stylesheet = (ROOT / "apps/influencer_config/static/product-category.css").read_text(
            encoding="utf-8"
        )
        for search_id, query_id, reset_id, primary_id in (
            ("productSearch", "productQueryAction", "productResetAction", "productPrimaryAction"),
            ("influencerSearch", "influencerQueryAction", "influencerResetAction", "influencerPrimaryAction"),
        ):
            with self.subTest(search_id=search_id):
                self.assertLess(script.index(f'id="{search_id}"'), script.index(f'id="{query_id}"'))
                self.assertLess(script.index(f'id="{query_id}"'), script.index(f'id="{reset_id}"'))
                self.assertLess(script.index(f'id="{reset_id}"'), script.index(f'id="{primary_id}"'))
        self.assertIn(".catalog-filters .query-button", stylesheet)
        self.assertIn(".catalog-filters .reset-button", stylesheet)

    def test_master_subnav_uses_segmented_tab_style(self):
        stylesheet = (ROOT / "apps/influencer_config/static/product-category.css").read_text(
            encoding="utf-8"
        )
        script = (ROOT / "apps/influencer_config/static/master-config.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("width: max-content", stylesheet)
        self.assertIn("gap: 4px", stylesheet)
        self.assertIn(".catalog-subtab.is-active { color: var(--primary);", stylesheet)
        self.assertIn(".catalog-subtab.is-active::after { display: none; }", stylesheet)
        self.assertIn('class="catalog-subnav"', script)
        self.assertIn('class="catalog-subtab"', script)

    def test_platform_influencer_mapping_supports_single_row_picker(self):
        script = (ROOT / "apps/influencer_config/static/master-config.js").read_text(
            encoding="utf-8"
        )
        stylesheet = (ROOT / "apps/influencer_config/static/master-config.css").read_text(
            encoding="utf-8"
        )
        index = (ROOT / "apps/influencer_config/static/index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("function influencerCompanyPicker(row)", script)
        self.assertIn("data-influencer-assign-trigger", script)
        self.assertIn("function saveSingleInfluencerMapping(row, company)", script)
        self.assertIn('app().api("/api/influencer-source-mappings/batch"', script)
        self.assertIn('id="assignDropdown"', index)
        self.assertIn('id="assignSearch" placeholder="查找公司达人"', index)
        self.assertIn(".influencer-assign-trigger[aria-expanded=\"true\"] svg", stylesheet)

    def test_source_product_current_owner_uses_same_compact_picker(self):
        script = (ROOT / "apps/influencer_config/static/master-config.js").read_text(
            encoding="utf-8"
        )
        stylesheet = (ROOT / "apps/influencer_config/static/master-config.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("function productCompanyPicker(row)", script)
        self.assertIn("data-product-assign-trigger", script)
        self.assertIn("function saveSingleProductMapping(row, product)", script)
        self.assertIn('app().api("/api/product-mappings/batch"', script)
        self.assertIn('search.placeholder = kind === "product" ? "查找公司商品" : "查找公司达人"', script)
        self.assertIn(".master-table td.product-company-cell", stylesheet)
        self.assertIn("width: 220px; min-width: 220px; max-width: 220px;", stylesheet)
        self.assertIn('class="product-status-cell"', script)
        self.assertIn('class="influencer-status-cell"', script)
        self.assertIn(
            ".master-table td.influencer-status-cell,\n"
            ".master-table td.product-status-cell { width: 72px; min-width: 72px; max-width: 72px; padding-left: 8px; padding-right: 8px; overflow: visible; }",
            stylesheet,
        )
        self.assertIn("width: 127px", stylesheet)
        self.assertIn("text-overflow: ellipsis", stylesheet)
        self.assertIn("title=\"${esc(displayName)}\"", script)

    def test_product_mapping_labels_use_company_code_and_do_not_overlap_status(self):
        script = (ROOT / "apps/influencer_config/static/master-config.js").read_text(
            encoding="utf-8"
        )
        stylesheet = (ROOT / "apps/influencer_config/static/master-config.css").read_text(
            encoding="utf-8"
        )
        self.assertIn('${item.company_product_code || "未设置编码"}', script)
        self.assertNotIn('${item.product_name || "公司商品"} (${item.product_id})', script)
        self.assertIn("<th>公司商品编码</th>", script)
        self.assertNotIn("商品ID / 公司编码", script)
        self.assertIn(".product-company-display strong", stylesheet)
        self.assertIn(".product-mapping-table .product-status-cell", stylesheet)

    def test_product_mapping_request_race_and_normalization_rules_are_supported(self):
        script = (ROOT / "apps/influencer_config/static/master-config.js").read_text(
            encoding="utf-8"
        )
        service = (ROOT / "apps/influencer_config/product_category.py").read_text(
            encoding="utf-8"
        )
        helper = (ROOT / "sql/common/276_operating_sales_product_allocation_refresh_helper_postgres.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("requestVersion !== s.requestVersion", script)
        self.assertIn("编码修正规则", script)
        self.assertIn("/api/product-code-normalizations", script)
        self.assertIn("def create_normalization_rule", service)
        self.assertIn("dim_company_product_code_normalization_rule", helper)
        self.assertIn("raw_merchant_code_component", helper)

    def test_toolbar_filters_only_apply_after_query_click(self):
        script = (ROOT / "apps/influencer_config/static/master-config.js").read_text(
            encoding="utf-8"
        )
        app_script = (ROOT / "apps/influencer_config/static/app.js").read_text(
            encoding="utf-8"
        )
        index = (ROOT / "apps/influencer_config/static/index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'state.product.status = root.querySelector("#productStatus").value;',
            script,
        )
        self.assertIn(
            'state.product.platform = root.querySelector("#productPlatform").value;',
            script,
        )
        self.assertIn(
            'state.influencer.status = root.querySelector("#influencerStatus").value;',
            script,
        )
        self.assertIn(
            'state.influencer.gmvMin = root.querySelector("#influencerGmvFilter").value;',
            script,
        )
        self.assertNotIn(
            'root.querySelector("#productStatus").addEventListener("change"', script
        )
        self.assertNotIn(
            'root.querySelector("#productSearch").addEventListener("input"', script
        )
        self.assertNotIn(
            'root.querySelector("#influencerStatus").addEventListener("change"', script
        )
        self.assertNotIn(
            'root.querySelector("#influencerSearch").addEventListener("input"', script
        )
        self.assertNotIn(
            'addEventListener("change", resetAndLoadAssignments)', app_script
        )
        self.assertNotIn(
            'el("searchInput").addEventListener("input"', app_script
        )
        self.assertIn(
            'el("reloadAssignments").addEventListener("click", resetAndLoadAssignments)',
            app_script,
        )
        self.assertIn('id="reloadAssignments"', index)
        self.assertIn('<svg><use href="#i-search"/></svg>查询', index)

    def test_source_mapping_batch_mode_is_shared_by_rows_and_picker(self):
        script = (ROOT / "apps/influencer_config/static/master-config.js").read_text(
            encoding="utf-8"
        )
        stylesheet = (ROOT / "apps/influencer_config/static/master-config.css").read_text(
            encoding="utf-8"
        )
        index = (ROOT / "apps/influencer_config/static/index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("batchMode: false", script)
        self.assertIn("batch-selection-mode", script)
        self.assertIn("master-selection-col", script)
        self.assertIn("showTablePopover(\"batch-confirm\"", script)
        self.assertIn("event.target.closest(\"button,input,select,textarea,a,.row-actions,.assign-combobox,[data-action]\")", script)
        self.assertIn(".master-table:not(.batch-selection-mode) .master-selection-col", stylesheet)
        self.assertIn(".master-table.batch-selection-mode tbody tr.is-selected", stylesheet)
        self.assertIn('id="tablePopover"', index)

    def test_batch_toggle_uses_check_square_and_orange_close_state(self):
        script = (ROOT / "apps/influencer_config/static/master-config.js").read_text(
            encoding="utf-8"
        )
        stylesheet = (ROOT / "apps/influencer_config/static/master-config.css").read_text(
            encoding="utf-8"
        )
        index = (ROOT / "apps/influencer_config/static/index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('id="i-check-square"', index)
        self.assertIn('id="i-x-square"', index)
        self.assertIn("开启批量勾选", script)
        self.assertIn("关闭批量勾选", script)
        self.assertIn("#i-check-square", script)
        self.assertIn("#i-x-square", script)
        self.assertIn(".button.batch-toggle-button.batch-mode-active", stylesheet)

    def test_source_pagers_show_total_and_unmapped_total(self):
        script = (ROOT / "apps/influencer_config/static/master-config.js").read_text(
            encoding="utf-8"
        )
        product_service = (ROOT / "apps/influencer_config/product_category.py").read_text(
            encoding="utf-8"
        )
        influencer_service = (ROOT / "apps/influencer_config/influencer_master.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("function paginationSummary(scope)", script)
        self.assertIn("共 ${s.total || 0} 条 · 未映射 ${s.unmappedTotal || 0} 条", script)
        self.assertIn("data.pagination?.unmapped_total", script)
        self.assertIn('"unmapped_total": unmapped_total', product_service)
        self.assertIn("mapping_status = 'unmapped'", product_service)
        self.assertIn('"unmapped_total": unmapped_total', influencer_service)
        self.assertIn("mapping.mapping_id IS NULL OR NOT mapping.is_active", influencer_service)

    def test_mapping_picker_empty_values_are_black(self):
        stylesheet = (ROOT / "apps/influencer_config/static/master-config.css").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            ".influencer-assign-trigger .assign-value.empty,\n"
            ".product-assign-trigger .assign-value.empty { color: var(--foreground); }",
            stylesheet,
        )

    def test_company_influencer_lists_are_sorted_by_id_ascending(self):
        service = (ROOT / "apps/influencer_config/influencer_master.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("ORDER BY i.company_influencer_id ASC", service)
        self.assertIn("ORDER BY influencer.company_influencer_id ASC", service)


if __name__ == "__main__":
    unittest.main()
