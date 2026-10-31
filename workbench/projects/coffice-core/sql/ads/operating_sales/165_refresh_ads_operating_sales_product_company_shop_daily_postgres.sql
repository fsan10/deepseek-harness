TRUNCATE TABLE ads.ads_operating_sales_product_company_shop_daily;

INSERT INTO ads.ads_operating_sales_product_company_shop_daily (
    stat_date, platform_code, platform_name, company_code, company_name,
    shop_code, shop_name, product_id, company_product_code, product_type,
    large_product_category, product_category_l2, product_name, gmv_amount,
    paid_component_count, gift_component_count, mapped_component_count,
    unmapped_component_count, paid_unit_count, gift_unit_count,
    source_sub_order_count, source_updated_at, updated_at
)
WITH platform_product_allocation_union AS (
    SELECT * FROM dws.dws_douyin_operating_sales_product_allocation
    UNION ALL SELECT * FROM dws.dws_wechat_channels_operating_sales_product_allocation
    UNION ALL SELECT * FROM dws.dws_jd_operating_sales_product_allocation
    UNION ALL SELECT * FROM dws.dws_ks_operating_sales_product_allocation
    UNION ALL SELECT * FROM dws.dws_xhs_operating_sales_product_allocation
    UNION ALL SELECT * FROM dws.dws_pdd_operating_sales_product_allocation
    UNION ALL SELECT * FROM dws.dws_tmall_operating_sales_product_allocation
)
SELECT
    d.stat_date,
    d.platform_code,
    MAX(d.platform_name),
    COALESCE(company.company_code, 'unmapped'),
    COALESCE(company.company_name, '未匹配公司'),
    d.shop_code,
    COALESCE(company.shop_name, MAX(d.shop_name), '未匹配店铺'),
    COALESCE(d.company_product_id, 'unmapped:' || d.code_expression),
    COALESCE(d.company_product_code, d.code_expression),
    COALESCE(d.product_type, 'unmapped'),
    d.large_product_category,
    d.product_category_l2,
    d.product_name,
    ROUND(SUM(d.allocated_gmv_amount), 2),
    COUNT(*) FILTER (WHERE d.paid_quantity > 0),
    COUNT(*) FILTER (WHERE d.is_gift),
    COUNT(*) FILTER (WHERE d.is_mapped),
    COUNT(*) FILTER (WHERE NOT d.is_mapped),
    ROUND(SUM(d.paid_quantity), 2),
    ROUND(SUM(d.gift_quantity), 2),
    COUNT(DISTINCT d.sub_order_no),
    MAX(d.source_updated_at),
    NOW()
FROM platform_product_allocation_union d
LEFT JOIN dim.dim_platform_shop_company company
  ON company.platform_code = d.platform_code
 AND company.shop_code = d.shop_code
 AND company.is_active
 AND d.stat_date >= company.valid_from
 AND (company.valid_to IS NULL OR d.stat_date <= company.valid_to)
GROUP BY
    d.stat_date,
    d.platform_code,
    COALESCE(company.company_code, 'unmapped'),
    COALESCE(company.company_name, '未匹配公司'),
    d.shop_code,
    company.shop_name,
    COALESCE(d.company_product_id, 'unmapped:' || d.code_expression),
    COALESCE(d.company_product_code, d.code_expression),
    COALESCE(d.product_type, 'unmapped'),
    d.large_product_category,
    d.product_category_l2,
    d.product_name;
