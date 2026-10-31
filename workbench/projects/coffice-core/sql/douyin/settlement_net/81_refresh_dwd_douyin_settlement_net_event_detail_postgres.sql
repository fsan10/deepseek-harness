TRUNCATE TABLE dwd.dwd_douyin_settlement_net_event_detail;

INSERT INTO dwd.dwd_douyin_settlement_net_event_detail (
    source_id, platform_code, platform_name, shop_code, shop_name, shop_identity_key,
    shop_mapping_source, stat_date, settlement_at, order_no, sub_order_no,
    settlement_type, has_pre_settlement_refund, business_type, order_type,
    source_company_name, income_amount, expense_amount, settlement_net_amount,
    source_settlement_amount, validation_difference_amount, source_batch_id,
    source_file_name, source_row_no, source_updated_at, updated_at
)
WITH parsed AS (
    SELECT
        raw.*,
        ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."收入合计"), ''), '-')::numeric, 0), 2) AS parsed_income_amount,
        ROUND(-COALESCE(NULLIF(NULLIF(BTRIM(raw."支出合计"), ''), '-')::numeric, 0), 2) AS parsed_expense_amount,
        ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."结算金额"), ''), '-')::numeric, 0), 2) AS parsed_source_settlement_amount
    FROM common.v_current_douyin_settlement_raw raw
)
SELECT
    p.id, 'douyin', '抖音', ctx.shop_code, ctx.shop_name, ctx.shop_identity_key,
    ctx.shop_mapping_source,
    NULLIF(NULLIF(BTRIM(p."结算时间"), ''), '-')::timestamp::date,
    NULLIF(NULLIF(BTRIM(p."结算时间"), ''), '-')::timestamp,
    NULLIF(REPLACE(BTRIM(p."订单号"), '''', ''), ''),
    NULLIF(REPLACE(BTRIM(p."子订单号"), '''', ''), ''),
    NULLIF(BTRIM(p."结算单类型"), ''),
    NULLIF(BTRIM(p."有结算前退款"), ''),
    NULLIF(BTRIM(p."业务类型"), ''),
    NULLIF(BTRIM(p."订单类型"), ''),
    NULLIF(BTRIM(p."商户主体名称"), ''),
    p.parsed_income_amount,
    p.parsed_expense_amount,
    ROUND(p.parsed_income_amount - p.parsed_expense_amount, 2),
    p.parsed_source_settlement_amount,
    ROUND(p.parsed_income_amount - p.parsed_expense_amount - p.parsed_source_settlement_amount, 2),
    p.batch_id, p.source_file_name, p.source_row_no, p.ingest_time, NOW()
FROM parsed p
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = p.batch_id
   AND ctx.platform_code = 'douyin'
   AND ctx.target_table = 'ods_douyin_settlement_raw'
   AND ctx.shop_mapping_status = 'mapped';

