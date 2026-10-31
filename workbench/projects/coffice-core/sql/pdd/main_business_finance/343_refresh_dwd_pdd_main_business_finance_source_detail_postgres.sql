TRUNCATE TABLE dwd.dwd_pdd_main_business_income_source_detail;
TRUNCATE TABLE dwd.dwd_pdd_platform_expense_source_detail;

WITH cleaned AS (
    SELECT
        raw.*,
        NULLIF(BTRIM(raw."商户订单号"), '') AS clean_order_no,
        BTRIM(raw."账务类型") AS clean_business_type,
        BTRIM(raw."业务描述") AS clean_description,
        NULLIF(BTRIM(raw."发生时间"), '')::timestamp AS parsed_event_at,
        ROUND(REPLACE(BTRIM(raw."收入金额（+元）"), ',', '')::numeric, 2)
      + ROUND(REPLACE(BTRIM(raw."支出金额（-元）"), ',', '')::numeric, 2)
            AS parsed_signed_amount
    FROM common.v_current_pdd_settlement_raw raw
)
INSERT INTO dwd.dwd_pdd_main_business_income_source_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, event_at, order_no,
    source_business_type, source_description, secondary_category_name,
    signed_amount, source_batch_id, source_file_name, source_row_no,
    source_row_hash, source_updated_at, updated_at
)
SELECT
    c.id, 'pdd', '拼多多', ctx.shop_code, ctx.shop_name,
    ctx.shop_identity_key, ctx.shop_mapping_source, c.parsed_event_at::date,
    c.parsed_event_at, c.clean_order_no, c.clean_business_type,
    c.clean_description, c.clean_business_type || ' + ' || c.clean_description,
    c.parsed_signed_amount, c.batch_id, c.source_file_name, c.source_row_no,
    c.row_hash, c.ingest_time, NOW()
FROM cleaned c
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = c.batch_id
   AND ctx.platform_code = 'pdd'
   AND ctx.target_table = 'ods_pdd_settlement_raw'
   AND ctx.shop_mapping_status = 'mapped';

INSERT INTO dwd.dwd_pdd_platform_expense_source_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, event_at, order_no,
    source_business_type, source_description, secondary_category_name,
    signed_amount, directional_expense_amount, source_batch_id,
    source_file_name, source_row_no, source_row_hash, source_updated_at, updated_at
)
SELECT
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, event_at, order_no,
    source_business_type, source_description, secondary_category_name,
    signed_amount, -signed_amount, source_batch_id, source_file_name,
    source_row_no, source_row_hash, source_updated_at, NOW()
FROM dwd.dwd_pdd_main_business_income_source_detail;
