TRUNCATE TABLE dwd.dwd_xhs_settlement_expense_event_detail;

INSERT INTO dwd.dwd_xhs_settlement_expense_event_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, settled_at, order_no,
    business_item, business_no, settlement_account, source_movement_amount,
    expense_amount, remark, source_batch_id, source_file_name,
    source_sheet_name, source_row_no, source_updated_at, updated_at
)
SELECT
    raw.id, 'xhs', '小红书', ctx.shop_code, ctx.shop_name,
    ctx.shop_identity_key, ctx.shop_mapping_source,
    BTRIM(raw."结算时间")::timestamp::date,
    BTRIM(raw."结算时间")::timestamp,
    NULLIF(BTRIM(raw."订单号"), ''),
    NULLIF(BTRIM(raw."业务款项"), ''),
    NULLIF(BTRIM(raw."业务单号"), ''),
    NULLIF(BTRIM(raw."结算账户"), ''),
    ROUND(BTRIM(raw."动账金额")::numeric, 2),
    ROUND(-BTRIM(raw."动账金额")::numeric, 2),
    NULLIF(BTRIM(raw."备注"), ''),
    raw.batch_id, raw.source_file_name, raw.source_sheet_name,
    raw.source_row_no, raw.ingest_time, NOW()
FROM common.v_current_xhs_settlement_expense_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'xhs'
   AND ctx.target_table = 'ods_xhs_settlement_expense_raw'
   AND ctx.shop_mapping_status = 'mapped'
WHERE BTRIM(raw."业务款项") <> '申诉调账';
