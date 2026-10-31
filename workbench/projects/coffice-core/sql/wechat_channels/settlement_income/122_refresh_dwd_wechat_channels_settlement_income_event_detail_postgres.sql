TRUNCATE TABLE dwd.dwd_wechat_channels_settlement_income_event_detail;

INSERT INTO dwd.dwd_wechat_channels_settlement_income_event_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, occurred_at, flow_no,
    movement_type, income_expense_direction, source_amount, income_amount,
    account_balance, related_order_no, related_after_sale_no,
    related_withdrawal_no, related_policy_no, related_gift_no, detail_text,
    source_batch_id, source_file_name, source_row_no, source_updated_at, updated_at
)
SELECT
    raw.id, 'wechat_channels', '视频号', ctx.shop_code, ctx.shop_name,
    ctx.shop_identity_key, ctx.shop_mapping_source,
    NULLIF(NULLIF(BTRIM(raw."记账时间"), ''), '-')::timestamp::date,
    NULLIF(NULLIF(BTRIM(raw."记账时间"), ''), '-')::timestamp,
    NULLIF(BTRIM(raw."流水单号"), ''),
    NULLIF(BTRIM(raw."动帐类型"), ''),
    NULLIF(BTRIM(raw."收支类型"), ''),
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."收支金额"), ''), '-')::numeric, 0), 2),
    CASE WHEN BTRIM(raw."收支类型") = '收入'
         THEN ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."收支金额"), ''), '-')::numeric, 0), 2)
         ELSE 0 END,
    ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."账户余额"), ''), '-')::numeric, 0), 2),
    NULLIF(BTRIM(raw."关联订单号"), ''),
    NULLIF(BTRIM(raw."关联售后单号"), ''),
    NULLIF(BTRIM(raw."关联提现单号"), ''),
    NULLIF(BTRIM(raw."关联保单号"), ''),
    NULLIF(BTRIM(raw."关联礼物单号"), ''),
    NULLIF(BTRIM(raw."详情"), ''),
    raw.batch_id, raw.source_file_name, raw.source_row_no, raw.ingest_time, NOW()
FROM common.v_current_wechat_channels_settlement_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'wechat_channels'
   AND ctx.target_table = 'ods_wechat_channels_settlement_raw'
   AND ctx.shop_mapping_status = 'mapped';

