CREATE SCHEMA IF NOT EXISTS dws;

CREATE OR REPLACE VIEW dws.v_influencer_identity_resolved AS
WITH source_rows AS (
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_douyin_influencer_sales_order_item
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_wechat_channels_influencer_sales_order_item
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_ks_influencer_sales_order_item
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_tmall_influencer_sales_order
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_jd_influencer_sales_shop_daily_zero
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_xhs_influencer_sales_shop_daily_zero
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_pdd_influencer_sales_shop_daily_zero
)
SELECT
    source.stat_date,
    source.stat_month,
    source.platform_code,
    source.platform_name,
    source.shop_code,
    source.shop_name,
    source.influencer_id AS source_influencer_id,
    source.influencer_name AS source_influencer_name,
    source.influencer_key AS source_influencer_key,
    company.company_influencer_id,
    company.company_influencer_name,
    CASE
        WHEN company.company_influencer_id IS NOT NULL
            THEN 'company:' || company.company_influencer_id::TEXT
        ELSE 'source:' || source.platform_code || ':' || source.influencer_id
    END AS influencer_identity_key,
    COALESCE(company.company_influencer_name, source.influencer_name) AS influencer_display_name,
    source.gmv_amount,
    source.refund_amount,
    source.included_sub_order_count,
    source.source_updated_at
FROM source_rows source
LEFT JOIN dim.dim_company_influencer_source_mapping mapping
  ON mapping.platform_code = source.platform_code
 AND mapping.source_influencer_id = source.influencer_id
 AND mapping.is_active
LEFT JOIN dim.dim_company_influencer company
  ON company.company_influencer_id = mapping.company_influencer_id
 AND company.is_active;

COMMENT ON VIEW dws.v_influencer_identity_resolved IS
    '七平台达人统一身份视图；平台来源账号先映射公司达人，未映射账号按平台加来源UID保持彼此独立。';
COMMENT ON COLUMN dws.v_influencer_identity_resolved.stat_date IS
    '平台达人业绩统计自然日。';
COMMENT ON COLUMN dws.v_influencer_identity_resolved.stat_month IS
    '统计日期所属自然月首日。';
COMMENT ON COLUMN dws.v_influencer_identity_resolved.platform_code IS
    '来源平台标准编码。';
COMMENT ON COLUMN dws.v_influencer_identity_resolved.platform_name IS
    '来源平台展示名称。';
COMMENT ON COLUMN dws.v_influencer_identity_resolved.shop_code IS
    '来源标准店铺编码，不参与达人身份唯一性。';
COMMENT ON COLUMN dws.v_influencer_identity_resolved.shop_name IS
    '来源标准店铺名称，仅作展示属性。';
COMMENT ON COLUMN dws.v_influencer_identity_resolved.source_influencer_id IS
    '平台原始达人账号ID。';
COMMENT ON COLUMN dws.v_influencer_identity_resolved.source_influencer_name IS
    '平台订单中的达人昵称，允许随时间变化。';
COMMENT ON COLUMN dws.v_influencer_identity_resolved.source_influencer_key IS
    '平台DWS原有达人键，仅用于兼容审计。';
COMMENT ON COLUMN dws.v_influencer_identity_resolved.company_influencer_id IS
    '命中的公司统一达人ID；未映射时为空。';
COMMENT ON COLUMN dws.v_influencer_identity_resolved.company_influencer_name IS
    '公司统一达人名称；未映射时为空。';
COMMENT ON COLUMN dws.v_influencer_identity_resolved.influencer_identity_key IS
    '稳定事实身份键：已映射为company加公司达人ID，未映射为source加平台和来源UID。';
COMMENT ON COLUMN dws.v_influencer_identity_resolved.influencer_display_name IS
    '达人展示名称；优先公司统一名称，未映射时使用平台昵称。';
COMMENT ON COLUMN dws.v_influencer_identity_resolved.gmv_amount IS
    '平台DWS已确认口径的达人GMV，单位元。';
COMMENT ON COLUMN dws.v_influencer_identity_resolved.refund_amount IS
    '平台DWS已确认口径的达人退款金额，单位元。';
COMMENT ON COLUMN dws.v_influencer_identity_resolved.included_sub_order_count IS
    '平台DWS纳入的订单或商品行数量。';
COMMENT ON COLUMN dws.v_influencer_identity_resolved.source_updated_at IS
    '来源DWS最晚更新时间。';
