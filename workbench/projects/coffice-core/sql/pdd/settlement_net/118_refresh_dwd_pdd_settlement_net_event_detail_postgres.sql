TRUNCATE TABLE dwd.dwd_pdd_settlement_net_event_detail;

INSERT INTO dwd.dwd_pdd_settlement_net_event_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, occurred_at,
    merchant_order_no, account_type, remark, business_description,
    income_amount, source_signed_expense_amount, expense_amount,
    settlement_net_amount, source_settlement_amount,
    validation_difference_amount, source_batch_id, source_file_name,
    source_row_no, source_updated_at, updated_at
)
WITH parsed AS (
    SELECT
        raw.*,
        ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."收入金额（+元）"), ''), '-')::numeric, 0), 2) AS parsed_income_amount,
        ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."支出金额（-元）"), ''), '-')::numeric, 0), 2) AS parsed_signed_expense_amount
    FROM common.v_current_pdd_settlement_raw raw
)
SELECT
    p.id, 'pdd', '拼多多', ctx.shop_code, ctx.shop_name,
    ctx.shop_identity_key, ctx.shop_mapping_source,
    NULLIF(NULLIF(BTRIM(p."发生时间"), ''), '-')::timestamp::date,
    NULLIF(NULLIF(BTRIM(p."发生时间"), ''), '-')::timestamp,
    NULLIF(BTRIM(p."商户订单号"), ''),
    NULLIF(BTRIM(p."账务类型"), ''),
    NULLIF(BTRIM(p."备注"), ''),
    NULLIF(BTRIM(p."业务描述"), ''),
    p.parsed_income_amount,
    p.parsed_signed_expense_amount,
    -p.parsed_signed_expense_amount,
    ROUND(p.parsed_income_amount - (-p.parsed_signed_expense_amount), 2),
    ROUND(p.parsed_income_amount + p.parsed_signed_expense_amount, 2),
    ROUND(
        p.parsed_income_amount - (-p.parsed_signed_expense_amount)
        - (p.parsed_income_amount + p.parsed_signed_expense_amount), 2
    ),
    p.batch_id, p.source_file_name, p.source_row_no, p.ingest_time, NOW()
FROM parsed p
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = p.batch_id
   AND ctx.platform_code = 'pdd'
   AND ctx.target_table = 'ods_pdd_settlement_raw'
   AND ctx.shop_mapping_status = 'mapped';

