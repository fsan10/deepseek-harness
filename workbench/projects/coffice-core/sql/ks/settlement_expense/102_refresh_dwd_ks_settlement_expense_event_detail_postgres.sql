TRUNCATE TABLE dwd.dwd_ks_settlement_expense_event_detail;

INSERT INTO dwd.dwd_ks_settlement_expense_event_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, settlement_at,
    merchant_id, order_no, product_id, commission_mode, settlement_rule,
    fund_channel, order_refund_amount, payment_marketing_rollback_amount,
    technical_service_fee_amount, presale_technical_service_fee_amount,
    talent_commission_amount, leader_commission_amount,
    earner_commission_amount, service_provider_commission_amount,
    other_fee_amount, other_fee_detail, expense_amount, source_batch_id,
    source_file_name, source_row_no, source_updated_at, updated_at
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
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."订单退款(元)"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."支付营销回退（元）"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."技术服务费(元)"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."预售增收技术服务费（元）"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."达人佣金(元)"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."团长佣金(元)"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."快赚客佣金(元)"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."服务商佣金(元)"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."其他收费"), ''), '-')::numeric, 0), 2),
    NULLIF(BTRIM(raw."其他收费明细"), ''),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."合计支出(元)"), ''), '-')::numeric, 0), 2),
    raw.batch_id, raw.source_file_name, raw.source_row_no, raw.ingest_time, NOW()
FROM common.v_current_ks_settlement_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'ks'
   AND ctx.target_table = 'ods_ks_settlement_raw'
   AND ctx.shop_mapping_status = 'mapped';

