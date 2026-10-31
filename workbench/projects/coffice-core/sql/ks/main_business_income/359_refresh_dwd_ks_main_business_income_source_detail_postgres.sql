TRUNCATE TABLE dwd.dwd_ks_main_business_income_source_detail;

WITH parsed AS (
    SELECT
        raw.*,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."订单实付(元)"), ',', ''), ''), '-')::numeric, 0), 2)
            AS order_paid_amount,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."政府补贴"), ',', ''), ''), '-')::numeric, 0), 2)
            AS government_subsidy_amount,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."支付营销补贴"), ',', ''), ''), '-')::numeric, 0), 2)
            AS payment_marketing_subsidy_amount,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."平台补贴"), ',', ''), ''), '-')::numeric, 0), 2)
            AS platform_subsidy_amount,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."达人补贴"), ',', ''), ''), '-')::numeric, 0), 2)
            AS talent_subsidy_amount,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."商家补贴(元)"), ',', ''), ''), '-')::numeric, 0), 2)
            AS merchant_subsidy_amount,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."订单退款(元)"), ',', ''), ''), '-')::numeric, 0), 2)
            AS order_refund_amount,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."合计收入(元)"), ',', ''), ''), '-')::numeric, 0), 2)
            AS source_income_amount
    FROM common.v_current_ks_settlement_raw raw
)
INSERT INTO dwd.dwd_ks_main_business_income_source_detail (
    source_document_type,
    source_id,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    shop_identity_key,
    shop_mapping_source,
    stat_date,
    event_at,
    source_direction,
    source_business_type,
    source_description,
    flow_no,
    order_no,
    related_order_no,
    order_paid_amount,
    government_subsidy_amount,
    payment_marketing_subsidy_amount,
    platform_subsidy_amount,
    talent_subsidy_amount,
    merchant_subsidy_amount,
    order_refund_amount,
    source_income_amount,
    settlement_formula_income_amount,
    signed_fund_amount,
    source_batch_id,
    source_file_name,
    source_row_no,
    source_updated_at,
    updated_at
)
SELECT
    'settlement',
    p.id,
    'ks',
    '快手',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    NULLIF(NULLIF(BTRIM(p."实际结算时间"), ''), '-')::timestamp::date,
    NULLIF(NULLIF(BTRIM(p."实际结算时间"), ''), '-')::timestamp,
    '结算',
    NULL,
    NULL,
    NULL,
    NULLIF(BTRIM(p."订单号", E' \t\r\n'), ''),
    NULL,
    p.order_paid_amount,
    p.government_subsidy_amount,
    p.payment_marketing_subsidy_amount,
    p.platform_subsidy_amount,
    p.talent_subsidy_amount,
    p.merchant_subsidy_amount,
    p.order_refund_amount,
    p.source_income_amount,
    ROUND(
        p.order_paid_amount
        + p.government_subsidy_amount
        + p.payment_marketing_subsidy_amount
        + p.platform_subsidy_amount
        + p.talent_subsidy_amount
        - p.merchant_subsidy_amount
        - p.order_refund_amount,
        2
    ),
    0,
    p.batch_id,
    p.source_file_name,
    p.source_row_no,
    p.ingest_time,
    NOW()
FROM parsed p
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = p.batch_id
   AND ctx.platform_code = 'ks'
   AND ctx.target_table = 'ods_ks_settlement_raw'
   AND ctx.shop_mapping_status = 'mapped';

WITH parsed AS (
    SELECT
        raw.*,
        ROUND(
            COALESCE(
                NULLIF(
                    NULLIF(REPLACE(BTRIM(raw."发生额（元）"), ',', ''), ''),
                    '-'
                )::numeric,
                0
            ),
            2
        ) AS source_amount
    FROM common.v_current_ks_fund_raw raw
)
INSERT INTO dwd.dwd_ks_main_business_income_source_detail (
    source_document_type,
    source_id,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    shop_identity_key,
    shop_mapping_source,
    stat_date,
    event_at,
    source_direction,
    source_business_type,
    source_description,
    flow_no,
    order_no,
    related_order_no,
    order_paid_amount,
    government_subsidy_amount,
    payment_marketing_subsidy_amount,
    platform_subsidy_amount,
    talent_subsidy_amount,
    merchant_subsidy_amount,
    order_refund_amount,
    source_income_amount,
    settlement_formula_income_amount,
    signed_fund_amount,
    source_batch_id,
    source_file_name,
    source_row_no,
    source_updated_at,
    updated_at
)
SELECT
    'fund',
    p.id,
    'ks',
    '快手',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    NULLIF(NULLIF(BTRIM(p."入账时间"), ''), '-')::timestamp::date,
    NULLIF(NULLIF(BTRIM(p."入账时间"), ''), '-')::timestamp,
    BTRIM(p."账务方向"),
    NULLIF(BTRIM(p."业务类型"), ''),
    NULLIF(BTRIM(p."描述"), ''),
    NULLIF(BTRIM(p."账务流水号"), ''),
    NULL,
    NULLIF(BTRIM(p."关联业务单号", E' \t\r\n'), ''),
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    CASE BTRIM(p."账务方向")
        WHEN '收' THEN p.source_amount
        WHEN '支' THEN -p.source_amount
    END,
    p.batch_id,
    p.source_file_name,
    p.source_row_no,
    p.ingest_time,
    NOW()
FROM parsed p
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = p.batch_id
   AND ctx.platform_code = 'ks'
   AND ctx.target_table = 'ods_ks_fund_raw'
   AND ctx.shop_mapping_status = 'mapped';
