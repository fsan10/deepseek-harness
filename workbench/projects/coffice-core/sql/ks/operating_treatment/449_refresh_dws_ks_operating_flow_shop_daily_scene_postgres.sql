TRUNCATE TABLE dws.dws_ks_operating_flow_shop_daily_scene;
WITH formula AS (
    SELECT stat_date,platform_code,platform_name,shop_code,shop_name,source_document_type,
        'income'::text source_origin,secondary_category_code,secondary_category_name,
        income_amount source_signed_amount,included_detail_count,
        included_detail_count source_detail_count,source_updated_at
    FROM dws.dws_ks_main_business_income_shop_daily_category
    UNION ALL
    SELECT stat_date,platform_code,platform_name,shop_code,shop_name,source_document_type,
        'expense',secondary_category_code,secondary_category_name,
        -expense_amount,included_detail_count,source_detail_count,source_updated_at
    FROM dws.dws_ks_platform_expense_shop_daily_category
    UNION ALL
    SELECT d.stat_date,d.platform_code,MAX(d.platform_name),d.shop_code,MAX(d.shop_name),d.source_document_type,
        'excluded',m.secondary_category_code||'_'||LEFT(MD5(d.secondary_category_name),12),d.secondary_category_name,
        -SUM(d.directional_expense_amount),
        COUNT(*) FILTER(WHERE d.directional_expense_amount<>0),COUNT(*),MAX(d.source_updated_at)
    FROM dwd.dwd_ks_platform_expense_source_detail d
    CROSS JOIN LATERAL dim.match_platform_operating_scene('ks',d.source_document_type,d.secondary_category_name,d.source_business_type,d.source_description) m
    WHERE m.canonical_operating_treatment='excluded' OR m.canonical_operating_treatment IS NULL
    GROUP BY d.stat_date,d.platform_code,d.shop_code,d.source_document_type,m.secondary_category_code,d.secondary_category_name
), resolved AS (
    SELECT f.*,m.operating_treatment,m.canonical_operating_treatment,m.source_role,m.classification_note,
        m.updated_at mapping_updated_at,m.source_usage,m.source_usage_note,
        CASE WHEN m.is_active AND c.is_active AND m.primary_category_code<>'unmapped'
            THEN m.primary_category_code ELSE 'unmapped' END classified_code,
        CASE WHEN m.is_active AND c.is_active AND m.primary_category_code<>'unmapped'
            THEN c.primary_category_name ELSE '未映射' END classified_name,
        dim.effective_platform_operating_treatment(m.mapping_id) effective_treatment
    FROM formula f
    LEFT JOIN LATERAL (
        SELECT r.* FROM dim.dim_platform_fee_mapping r
        WHERE r.platform_code=f.platform_code AND r.source_document_type=f.source_document_type
          AND (r.source_component_code=f.secondary_category_code
            OR (r.source_component_code IS NULL AND (
                r.secondary_category_code=f.secondary_category_code
                OR LEFT(f.secondary_category_code,LENGTH(r.secondary_category_code)+1)=r.secondary_category_code||'_'
                OR r.secondary_category_name=f.secondary_category_name)))
        ORDER BY (r.source_component_code=f.secondary_category_code) DESC NULLS LAST,
            (r.secondary_category_code=f.secondary_category_code) DESC,
            r.mapping_priority DESC,r.mapping_id LIMIT 1
    ) m ON TRUE
    LEFT JOIN dim.dim_platform_fee_primary_category c ON c.primary_category_code=m.primary_category_code
)
INSERT INTO dws.dws_ks_operating_flow_shop_daily_scene(stat_date,platform_code,platform_name,shop_code,shop_name,source_document_type,source_origin,secondary_category_code,secondary_category_name,primary_category_code,primary_category_name,operating_treatment,mapping_status,source_signed_amount,income_amount,expense_amount,excluded_amount,included_detail_count,source_detail_count,exclusion_reason,source_updated_at,mapping_updated_at,updated_at)
SELECT stat_date,platform_code,platform_name,shop_code,shop_name,source_document_type,source_origin,
    secondary_category_code,secondary_category_name,classified_code,classified_name,effective_treatment,
    CASE WHEN classified_code='unmapped' THEN 'unmapped' ELSE 'mapped' END,
    source_signed_amount,
    CASE WHEN effective_treatment='income' THEN source_signed_amount ELSE 0 END,
    CASE WHEN effective_treatment='expense' THEN -source_signed_amount ELSE 0 END,
    CASE WHEN effective_treatment='excluded' OR effective_treatment IS NULL THEN source_signed_amount ELSE 0 END,
    included_detail_count,source_detail_count,
    CASE WHEN effective_treatment IS NULL THEN '经营归属待确认'
        WHEN source_usage IN ('accounted','duplicate') THEN source_usage_note
        WHEN effective_treatment='excluded' THEN COALESCE(NULLIF(classification_note,''),'财务设置不计入经营收支')
        ELSE '' END,
    source_updated_at,mapping_updated_at,NOW() FROM resolved;
