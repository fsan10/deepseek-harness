TRUNCATE TABLE dwd.dwd_tmall_platform_expense_source_detail;

WITH cleaned AS (
    SELECT
        raw.*, context.shop_identity_key AS source_shop_identity_key,
        NULLIF(BTRIM(raw."支付流水号"), '') AS clean_flow_no,
        NULLIF(BTRIM(raw."主订单id"), '') AS clean_main_order_no,
        NULLIF(BTRIM(raw."子订单id"), '') AS clean_sub_order_no,
        BTRIM(raw."入帐类型") AS clean_business_type,
        COALESCE(BTRIM(raw."备注"), '') AS clean_note,
        ROUND(
            REPLACE(COALESCE(NULLIF(BTRIM(raw."收入金额(元)"), ''), '0'), ',', '')::numeric,
            2
        ) AS income_amount,
        ROUND(
            REPLACE(COALESCE(NULLIF(BTRIM(raw."支出金额(元)"), ''), '0'), ',', '')::numeric,
            2
        ) AS expense_amount
    FROM common.v_current_tmall_aggregate_fund_raw raw
    JOIN common.v_ingest_batch_shop_context context ON context.batch_id=raw.batch_id
      AND context.platform_code='tmall' AND context.target_table='ods_tmall_aggregate_fund_raw'
),
latest AS (
    SELECT DISTINCT ON (source_shop_identity_key, clean_flow_no) *
    FROM cleaned
    WHERE clean_flow_no IS NOT NULL
    ORDER BY source_shop_identity_key, clean_flow_no, ingest_time DESC, id DESC
),
standardized AS (
    SELECT
        l.*,
        CASE
            WHEN clean_business_type = '交易收款' THEN '订单收款'
            WHEN clean_business_type = '交易退款(售后)' THEN '销售退款'
            WHEN clean_business_type = '提现' THEN '账户提现'
            WHEN clean_note LIKE '%品牌新享-首单拉新计划%' THEN '品牌新享-首单拉新计划'
            WHEN clean_note LIKE '%限时红包代商家垫付扣回%' THEN '限时红包代商家垫付扣回'
            WHEN clean_note LIKE '%淘金币软件服务费%' THEN '淘金币软件服务费'
            WHEN clean_note LIKE '%基础软件服务费%' THEN '基础软件服务费'
            WHEN clean_note LIKE '%光合平台软件服务费%' THEN '光合平台软件服务费'
            WHEN clean_note LIKE '%淘宝内容推广服务费%' THEN '淘宝内容推广服务费'
            ELSE BTRIM(
                REGEXP_REPLACE(clean_note, '[0-9]{10,}', '<ID>', 'g')
            )
        END AS standardized_note,
        income_amount - expense_amount AS parsed_signed_amount
    FROM latest l
)
INSERT INTO dwd.dwd_tmall_platform_expense_source_detail (
    source_account_type,
    source_event_key,
    source_id,
    standardized_note,
    secondary_category_name,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    shop_identity_key,
    shop_mapping_source,
    stat_date,
    event_at,
    source_direction,
    source_business_type,
    source_description,
    flow_no,
    business_flow_no,
    merchant_order_no,
    main_order_no,
    sub_order_no,
    source_amount,
    signed_amount,
    directional_expense_amount,
    source_batch_id,
    source_file_name,
    source_row_no,
    source_updated_at,
    updated_at
)
SELECT
    'aggregate',
    s.clean_flow_no,
    s.id,
    s.standardized_note,
    s.clean_business_type || ' + ' || s.standardized_note,
    'tmall',
    '天猫',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    TO_DATE(BTRIM(s."入帐日期"), 'YYYYMMDD'),
    NULLIF(BTRIM(s."入帐时间"), '')::timestamp,
    CASE
        WHEN s.parsed_signed_amount > 0 THEN '收入'
        WHEN s.parsed_signed_amount < 0 THEN '支出'
        ELSE '零金额'
    END,
    s.clean_business_type,
    NULLIF(s.clean_note, ''),
    s.clean_flow_no,
    NULL,
    NULL,
    s.clean_main_order_no,
    s.clean_sub_order_no,
    ABS(s.parsed_signed_amount),
    s.parsed_signed_amount,
    -s.parsed_signed_amount,
    s.batch_id,
    s.source_file_name,
    s.source_row_no,
    s.ingest_time,
    NOW()
FROM standardized s
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = s.batch_id
   AND ctx.platform_code = 'tmall'
   AND ctx.target_table = 'ods_tmall_aggregate_fund_raw'
   AND ctx.shop_mapping_status = 'mapped';

WITH cleaned AS (
    SELECT
        raw.*, context.shop_identity_key AS source_shop_identity_key,
        NULLIF(BTRIM(REPLACE(raw."账务流水号", E'\t', '')), '') AS clean_flow_no,
        NULLIF(BTRIM(REPLACE(raw."业务流水号", E'\t', '')), '') AS clean_business_flow_no,
        NULLIF(BTRIM(REPLACE(raw."商户订单号", E'\t', '')), '') AS clean_merchant_order_no,
        BTRIM(REPLACE(raw."业务类型", E'\t', '')) AS clean_business_type,
        COALESCE(BTRIM(REPLACE(raw."备注", E'\t', '')), '') AS clean_note,
        ROUND(
            REPLACE(
                COALESCE(NULLIF(BTRIM(raw."收入金额（+元）"), ''), '0'),
                ',',
                ''
            )::numeric,
            2
        ) AS income_amount,
        ROUND(
            REPLACE(
                COALESCE(NULLIF(BTRIM(raw."支出金额（-元）"), ''), '0'),
                ',',
                ''
            )::numeric,
            2
        ) AS expense_amount
    FROM common.v_current_tmall_alipay_fund_raw raw
    JOIN common.v_ingest_batch_shop_context context ON context.batch_id=raw.batch_id
      AND context.platform_code='tmall' AND context.target_table='ods_tmall_alipay_fund_raw'
),
latest AS (
    SELECT DISTINCT ON (source_shop_identity_key, clean_flow_no) *
    FROM cleaned
    WHERE clean_flow_no IS NOT NULL
    ORDER BY source_shop_identity_key, clean_flow_no, ingest_time DESC, id DESC
),
standardized AS (
    SELECT
        l.*,
        CASE
            WHEN clean_business_type = '交易付款' THEN '订单收款'
            WHEN clean_business_type = '交易退款' THEN '销售退款'
            WHEN clean_business_type = '提现' THEN '账户提现'
            WHEN clean_note LIKE '%品牌新享-首单拉新计划%' THEN '品牌新享-首单拉新计划'
            WHEN clean_note LIKE '%限时红包代商家垫付扣回%' THEN '限时红包代商家垫付扣回'
            WHEN clean_note LIKE '%淘金币软件服务费%' THEN '淘金币软件服务费'
            WHEN clean_note LIKE '%基础软件服务费%' THEN '基础软件服务费'
            WHEN clean_note LIKE '%光合平台软件服务费%' THEN '光合平台软件服务费'
            WHEN clean_note LIKE '%淘宝内容推广服务费%' THEN '淘宝内容推广服务费'
            WHEN clean_note LIKE '%淘宝客佣金代扣款%' THEN '淘宝客佣金'
            WHEN clean_note LIKE '%先用后付技术服务费%' THEN '先用后付技术服务费'
            WHEN clean_note LIKE '%天猫佣金（类目系统）%' THEN '天猫佣金（类目系统）'
            WHEN clean_note LIKE '%代扣返点积分%'
              OR clean_note LIKE '%代扣交易退回积分%' THEN '代扣返点积分'
            WHEN clean_note LIKE '%消费者体验提升计划服务费%' THEN '消费者体验提升计划服务费'
            WHEN clean_note LIKE '%商家集运物流服务费%' THEN '商家集运物流服务费'
            WHEN clean_note LIKE '%商家集运中转操作费%' THEN '商家集运中转操作费'
            WHEN clean_note LIKE '%淘宝联盟佣金代扣%'
              OR clean_note LIKE '%淘宝联盟推广佣金返还%' THEN '淘宝联盟佣金'
            WHEN clean_note LIKE '%天猫保证金履约险追偿%' THEN '天猫保证金履约险追偿'
            WHEN clean_note LIKE '%支付宝转账小额打款%' THEN '小额打款'
            ELSE BTRIM(
                REGEXP_REPLACE(clean_note, '[0-9]{10,}', '<ID>', 'g')
            )
        END AS standardized_note,
        income_amount + expense_amount AS parsed_signed_amount
    FROM latest l
)
INSERT INTO dwd.dwd_tmall_platform_expense_source_detail (
    source_account_type,
    source_event_key,
    source_id,
    standardized_note,
    secondary_category_name,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    shop_identity_key,
    shop_mapping_source,
    stat_date,
    event_at,
    source_direction,
    source_business_type,
    source_description,
    flow_no,
    business_flow_no,
    merchant_order_no,
    main_order_no,
    sub_order_no,
    source_amount,
    signed_amount,
    directional_expense_amount,
    source_batch_id,
    source_file_name,
    source_row_no,
    source_updated_at,
    updated_at
)
SELECT
    'alipay',
    s.clean_flow_no,
    s.id,
    s.standardized_note,
    s.clean_business_type || ' + ' || s.standardized_note,
    'tmall',
    '天猫',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    NULLIF(BTRIM(s."发生时间"), '')::timestamp::date,
    NULLIF(BTRIM(s."发生时间"), '')::timestamp,
    CASE
        WHEN s.parsed_signed_amount > 0 THEN '收入'
        WHEN s.parsed_signed_amount < 0 THEN '支出'
        ELSE '零金额'
    END,
    s.clean_business_type,
    NULLIF(s.clean_note, ''),
    s.clean_flow_no,
    s.clean_business_flow_no,
    s.clean_merchant_order_no,
    NULL,
    NULL,
    ABS(s.parsed_signed_amount),
    s.parsed_signed_amount,
    -s.parsed_signed_amount,
    s.batch_id,
    s.source_file_name,
    s.source_row_no,
    s.ingest_time,
    NOW()
FROM standardized s
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = s.batch_id
   AND ctx.platform_code = 'tmall'
   AND ctx.target_table = 'ods_tmall_alipay_fund_raw'
   AND ctx.shop_mapping_status = 'mapped';

