TRUNCATE TABLE dwd.dwd_douyin_main_business_income_source_detail;

WITH parsed AS (
    SELECT
        raw.*,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."用户实付"), ',', ''), ''), '-')::numeric, 0), 2)
            AS user_payment_amount,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."平台补贴"), ',', ''), ''), '-')::numeric, 0), 2)
            AS platform_subsidy_amount,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."其他平台补贴"), ',', ''), ''), '-')::numeric, 0), 2)
            AS other_platform_subsidy_amount,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."政府补贴平台垫资"), ',', ''), ''), '-')::numeric, 0), 2)
            AS government_platform_advance_amount,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."达人补贴"), ',', ''), ''), '-')::numeric, 0), 2)
            AS talent_subsidy_amount,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."抖音支付补贴"), ',', ''), ''), '-')::numeric, 0), 2)
            AS douyin_pay_subsidy_amount,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."抖音月付营销补贴"), ',', ''), ''), '-')::numeric, 0), 2)
            AS douyin_monthly_pay_subsidy_amount,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."银行补贴"), ',', ''), ''), '-')::numeric, 0), 2)
            AS bank_subsidy_amount,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."以旧换新抵扣"), ',', ''), ''), '-')::numeric, 0), 2)
            AS trade_in_deduction_amount,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."平台补贴运费"), ',', ''), ''), '-')::numeric, 0), 2)
            AS platform_shipping_subsidy_amount,
        ROUND(COALESCE(NULLIF(NULLIF(REPLACE(BTRIM(raw."收入合计"), ',', ''), ''), '-')::numeric, 0), 2)
            AS source_income_amount
    FROM common.v_current_douyin_settlement_raw raw
)
INSERT INTO dwd.dwd_douyin_main_business_income_source_detail (
    source_id,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    shop_identity_key,
    shop_mapping_source,
    stat_date,
    event_at,
    order_no,
    sub_order_no,
    settlement_type,
    has_pre_settlement_refund,
    business_type,
    order_type,
    user_payment_amount,
    platform_subsidy_amount,
    other_platform_subsidy_amount,
    government_platform_advance_amount,
    talent_subsidy_amount,
    douyin_pay_subsidy_amount,
    douyin_monthly_pay_subsidy_amount,
    bank_subsidy_amount,
    trade_in_deduction_amount,
    platform_shipping_subsidy_amount,
    source_income_amount,
    component_income_amount,
    reconciliation_difference,
    source_batch_id,
    source_file_name,
    source_row_no,
    source_updated_at,
    updated_at
)
SELECT
    p.id,
    'douyin',
    '抖音',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    NULLIF(NULLIF(BTRIM(p."结算时间"), ''), '-')::timestamp::date,
    NULLIF(NULLIF(BTRIM(p."结算时间"), ''), '-')::timestamp,
    NULLIF(REPLACE(BTRIM(p."订单号"), '''', ''), ''),
    NULLIF(REPLACE(BTRIM(p."子订单号"), '''', ''), ''),
    NULLIF(BTRIM(p."结算单类型"), ''),
    NULLIF(BTRIM(p."有结算前退款"), ''),
    NULLIF(BTRIM(p."业务类型"), ''),
    NULLIF(BTRIM(p."订单类型"), ''),
    p.user_payment_amount,
    p.platform_subsidy_amount,
    p.other_platform_subsidy_amount,
    p.government_platform_advance_amount,
    p.talent_subsidy_amount,
    p.douyin_pay_subsidy_amount,
    p.douyin_monthly_pay_subsidy_amount,
    p.bank_subsidy_amount,
    p.trade_in_deduction_amount,
    p.platform_shipping_subsidy_amount,
    p.source_income_amount,
    ROUND(
        p.user_payment_amount
        + p.platform_subsidy_amount
        + p.other_platform_subsidy_amount
        + p.government_platform_advance_amount
        + p.talent_subsidy_amount
        + p.douyin_pay_subsidy_amount
        + p.douyin_monthly_pay_subsidy_amount
        + p.bank_subsidy_amount
        + p.trade_in_deduction_amount
        + p.platform_shipping_subsidy_amount,
        2
    ),
    ROUND(
        p.source_income_amount
        - (
            p.user_payment_amount
            + p.platform_subsidy_amount
            + p.other_platform_subsidy_amount
            + p.government_platform_advance_amount
            + p.talent_subsidy_amount
            + p.douyin_pay_subsidy_amount
            + p.douyin_monthly_pay_subsidy_amount
            + p.bank_subsidy_amount
            + p.trade_in_deduction_amount
            + p.platform_shipping_subsidy_amount
        ),
        2
    ),
    p.batch_id,
    p.source_file_name,
    p.source_row_no,
    p.ingest_time,
    NOW()
FROM parsed p
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = p.batch_id
   AND ctx.platform_code = 'douyin'
   AND ctx.target_table = 'ods_douyin_settlement_raw'
   AND ctx.shop_mapping_status = 'mapped';
