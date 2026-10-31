TRUNCATE TABLE dwd.dwd_douyin_settlement_expense_event_detail;

INSERT INTO dwd.dwd_douyin_settlement_expense_event_detail (
    source_id, platform_code, platform_name, shop_code, shop_name, shop_identity_key,
    shop_mapping_source, stat_date, settlement_at, order_no, sub_order_no,
    settlement_type, has_pre_settlement_refund, business_type, order_type,
    source_company_name, platform_service_fee_amount, creator_commission_amount,
    service_provider_commission_amount, channel_share_amount,
    merchant_recruitment_service_fee_amount, offsite_promotion_fee_amount,
    other_share_amount, expense_amount, source_batch_id, source_file_name,
    source_row_no, source_updated_at, updated_at
)
SELECT
    raw.id, 'douyin', '抖音', ctx.shop_code, ctx.shop_name, ctx.shop_identity_key,
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
    ROUND(-COALESCE(NULLIF(NULLIF(BTRIM(raw."平台服务费"), ''), '-')::numeric, 0), 2),
    ROUND(-COALESCE(NULLIF(NULLIF(BTRIM(raw."达人佣金"), ''), '-')::numeric, 0), 2),
    ROUND(-COALESCE(NULLIF(NULLIF(BTRIM(raw."服务商佣金"), ''), '-')::numeric, 0), 2),
    ROUND(-COALESCE(NULLIF(NULLIF(BTRIM(raw."渠道分成"), ''), '-')::numeric, 0), 2),
    ROUND(-COALESCE(NULLIF(NULLIF(BTRIM(raw."招商服务费"), ''), '-')::numeric, 0), 2),
    ROUND(-COALESCE(NULLIF(NULLIF(BTRIM(raw."站外推广费"), ''), '-')::numeric, 0), 2),
    ROUND(-COALESCE(NULLIF(NULLIF(BTRIM(raw."其他分成"), ''), '-')::numeric, 0), 2),
    ROUND(-COALESCE(NULLIF(NULLIF(BTRIM(raw."支出合计"), ''), '-')::numeric, 0), 2),
    raw.batch_id, raw.source_file_name, raw.source_row_no, raw.ingest_time, NOW()
FROM common.v_current_douyin_settlement_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'douyin'
   AND ctx.target_table = 'ods_douyin_settlement_raw'
   AND ctx.shop_mapping_status = 'mapped';

