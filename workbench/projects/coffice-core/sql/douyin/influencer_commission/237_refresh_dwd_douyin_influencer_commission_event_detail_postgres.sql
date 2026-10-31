TRUNCATE TABLE dwd.dwd_douyin_influencer_commission_event_detail;

INSERT INTO dwd.dwd_douyin_influencer_commission_event_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, movement_at, flow_no,
    order_no, sub_order_no, influencer_id, influencer_name, movement_direction,
    movement_account, movement_scenario, billing_type, order_type, source_company_name,
    creator_commission_source_amount, recruitment_service_fee_source_amount,
    creator_commission_amount, recruitment_service_fee_amount,
    source_batch_id, source_file_name, source_row_no, source_updated_at, updated_at
)
WITH ranked_fund AS (
    SELECT
        raw.*,
        ctx.shop_code AS standard_shop_code,
        ctx.shop_name AS standard_shop_name,
        ctx.shop_identity_key AS standard_shop_identity_key,
        ctx.shop_mapping_source AS standard_shop_mapping_source,
        NULLIF(LTRIM(BTRIM(raw."动帐流水号"), CHR(39)), '') AS standard_flow_no,
        ROW_NUMBER() OVER (
            PARTITION BY
                ctx.shop_identity_key,
                NULLIF(LTRIM(BTRIM(raw."动帐流水号"), CHR(39)), '')
            ORDER BY raw.batch_id DESC, raw.id DESC
        ) AS version_rank
    FROM ods.ods_douyin_fund_raw raw
    INNER JOIN common.v_ingest_batch_shop_context ctx
        ON ctx.batch_id = raw.batch_id
       AND ctx.platform_code = 'douyin'
       AND ctx.target_table = 'ods_douyin_fund_raw'
       AND ctx.shop_mapping_status = 'mapped'
       AND ctx.ingest_status = 'success'
)
SELECT
    raw.id,
    'douyin',
    '抖音',
    raw.standard_shop_code,
    raw.standard_shop_name,
    raw.standard_shop_identity_key,
    raw.standard_shop_mapping_source,
    NULLIF(NULLIF(BTRIM(raw."动账时间"), ''), '-')::timestamp::date,
    NULLIF(NULLIF(BTRIM(raw."动账时间"), ''), '-')::timestamp,
    raw.standard_flow_no,
    NULLIF(REPLACE(BTRIM(raw."订单号"), '''', ''), ''),
    NULLIF(REPLACE(BTRIM(raw."子订单号"), '''', ''), ''),
    NULLIF(REPLACE(BTRIM(raw."达人ID"), '''', ''), ''),
    NULLIF(BTRIM(raw."达人名称"), ''),
    NULLIF(BTRIM(raw."动账方向"), ''),
    NULLIF(BTRIM(raw."动账账户"), ''),
    NULLIF(BTRIM(raw."动账场景"), ''),
    NULLIF(BTRIM(raw."计费类型"), ''),
    NULLIF(BTRIM(raw."订单类型"), ''),
    NULLIF(BTRIM(raw."商户主体名称"), ''),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."佣金"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."招商服务费"), ''), '-')::numeric, 0), 2),
    ROUND(-COALESCE(NULLIF(NULLIF(BTRIM(raw."佣金"), ''), '-')::numeric, 0), 2),
    ROUND(-COALESCE(NULLIF(NULLIF(BTRIM(raw."招商服务费"), ''), '-')::numeric, 0), 2),
    raw.batch_id,
    raw.source_file_name,
    raw.source_row_no,
    raw.ingest_time,
    NOW()
FROM ranked_fund raw
WHERE raw.version_rank = 1;

ALTER TABLE dwd.dwd_douyin_influencer_commission_event_detail
    ALTER COLUMN flow_no SET NOT NULL;
