TRUNCATE TABLE dwd.dwd_xhs_main_business_income_source_detail;
TRUNCATE TABLE dwd.dwd_xhs_platform_expense_source_detail;

WITH cleaned AS (
    SELECT
        raw.*,
        NULLIF(BTRIM(raw."订单号"), '') AS clean_order_no,
        NULLIF(BTRIM(raw."售后单号"), '') AS clean_after_sale_no,
        BTRIM(raw."交易类型") AS clean_business_type,
        NULLIF(BTRIM(raw."结算时间"), '')::timestamp AS parsed_event_at,
        ROUND(REPLACE(BTRIM(raw."动账金额"), ',', '')::numeric, 2) AS parsed_net_amount,
        ROUND(REPLACE(BTRIM(raw."平台佣金"), ',', '')::numeric, 2) AS parsed_platform_commission,
        ROUND(REPLACE(BTRIM(raw."买手佣金"), ',', '')::numeric, 2) AS parsed_buyer_commission,
        ROUND(REPLACE(BTRIM(raw."花呗分期手续费"), ',', '')::numeric, 2) AS parsed_installment_fee
    FROM common.v_current_xhs_settlement_income_raw raw
)
INSERT INTO dwd.dwd_xhs_main_business_income_source_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, event_at, order_no,
    after_sale_no, source_business_type, secondary_category_name,
    source_net_amount, platform_commission_amount, buyer_commission_amount,
    installment_fee_amount, restored_income_amount, source_batch_id,
    source_file_name, source_row_no, source_row_hash, source_updated_at, updated_at
)
SELECT
    c.id, 'xhs', '小红书', ctx.shop_code, ctx.shop_name,
    ctx.shop_identity_key, ctx.shop_mapping_source, c.parsed_event_at::date,
    c.parsed_event_at, c.clean_order_no, c.clean_after_sale_no,
    c.clean_business_type, c.clean_business_type, c.parsed_net_amount,
    c.parsed_platform_commission, c.parsed_buyer_commission,
    c.parsed_installment_fee,
    ROUND(c.parsed_net_amount - c.parsed_platform_commission
        - c.parsed_buyer_commission - c.parsed_installment_fee, 2),
    c.batch_id, c.source_file_name, c.source_row_no, c.row_hash,
    c.ingest_time, NOW()
FROM cleaned c
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id=c.batch_id
   AND ctx.platform_code='xhs'
   AND ctx.target_table='ods_xhs_settlement_income_raw'
   AND ctx.shop_mapping_status='mapped';

WITH cleaned AS (
    SELECT
        raw.*,
        NULLIF(BTRIM(raw."业务单号"), '') AS clean_business_no,
        BTRIM(raw."业务款项") AS clean_business_type,
        NULLIF(BTRIM(raw."结算时间"), '')::timestamp AS parsed_event_at,
        ROUND(REPLACE(BTRIM(raw."动账金额"), ',', '')::numeric, 2) AS parsed_signed_amount
    FROM common.v_current_xhs_settlement_expense_raw raw
)
INSERT INTO dwd.dwd_xhs_main_business_income_source_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, event_at, order_no,
    after_sale_no, source_business_type, secondary_category_name,
    source_net_amount, platform_commission_amount, buyer_commission_amount,
    installment_fee_amount, restored_income_amount, source_batch_id,
    source_file_name, source_row_no, source_row_hash, source_updated_at, updated_at
)
SELECT
    -c.id, 'xhs', '小红书', ctx.shop_code, ctx.shop_name,
    ctx.shop_identity_key, ctx.shop_mapping_source, c.parsed_event_at::date,
    c.parsed_event_at, COALESCE(NULLIF(c.clean_business_no, '-'), '申诉调账:' || c.id::text),
    NULL, '申诉调账', '申诉调账收入',
    c.parsed_signed_amount, 0, 0, 0, c.parsed_signed_amount,
    c.batch_id, c.source_file_name, c.source_row_no, c.row_hash,
    c.ingest_time, NOW()
FROM cleaned c
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id=c.batch_id
   AND ctx.platform_code='xhs'
   AND ctx.target_table='ods_xhs_settlement_expense_raw'
   AND ctx.shop_mapping_status='mapped'
WHERE c.clean_business_type='申诉调账';

INSERT INTO dwd.dwd_xhs_platform_expense_source_detail (
    source_table, source_id, source_component_code, platform_code,
    platform_name, shop_code, shop_name, shop_identity_key,
    shop_mapping_source, stat_date, event_at, order_no,
    source_business_type, secondary_category_name, signed_amount,
    directional_expense_amount, source_batch_id, source_file_name,
    source_row_no, source_row_hash, source_updated_at, updated_at
)
SELECT
    'income', d.source_id, component.component_code, d.platform_code,
    d.platform_name, d.shop_code, d.shop_name, d.shop_identity_key,
    d.shop_mapping_source, d.stat_date, d.event_at, d.order_no,
    d.source_business_type, component.category_name, component.signed_amount,
    -component.signed_amount, d.source_batch_id, d.source_file_name,
    d.source_row_no, d.source_row_hash, d.source_updated_at, NOW()
FROM dwd.dwd_xhs_main_business_income_source_detail d
CROSS JOIN LATERAL (
    VALUES
        ('platform_commission', '平台佣金', d.platform_commission_amount),
        ('buyer_commission', '买手佣金', d.buyer_commission_amount),
        ('installment_fee', '花呗分期手续费', d.installment_fee_amount)
    ) component(component_code, category_name, signed_amount)
WHERE d.source_business_type <> '申诉调账';

WITH cleaned AS (
    SELECT
        raw.*,
        NULLIF(BTRIM(raw."订单号"), '') AS clean_order_no,
        BTRIM(raw."业务款项") AS clean_business_type,
        NULLIF(BTRIM(raw."结算时间"), '')::timestamp AS parsed_event_at,
        ROUND(REPLACE(BTRIM(raw."动账金额"), ',', '')::numeric, 2) AS parsed_signed_amount
    FROM common.v_current_xhs_settlement_expense_raw raw
)
INSERT INTO dwd.dwd_xhs_platform_expense_source_detail (
    source_table, source_id, source_component_code, platform_code,
    platform_name, shop_code, shop_name, shop_identity_key,
    shop_mapping_source, stat_date, event_at, order_no,
    source_business_type, secondary_category_name, signed_amount,
    directional_expense_amount, source_batch_id, source_file_name,
    source_row_no, source_row_hash, source_updated_at, updated_at
)
SELECT
    'expense', c.id, 'other_service', 'xhs', '小红书',
    ctx.shop_code, ctx.shop_name, ctx.shop_identity_key,
    ctx.shop_mapping_source, c.parsed_event_at::date, c.parsed_event_at,
    c.clean_order_no, c.clean_business_type, c.clean_business_type,
    c.parsed_signed_amount, -c.parsed_signed_amount, c.batch_id,
    c.source_file_name, c.source_row_no, c.row_hash, c.ingest_time, NOW()
FROM cleaned c
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id=c.batch_id
   AND ctx.platform_code='xhs'
   AND ctx.target_table='ods_xhs_settlement_expense_raw'
   AND ctx.shop_mapping_status='mapped'
WHERE c.clean_business_type <> '申诉调账';
