TRUNCATE TABLE dwd.dwd_xhs_settlement_net_event_detail;

INSERT INTO dwd.dwd_xhs_settlement_net_event_detail (
    source_event_key, source_table, source_id, platform_code, platform_name,
    shop_code, shop_name, shop_identity_key, shop_mapping_source, stat_date,
    settled_at, event_direction, event_type, order_no, source_movement_amount,
    income_amount, expense_amount, settlement_net_amount,
    source_settlement_amount, validation_difference_amount, source_batch_id,
    source_file_name, source_sheet_name, source_row_no, source_updated_at, updated_at
)
WITH income_events AS (
    SELECT
        'income:' || raw.id::text AS source_event_key,
        'ods_xhs_settlement_income_raw'::varchar AS source_table,
        raw.id AS source_id,
        ctx.shop_code, ctx.shop_name, ctx.shop_identity_key, ctx.shop_mapping_source,
        BTRIM(raw."结算时间")::timestamp::date AS stat_date,
        BTRIM(raw."结算时间")::timestamp AS settled_at,
        '收入'::varchar AS event_direction,
        NULLIF(BTRIM(raw."交易类型"), '') AS event_type,
        NULLIF(BTRIM(raw."订单号"), '') AS order_no,
        ROUND(BTRIM(raw."动账金额")::numeric, 2) AS source_movement_amount,
        ROUND(BTRIM(raw."动账金额")::numeric, 2) AS income_amount,
        0::numeric AS expense_amount,
        raw.batch_id, raw.source_file_name, raw.source_sheet_name,
        raw.source_row_no, raw.ingest_time
    FROM common.v_current_xhs_settlement_income_raw raw
    INNER JOIN common.v_ingest_batch_shop_context ctx
        ON ctx.batch_id = raw.batch_id
       AND ctx.platform_code = 'xhs'
       AND ctx.target_table = 'ods_xhs_settlement_income_raw'
       AND ctx.shop_mapping_status = 'mapped'
), appeal_income_events AS (
    SELECT
        'expense_income:' || raw.id::text AS source_event_key,
        'ods_xhs_settlement_expense_raw'::varchar AS source_table,
        raw.id AS source_id,
        ctx.shop_code, ctx.shop_name, ctx.shop_identity_key, ctx.shop_mapping_source,
        BTRIM(raw."结算时间")::timestamp::date AS stat_date,
        BTRIM(raw."结算时间")::timestamp AS settled_at,
        '收入'::varchar AS event_direction,
        '申诉调账'::varchar AS event_type,
        COALESCE(
            NULLIF(NULLIF(BTRIM(raw."业务单号"), ''), '-'),
            '申诉调账:' || raw.id::text
        ) AS order_no,
        ROUND(BTRIM(raw."动账金额")::numeric, 2) AS source_movement_amount,
        ROUND(BTRIM(raw."动账金额")::numeric, 2) AS income_amount,
        0::numeric AS expense_amount,
        raw.batch_id, raw.source_file_name, raw.source_sheet_name,
        raw.source_row_no, raw.ingest_time
    FROM common.v_current_xhs_settlement_expense_raw raw
    INNER JOIN common.v_ingest_batch_shop_context ctx
        ON ctx.batch_id = raw.batch_id
       AND ctx.platform_code = 'xhs'
       AND ctx.target_table = 'ods_xhs_settlement_expense_raw'
       AND ctx.shop_mapping_status = 'mapped'
    WHERE BTRIM(raw."业务款项") = '申诉调账'
), expense_events AS (
    SELECT
        'expense:' || raw.id::text AS source_event_key,
        'ods_xhs_settlement_expense_raw'::varchar AS source_table,
        raw.id AS source_id,
        ctx.shop_code, ctx.shop_name, ctx.shop_identity_key, ctx.shop_mapping_source,
        BTRIM(raw."结算时间")::timestamp::date AS stat_date,
        BTRIM(raw."结算时间")::timestamp AS settled_at,
        '支出'::varchar AS event_direction,
        NULLIF(BTRIM(raw."业务款项"), '') AS event_type,
        NULLIF(BTRIM(raw."订单号"), '') AS order_no,
        ROUND(BTRIM(raw."动账金额")::numeric, 2) AS source_movement_amount,
        0::numeric AS income_amount,
        ROUND(-BTRIM(raw."动账金额")::numeric, 2) AS expense_amount,
        raw.batch_id, raw.source_file_name, raw.source_sheet_name,
        raw.source_row_no, raw.ingest_time
    FROM common.v_current_xhs_settlement_expense_raw raw
    INNER JOIN common.v_ingest_batch_shop_context ctx
        ON ctx.batch_id = raw.batch_id
       AND ctx.platform_code = 'xhs'
       AND ctx.target_table = 'ods_xhs_settlement_expense_raw'
       AND ctx.shop_mapping_status = 'mapped'
    WHERE BTRIM(raw."业务款项") <> '申诉调账'
), all_events AS (
    SELECT * FROM income_events
    UNION ALL
    SELECT * FROM appeal_income_events
    UNION ALL
    SELECT * FROM expense_events
)
SELECT
    source_event_key, source_table, source_id, 'xhs', '小红书',
    shop_code, shop_name, shop_identity_key, shop_mapping_source, stat_date,
    settled_at, event_direction, event_type, order_no, source_movement_amount,
    income_amount, expense_amount,
    ROUND(income_amount - expense_amount, 2),
    source_movement_amount,
    ROUND(income_amount - expense_amount - source_movement_amount, 2),
    batch_id, source_file_name, source_sheet_name, source_row_no, ingest_time, NOW()
FROM all_events;
