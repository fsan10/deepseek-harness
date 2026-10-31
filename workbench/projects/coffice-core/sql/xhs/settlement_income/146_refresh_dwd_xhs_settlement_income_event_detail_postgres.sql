TRUNCATE TABLE dwd.dwd_xhs_settlement_income_event_detail;

INSERT INTO dwd.dwd_xhs_settlement_income_event_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, settled_at, order_no,
    after_sale_no, transaction_type, settlement_account, income_amount,
    commission_base_amount, product_paid_refund_amount, freight_paid_refund_amount,
    merchant_discount_amount, platform_subsidy_amount, government_subsidy_amount,
    platform_commission_amount, buyer_commission_amount, installment_fee_amount,
    component_check_amount, component_difference_amount, source_batch_id,
    source_file_name, source_sheet_name, source_row_no, source_updated_at, updated_at
)
WITH parsed AS (
    SELECT
        raw.*,
        ROUND(BTRIM(raw."动账金额")::numeric, 2) AS parsed_income_amount,
        ROUND(BTRIM(raw."商品实付/实退")::numeric
            + BTRIM(raw."运费实付/实退")::numeric
            - BTRIM(raw."商家优惠总额")::numeric
            + BTRIM(raw."平台优惠补贴")::numeric
            + BTRIM(raw."政府券优惠补贴")::numeric
            + BTRIM(raw."平台佣金")::numeric
            + BTRIM(raw."买手佣金")::numeric
            + BTRIM(raw."花呗分期手续费")::numeric, 2) AS parsed_component_amount
    FROM common.v_current_xhs_settlement_income_raw raw
)
SELECT
    p.id, 'xhs', '小红书', ctx.shop_code, ctx.shop_name,
    ctx.shop_identity_key, ctx.shop_mapping_source,
    BTRIM(p."结算时间")::timestamp::date,
    BTRIM(p."结算时间")::timestamp,
    NULLIF(BTRIM(p."订单号"), ''),
    NULLIF(NULLIF(BTRIM(p."售后单号"), ''), '-'),
    NULLIF(BTRIM(p."交易类型"), ''),
    NULLIF(BTRIM(p."结算账户"), ''),
    p.parsed_income_amount,
    ROUND(BTRIM(p."计佣基数")::numeric, 2),
    ROUND(BTRIM(p."商品实付/实退")::numeric, 2),
    ROUND(BTRIM(p."运费实付/实退")::numeric, 2),
    ROUND(BTRIM(p."商家优惠总额")::numeric, 2),
    ROUND(BTRIM(p."平台优惠补贴")::numeric, 2),
    ROUND(BTRIM(p."政府券优惠补贴")::numeric, 2),
    ROUND(BTRIM(p."平台佣金")::numeric, 2),
    ROUND(BTRIM(p."买手佣金")::numeric, 2),
    ROUND(BTRIM(p."花呗分期手续费")::numeric, 2),
    p.parsed_component_amount,
    ROUND(p.parsed_income_amount - p.parsed_component_amount, 2),
    p.batch_id, p.source_file_name, p.source_sheet_name,
    p.source_row_no, p.ingest_time, NOW()
FROM parsed p
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = p.batch_id
   AND ctx.platform_code = 'xhs'
   AND ctx.target_table = 'ods_xhs_settlement_income_raw'
   AND ctx.shop_mapping_status = 'mapped';

INSERT INTO dwd.dwd_xhs_settlement_income_event_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, settled_at, order_no,
    after_sale_no, transaction_type, settlement_account, income_amount,
    commission_base_amount, product_paid_refund_amount, freight_paid_refund_amount,
    merchant_discount_amount, platform_subsidy_amount, government_subsidy_amount,
    platform_commission_amount, buyer_commission_amount, installment_fee_amount,
    component_check_amount, component_difference_amount, source_batch_id,
    source_file_name, source_sheet_name, source_row_no, source_updated_at, updated_at
)
SELECT
    -raw.id, 'xhs', '小红书', ctx.shop_code, ctx.shop_name,
    ctx.shop_identity_key, ctx.shop_mapping_source,
    BTRIM(raw."结算时间")::timestamp::date,
    BTRIM(raw."结算时间")::timestamp,
    COALESCE(
        NULLIF(NULLIF(BTRIM(raw."业务单号"), ''), '-'),
        '申诉调账:' || raw.id::text
    ),
    NULL,
    '申诉调账',
    NULLIF(BTRIM(raw."结算账户"), ''),
    ROUND(BTRIM(raw."动账金额")::numeric, 2),
    0, 0, 0, 0, 0, 0, 0, 0, 0,
    ROUND(BTRIM(raw."动账金额")::numeric, 2),
    0,
    raw.batch_id, raw.source_file_name, raw.source_sheet_name,
    raw.source_row_no, raw.ingest_time, NOW()
FROM common.v_current_xhs_settlement_expense_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'xhs'
   AND ctx.target_table = 'ods_xhs_settlement_expense_raw'
   AND ctx.shop_mapping_status = 'mapped'
WHERE BTRIM(raw."业务款项") = '申诉调账';
