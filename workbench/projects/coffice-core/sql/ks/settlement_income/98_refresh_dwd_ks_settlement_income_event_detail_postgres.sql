TRUNCATE TABLE dwd.dwd_ks_settlement_income_event_detail;

INSERT INTO dwd.dwd_ks_settlement_income_event_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, settlement_at,
    merchant_id, order_no, product_id, commission_mode, settlement_rule,
    fund_channel, order_paid_amount, government_subsidy_amount,
    payment_marketing_subsidy_amount, platform_subsidy_amount,
    merchant_subsidy_amount, talent_subsidy_amount, income_amount,
    source_batch_id, source_file_name, source_row_no, source_updated_at, updated_at
)
SELECT
    raw.id, 'ks', '快手', ctx.shop_code, ctx.shop_name,
    ctx.shop_identity_key, ctx.shop_mapping_source,
    NULLIF(NULLIF(BTRIM(raw."实际结算时间"), ''), '-')::timestamp::date,
    NULLIF(NULLIF(BTRIM(raw."实际结算时间"), ''), '-')::timestamp,
    NULLIF(BTRIM(raw."商家ID"), ''),
    NULLIF(BTRIM(raw."订单号"), ''),
    NULLIF(BTRIM(raw."商品ID"), ''),
    NULLIF(BTRIM(raw."佣金模式"), ''),
    NULLIF(BTRIM(raw."结算规则"), ''),
    NULLIF(BTRIM(raw."资金渠道"), ''),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."订单实付(元)"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."政府补贴"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."支付营销补贴"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."平台补贴"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."商家补贴(元)"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."达人补贴"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."合计收入(元)"), ''), '-')::numeric, 0), 2),
    raw.batch_id, raw.source_file_name, raw.source_row_no, raw.ingest_time, NOW()
FROM common.v_current_ks_settlement_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'ks'
   AND ctx.target_table = 'ods_ks_settlement_raw'
   AND ctx.shop_mapping_status = 'mapped';

