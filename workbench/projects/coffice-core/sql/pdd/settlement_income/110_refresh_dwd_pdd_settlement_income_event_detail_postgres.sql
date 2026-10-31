TRUNCATE TABLE dwd.dwd_pdd_settlement_income_event_detail;

INSERT INTO dwd.dwd_pdd_settlement_income_event_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, occurred_at,
    merchant_order_no, account_type, remark, business_description,
    income_amount, source_signed_expense_amount, source_batch_id, source_file_name, source_row_no,
    source_updated_at, updated_at
)
SELECT
    raw.id, 'pdd', '拼多多', ctx.shop_code, ctx.shop_name,
    ctx.shop_identity_key, ctx.shop_mapping_source,
    NULLIF(NULLIF(BTRIM(raw."发生时间"), ''), '-')::timestamp::date,
    NULLIF(NULLIF(BTRIM(raw."发生时间"), ''), '-')::timestamp,
    NULLIF(BTRIM(raw."商户订单号"), ''),
    NULLIF(BTRIM(raw."账务类型"), ''),
    NULLIF(BTRIM(raw."备注"), ''),
    NULLIF(BTRIM(raw."业务描述"), ''),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."收入金额（+元）"), ''), '-')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."支出金额（-元）"), ''), '-')::numeric, 0), 2),
    raw.batch_id, raw.source_file_name, raw.source_row_no, raw.ingest_time, NOW()
FROM common.v_current_pdd_settlement_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'pdd'
   AND ctx.target_table = 'ods_pdd_settlement_raw'
   AND ctx.shop_mapping_status = 'mapped';

