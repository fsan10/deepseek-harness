TRUNCATE TABLE dwd.dwd_douyin_settlement_income_event_detail;

INSERT INTO dwd.dwd_douyin_settlement_income_event_detail (
    source_id, platform_code, platform_name, shop_code, shop_name, shop_identity_key,
    shop_mapping_source, stat_date, settlement_at, order_no, sub_order_no,
    settlement_type, has_pre_settlement_refund, business_type, order_type,
    source_company_name, user_payment_amount, platform_subsidy_amount,
    other_platform_subsidy_amount, government_platform_advance_amount,
    creator_subsidy_amount, douyin_pay_subsidy_amount,
    douyin_monthly_pay_subsidy_amount, bank_subsidy_amount,
    trade_in_deduction_amount, platform_shipping_subsidy_amount, income_amount,
    source_batch_id, source_file_name, source_row_no, source_updated_at, updated_at
)
SELECT
    raw.id,
    'douyin',
    '抖音',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    NULLIF(NULLIF(BTRIM(raw."结算时间"), ''), '-')::timestamp::date,
    NULLIF(NULLIF(BTRIM(raw."结算时间"), ''), '-')::timestamp,
    NULLIF(REPLACE(BTRIM(raw."订单号"), '''', ''), ''),
    NULLIF(REPLACE(BTRIM(raw."子订单号"), '''', ''), ''),
    NULLIF(BTRIM(raw."结算单类型"), ''),
    NULLIF(BTRIM(raw."有结算前退款"), ''),
    NULLIF(BTRIM(raw."业务类型"), ''),
    NULLIF(BTRIM(raw."订单类型"), ''),
    NULLIF(BTRIM(raw."商户主体名称"), ''),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."用户实付"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."平台补贴"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."其他平台补贴"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."政府补贴平台垫资"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."达人补贴"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."抖音支付补贴"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."抖音月付营销补贴"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."银行补贴"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."以旧换新抵扣"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."平台补贴运费"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."收入合计"), ''), '-')::numeric, 0), 2),
    raw.batch_id,
    raw.source_file_name,
    raw.source_row_no,
    raw.ingest_time,
    NOW()
FROM common.v_current_douyin_settlement_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'douyin'
   AND ctx.target_table = 'ods_douyin_settlement_raw'
   AND ctx.shop_mapping_status = 'mapped';

