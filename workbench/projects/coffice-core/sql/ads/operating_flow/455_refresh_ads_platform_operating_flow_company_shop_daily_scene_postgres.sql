TRUNCATE TABLE ads.ads_platform_operating_flow_company_shop_daily_scene;
INSERT INTO ads.ads_platform_operating_flow_company_shop_daily_scene(stat_date,platform_code,platform_name,shop_code,shop_name,company_code,company_name,source_document_type,source_origin,secondary_category_code,secondary_category_name,primary_category_code,primary_category_name,operating_treatment,mapping_status,source_signed_amount,income_amount,expense_amount,excluded_amount,included_detail_count,source_detail_count,exclusion_reason,source_updated_at,mapping_updated_at,updated_at)
WITH source_union AS (SELECT * FROM dws.dws_douyin_operating_flow_shop_daily_scene
UNION ALL
SELECT * FROM dws.dws_jd_operating_flow_shop_daily_scene
UNION ALL
SELECT * FROM dws.dws_ks_operating_flow_shop_daily_scene
UNION ALL
SELECT * FROM dws.dws_pdd_operating_flow_shop_daily_scene
UNION ALL
SELECT * FROM dws.dws_tmall_operating_flow_shop_daily_scene
UNION ALL
SELECT * FROM dws.dws_wechat_channels_operating_flow_shop_daily_scene
UNION ALL
SELECT * FROM dws.dws_xhs_operating_flow_shop_daily_scene)
SELECT d.stat_date,d.platform_code,d.platform_name,d.shop_code,d.shop_name,COALESCE(c.company_code,'unmapped'),COALESCE(c.company_name,'未匹配公司'),d.source_document_type,d.source_origin,d.secondary_category_code,d.secondary_category_name,d.primary_category_code,d.primary_category_name,d.operating_treatment,d.mapping_status,d.source_signed_amount,d.income_amount,d.expense_amount,d.excluded_amount,d.included_detail_count,d.source_detail_count,d.exclusion_reason,d.source_updated_at,d.mapping_updated_at,d.updated_at
FROM source_union d
LEFT JOIN dim.dim_platform_shop_company c ON c.platform_code=d.platform_code AND c.shop_code=d.shop_code
 AND c.is_active AND d.stat_date>=c.valid_from AND (c.valid_to IS NULL OR d.stat_date<=c.valid_to);
DO $$ BEGIN
    IF EXISTS(SELECT 1 FROM ads.ads_platform_operating_flow_company_shop_daily_scene WHERE company_code='unmapped') THEN
        RAISE EXCEPTION '经营收支明细存在未匹配公司，停止刷新';
    END IF;
END $$;
