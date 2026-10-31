TRUNCATE TABLE dwd.dwd_tmall_settlement_income_event_detail;

INSERT INTO dwd.dwd_tmall_settlement_income_event_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, bill_period_raw,
    bill_category, business_category, business_subcategory, order_no,
    sub_order_no, business_flow_no, merchant_order_no, payment_channel,
    paid_at, paid_updated_at, order_actual_amount, refund_amount,
    source_batch_id, source_file_name, source_row_no, source_updated_at, updated_at
)
SELECT
    raw.id, 'tmall', '天猫', ctx.shop_code, ctx.shop_name,
    ctx.shop_identity_key, ctx.shop_mapping_source,
    TO_DATE(BTRIM(raw."账期"), 'YYYYMMDD'), BTRIM(raw."账期"),
    NULLIF(BTRIM(raw."账单大类"), ''),
    NULLIF(BTRIM(raw."业务大类"), ''),
    NULLIF(BTRIM(raw."业务小类"), ''),
    NULLIF(BTRIM(raw."订单号"), ''),
    NULLIF(BTRIM(raw."子订单号"), ''),
    NULLIF(BTRIM(raw."业务流水号"), ''),
    NULLIF(BTRIM(raw."商户订单号"), ''),
    NULLIF(BTRIM(raw."收/付渠道"), ''),
    NULLIF(NULLIF(BTRIM(raw."打款时间"), ''), '-')::timestamp,
    NULLIF(NULLIF(BTRIM(raw."打款更新时间"), ''), '-')::timestamp,
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."订单实际金额（元）"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."退款金额（元）"), ''), '-')::numeric, 0), 2),
    raw.batch_id, raw.source_file_name, raw.source_row_no, raw.ingest_time, NOW()
FROM ods.ods_tmall_settlement_income_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'tmall'
   AND ctx.target_table = 'ods_tmall_settlement_income_raw'
   AND ctx.shop_mapping_status = 'mapped';

