TRUNCATE TABLE dwd.dwd_wechat_channels_settlement_net_event_detail;

INSERT INTO dwd.dwd_wechat_channels_settlement_net_event_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, occurred_at, flow_no,
    movement_type, income_expense_direction, source_amount, income_amount,
    expense_amount, settlement_net_amount, source_settlement_amount,
    validation_difference_amount, account_balance, related_order_no,
    related_after_sale_no, related_withdrawal_no, related_policy_no,
    related_gift_no, detail_text, source_batch_id, source_file_name,
    source_row_no, source_updated_at, updated_at
)
WITH parsed AS (
    SELECT
        raw.*,
        ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."收支金额"), ''), '-')::numeric, 0), 2) AS parsed_amount
    FROM common.v_current_wechat_channels_settlement_raw raw
), directional AS (
    SELECT
        p.*,
        CASE WHEN BTRIM(p."收支类型") = '收入' THEN p.parsed_amount ELSE 0 END AS parsed_income_amount,
        CASE WHEN BTRIM(p."收支类型") = '支出' THEN p.parsed_amount ELSE 0 END AS parsed_expense_amount,
        CASE WHEN BTRIM(p."收支类型") = '收入' THEN p.parsed_amount ELSE -p.parsed_amount END AS parsed_source_net_amount
    FROM parsed p
)
SELECT
    d.id, 'wechat_channels', '视频号', ctx.shop_code, ctx.shop_name,
    ctx.shop_identity_key, ctx.shop_mapping_source,
    NULLIF(NULLIF(BTRIM(d."记账时间"), ''), '-')::timestamp::date,
    NULLIF(NULLIF(BTRIM(d."记账时间"), ''), '-')::timestamp,
    NULLIF(BTRIM(d."流水单号"), ''),
    NULLIF(BTRIM(d."动帐类型"), ''),
    NULLIF(BTRIM(d."收支类型"), ''),
    d.parsed_amount, d.parsed_income_amount, d.parsed_expense_amount,
    ROUND(d.parsed_income_amount - d.parsed_expense_amount, 2),
    d.parsed_source_net_amount,
    ROUND(d.parsed_income_amount - d.parsed_expense_amount - d.parsed_source_net_amount, 2),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(d."账户余额"), ''), '-')::numeric, 0), 2),
    NULLIF(BTRIM(d."关联订单号"), ''),
    NULLIF(BTRIM(d."关联售后单号"), ''),
    NULLIF(BTRIM(d."关联提现单号"), ''),
    NULLIF(BTRIM(d."关联保单号"), ''),
    NULLIF(BTRIM(d."关联礼物单号"), ''),
    NULLIF(BTRIM(d."详情"), ''),
    d.batch_id, d.source_file_name, d.source_row_no, d.ingest_time, NOW()
FROM directional d
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = d.batch_id
   AND ctx.platform_code = 'wechat_channels'
   AND ctx.target_table = 'ods_wechat_channels_settlement_raw'
   AND ctx.shop_mapping_status = 'mapped';

