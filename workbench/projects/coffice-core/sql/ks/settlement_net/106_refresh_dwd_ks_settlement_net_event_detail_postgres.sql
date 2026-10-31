TRUNCATE TABLE dwd.dwd_ks_settlement_net_event_detail;

INSERT INTO dwd.dwd_ks_settlement_net_event_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, settlement_at,
    merchant_id, order_no, product_id, commission_mode, settlement_rule,
    fund_channel, income_amount, expense_amount, settlement_net_amount,
    source_settlement_amount, validation_difference_amount, source_batch_id,
    source_file_name, source_row_no, source_updated_at, updated_at
)
WITH parsed AS (
    SELECT
        raw.*,
        ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."合计收入(元)"), ''), '-')::numeric, 0), 2) AS parsed_income_amount,
        ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."合计支出(元)"), ''), '-')::numeric, 0), 2) AS parsed_expense_amount,
        ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."实际结算金额(元)"), ''), '-')::numeric, 0), 2) AS parsed_source_settlement_amount
    FROM common.v_current_ks_settlement_raw raw
)
SELECT
    p.id, 'ks', '快手', ctx.shop_code, ctx.shop_name,
    ctx.shop_identity_key, ctx.shop_mapping_source,
    NULLIF(NULLIF(BTRIM(p."实际结算时间"), ''), '-')::timestamp::date,
    NULLIF(NULLIF(BTRIM(p."实际结算时间"), ''), '-')::timestamp,
    NULLIF(BTRIM(p."商家ID"), ''),
    NULLIF(BTRIM(p."订单号"), ''),
    NULLIF(BTRIM(p."商品ID"), ''),
    NULLIF(BTRIM(p."佣金模式"), ''),
    NULLIF(BTRIM(p."结算规则"), ''),
    NULLIF(BTRIM(p."资金渠道"), ''),
    p.parsed_income_amount,
    p.parsed_expense_amount,
    ROUND(p.parsed_income_amount - p.parsed_expense_amount, 2),
    p.parsed_source_settlement_amount,
    ROUND(p.parsed_income_amount - p.parsed_expense_amount - p.parsed_source_settlement_amount, 2),
    p.batch_id, p.source_file_name, p.source_row_no, p.ingest_time, NOW()
FROM parsed p
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = p.batch_id
   AND ctx.platform_code = 'ks'
   AND ctx.target_table = 'ods_ks_settlement_raw'
   AND ctx.shop_mapping_status = 'mapped';

