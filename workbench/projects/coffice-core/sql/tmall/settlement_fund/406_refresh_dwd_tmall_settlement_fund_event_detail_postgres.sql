TRUNCATE TABLE dwd.dwd_tmall_settlement_fund_event_detail;

WITH normalized AS (
    SELECT
        'aggregate:' || raw.id::text AS source_event_key,
        'aggregate'::varchar AS source_account_type,
        raw.id AS source_id,
        ctx.shop_code,
        ctx.shop_name,
        ctx.shop_identity_key,
        ctx.shop_mapping_source,
        TO_DATE(BTRIM(raw."入帐日期"), 'YYYYMMDD') AS stat_date,
        BTRIM(raw."入帐类型") AS source_business_type,
        BTRIM(COALESCE(NULLIF(BTRIM(raw."备注"), ''), NULLIF(BTRIM(raw."业务描述"), ''), '')) AS source_description,
        NULLIF(BTRIM(raw."主订单id"), '') AS order_no,
        NULL::varchar AS business_flow_no,
        NULL::varchar AS merchant_order_no,
        ROUND(COALESCE(NULLIF(REPLACE(NULLIF(BTRIM(raw."收入金额(元)"), ''), ',', ''), '-')::numeric, 0), 2) AS raw_income_amount,
        ROUND(COALESCE(NULLIF(REPLACE(NULLIF(BTRIM(raw."支出金额(元)"), ''), ',', ''), '-')::numeric, 0), 2) AS raw_expense_amount,
        raw.batch_id AS source_batch_id,
        raw.source_file_name,
        raw.source_row_no,
        raw.ingest_time AS source_updated_at
    FROM common.v_current_tmall_aggregate_fund_raw raw
    INNER JOIN common.v_ingest_batch_shop_context ctx
        ON ctx.batch_id = raw.batch_id
       AND ctx.platform_code = 'tmall'
       AND ctx.target_table = 'ods_tmall_aggregate_fund_raw'
       AND ctx.shop_mapping_status = 'mapped'

    UNION ALL

    SELECT
        'alipay:' || raw.id::text,
        'alipay'::varchar,
        raw.id,
        ctx.shop_code,
        ctx.shop_name,
        ctx.shop_identity_key,
        ctx.shop_mapping_source,
        NULLIF(BTRIM(raw."发生时间"), '')::timestamp::date,
        BTRIM(REPLACE(raw."业务类型", E'\t', '')),
        BTRIM(REPLACE(COALESCE(raw."备注", ''), E'\t', '')),
        NULLIF(BTRIM(REPLACE(raw."商户订单号", E'\t', '')), ''),
        NULLIF(BTRIM(REPLACE(raw."业务流水号", E'\t', '')), ''),
        NULLIF(BTRIM(REPLACE(raw."商户订单号", E'\t', '')), ''),
        ROUND(COALESCE(NULLIF(REPLACE(NULLIF(BTRIM(raw."收入金额（+元）"), ''), ',', ''), '-')::numeric, 0), 2),
        ROUND(COALESCE(NULLIF(REPLACE(NULLIF(BTRIM(raw."支出金额（-元）"), ''), ',', ''), '-')::numeric, 0), 2),
        raw.batch_id,
        raw.source_file_name,
        raw.source_row_no,
        raw.ingest_time
    FROM common.v_current_tmall_alipay_fund_raw raw
    INNER JOIN common.v_ingest_batch_shop_context ctx
        ON ctx.batch_id = raw.batch_id
       AND ctx.platform_code = 'tmall'
       AND ctx.target_table = 'ods_tmall_alipay_fund_raw'
       AND ctx.shop_mapping_status = 'mapped'
), classified AS (
    SELECT
        n.*,
        ROUND(
            CASE WHEN n.source_account_type = 'aggregate'
                 THEN n.raw_income_amount - n.raw_expense_amount
                 ELSE n.raw_income_amount + n.raw_expense_amount
            END,
            2
        ) AS signed_amount,
        CASE
            WHEN n.source_account_type = 'aggregate'
             AND n.source_business_type = '交易收款' THEN TRUE
            WHEN n.source_account_type = 'alipay'
             AND n.source_business_type = '交易付款' THEN TRUE
            ELSE FALSE
        END AS income_eligible,
        CASE
            WHEN n.source_business_type IN ('交易退款(售后)', '交易退款')
                THEN ABS(ROUND(
                    CASE WHEN n.source_account_type = 'aggregate'
                         THEN n.raw_income_amount - n.raw_expense_amount
                         ELSE n.raw_income_amount + n.raw_expense_amount
                    END, 2))
            ELSE 0
        END AS refund_amount,
        CASE
            WHEN n.source_business_type IN ('扣款', '扣款退回', '交易分账', '转账', '其它')
             AND n.source_description LIKE '%品牌新享-首单拉新计划%' THEN 'brand_new_customer'
            WHEN n.source_business_type IN ('扣款', '扣款退回', '交易分账', '转账', '其它')
             AND n.source_description LIKE '%限时红包代商家垫付扣回%' THEN 'limited_red_packet'
            WHEN n.source_business_type IN ('扣款', '扣款退回', '交易分账', '转账', '其它')
             AND n.source_description LIKE '%淘金币软件服务费%' THEN 'taobao_coins'
            WHEN n.source_business_type IN ('扣款', '扣款退回', '交易分账', '转账', '其它')
             AND n.source_description LIKE '%基础软件服务费%' THEN 'basic_software'
            WHEN n.source_business_type IN ('扣款', '扣款退回', '交易分账', '转账', '其它')
             AND n.source_description LIKE '%光合平台软件服务费%' THEN 'guanghe_platform'
            WHEN n.source_business_type IN ('扣款', '扣款退回', '交易分账', '转账', '其它')
             AND n.source_description LIKE '%淘宝内容推广服务费%' THEN 'taobao_content_promotion'
            WHEN n.source_business_type IN ('扣款', '扣款退回', '交易分账', '转账', '其它')
             AND n.source_description LIKE '%淘宝客佣金代扣款%' THEN 'taobao_affiliate_commission'
            WHEN n.source_business_type IN ('扣款', '扣款退回', '交易分账', '转账', '其它')
             AND n.source_description LIKE '%先用后付技术服务费%' THEN 'buy_now_pay_later'
            WHEN n.source_business_type IN ('扣款', '扣款退回', '交易分账', '转账', '其它')
             AND n.source_description LIKE '%天猫佣金（类目系统）%' THEN 'tmall_commission'
            WHEN n.source_business_type IN ('扣款', '扣款退回', '交易分账', '转账', '其它')
             AND (n.source_description LIKE '%代扣返点积分%'
                  OR n.source_description LIKE '%代扣交易退回积分%') THEN 'points_rebate'
            WHEN n.source_business_type IN ('扣款', '扣款退回', '交易分账', '转账', '其它')
             AND n.source_description LIKE '%消费者体验提升计划服务费%' THEN 'consumer_experience'
            WHEN n.source_business_type IN ('扣款', '扣款退回', '交易分账', '转账', '其它')
             AND n.source_description LIKE '%商家集运%' THEN 'merchant_logistics'
            WHEN n.source_business_type IN ('扣款', '扣款退回', '交易分账', '转账', '其它')
             AND (n.source_description LIKE '%淘宝联盟佣金代扣%'
                  OR n.source_description LIKE '%淘宝联盟推广佣金返还%') THEN 'taobao_union_commission'
            WHEN n.source_business_type IN ('扣款', '扣款退回', '交易分账', '转账', '其它')
             AND n.source_description LIKE '%天猫保证金履约险追偿%' THEN 'deposit_fulfillment_insurance'
            WHEN n.source_business_type IN ('扣款', '扣款退回', '交易分账', '转账', '其它')
             AND n.source_description LIKE '%支付宝转账小额打款%' THEN 'small_transfer'
            ELSE 'unclassified'
        END AS expense_type_code
    FROM normalized n
)
INSERT INTO dwd.dwd_tmall_settlement_fund_event_detail (
    source_event_key, source_account_type, source_id, platform_code, platform_name,
    shop_code, shop_name, shop_identity_key, shop_mapping_source, stat_date,
    bill_period_raw, source_business_type, source_direction, source_description,
    order_no, business_flow_no, merchant_order_no, income_amount, expense_amount,
    signed_amount, refund_amount, income_eligible, expense_eligible,
    expense_type_code, expense_type_name, source_batch_id, source_file_name,
    source_row_no, source_updated_at, updated_at
)
SELECT
    c.source_event_key,
    c.source_account_type,
    c.source_id,
    'tmall',
    '天猫',
    c.shop_code,
    c.shop_name,
    c.shop_identity_key,
    c.shop_mapping_source,
    c.stat_date,
    TO_CHAR(c.stat_date, 'YYYYMMDD'),
    c.source_business_type,
    CASE WHEN c.signed_amount > 0 THEN '收入'
         WHEN c.signed_amount < 0 THEN '支出'
         ELSE '零金额' END,
    NULLIF(c.source_description, ''),
    c.order_no,
    c.business_flow_no,
    c.merchant_order_no,
    CASE WHEN c.income_eligible THEN c.raw_income_amount ELSE 0 END,
    CASE WHEN c.expense_type_code <> 'unclassified' THEN -c.signed_amount ELSE 0 END,
    c.signed_amount,
    c.refund_amount,
    c.income_eligible,
    c.expense_type_code <> 'unclassified',
    c.expense_type_code,
    CASE c.expense_type_code
        WHEN 'brand_new_customer' THEN '品牌新享首单拉新'
        WHEN 'limited_red_packet' THEN '限时红包代商家垫付扣回'
        WHEN 'taobao_coins' THEN '淘金币软件服务费'
        WHEN 'basic_software' THEN '基础软件服务费'
        WHEN 'guanghe_platform' THEN '光合平台软件服务费'
        WHEN 'taobao_content_promotion' THEN '淘宝内容推广服务费'
        WHEN 'taobao_affiliate_commission' THEN '淘宝客佣金'
        WHEN 'buy_now_pay_later' THEN '先用后付技术服务费'
        WHEN 'tmall_commission' THEN '天猫佣金'
        WHEN 'points_rebate' THEN '代扣返点积分'
        WHEN 'consumer_experience' THEN '消费者体验提升计划服务费'
        WHEN 'merchant_logistics' THEN '商家集运服务费'
        WHEN 'taobao_union_commission' THEN '淘宝联盟佣金'
        WHEN 'deposit_fulfillment_insurance' THEN '天猫保证金履约险'
        WHEN 'small_transfer' THEN '小额打款'
        ELSE '未分类'
    END,
    c.source_batch_id,
    c.source_file_name,
    c.source_row_no,
    c.source_updated_at,
    NOW()
FROM classified c;
