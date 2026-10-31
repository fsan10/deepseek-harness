TRUNCATE TABLE dwd.dwd_wechat_channels_main_business_income_source_detail;
TRUNCATE TABLE dwd.dwd_wechat_channels_platform_expense_source_detail;

WITH cleaned AS (
    SELECT
        raw.*,
        NULLIF(BTRIM(raw."流水单号"), '') AS clean_flow_no,
        NULLIF(BTRIM(raw."关联订单号"), '') AS clean_order_no,
        NULLIF(BTRIM(raw."关联售后单号"), '') AS clean_after_sale_no,
        BTRIM(raw."动帐类型") AS clean_business_type,
        BTRIM(raw."收支类型") AS clean_direction,
        NULLIF(BTRIM(raw."详情"), '') AS clean_description,
        NULLIF(BTRIM(raw."记账时间"), '')::timestamp AS parsed_event_at,
        ROUND(REPLACE(BTRIM(raw."收支金额"), ',', '')::numeric, 2)
            * CASE WHEN BTRIM(raw."收支类型")='收入' THEN 1 ELSE -1 END
            AS parsed_signed_amount
    FROM common.v_current_wechat_channels_settlement_raw raw
)
INSERT INTO dwd.dwd_wechat_channels_main_business_income_source_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, event_at, flow_no,
    order_no, after_sale_no, source_business_type, source_direction,
    source_description, secondary_category_name, signed_amount,
    source_batch_id, source_file_name, source_row_no, source_row_hash,
    source_updated_at, updated_at
)
SELECT
    c.id, 'wechat_channels', '视频号', ctx.shop_code, ctx.shop_name,
    ctx.shop_identity_key, ctx.shop_mapping_source, c.parsed_event_at::date,
    c.parsed_event_at, c.clean_flow_no, c.clean_order_no, c.clean_after_sale_no,
    c.clean_business_type, c.clean_direction, c.clean_description,
    c.clean_business_type, c.parsed_signed_amount, c.batch_id,
    c.source_file_name, c.source_row_no, c.row_hash, c.ingest_time, NOW()
FROM cleaned c
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id=c.batch_id
   AND ctx.platform_code='wechat_channels'
   AND ctx.target_table='ods_wechat_channels_settlement_raw'
   AND ctx.shop_mapping_status='mapped';

INSERT INTO dwd.dwd_wechat_channels_platform_expense_source_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, event_at, flow_no,
    order_no, after_sale_no, source_business_type, source_direction,
    source_description, secondary_category_name, signed_amount,
    directional_expense_amount, source_batch_id, source_file_name,
    source_row_no, source_row_hash, source_updated_at, updated_at
)
SELECT
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, event_at, flow_no,
    order_no, after_sale_no, source_business_type, source_direction,
    source_description, secondary_category_name, signed_amount,
    -signed_amount, source_batch_id, source_file_name, source_row_no,
    source_row_hash, source_updated_at, NOW()
FROM dwd.dwd_wechat_channels_main_business_income_source_detail;
