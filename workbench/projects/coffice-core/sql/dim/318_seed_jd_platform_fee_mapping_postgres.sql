INSERT INTO dim.dim_platform_fee_mapping (
    platform_code,
    platform_name,
    source_document_type,
    secondary_category_code,
    secondary_category_name,
    source_business_type,
    source_description_match_type,
    source_description_match_value,
    mapping_priority,
    primary_category_code,
    primary_category_name,
    include_in_platform_expense,
    classification_note,
    display_order,
    created_by,
    updated_by
)
VALUES
    ('jd', '京东', 'settlement', 'goods_payment', '货款',
     NULL, 'none', NULL, 0, 'non_expense_goods_payment', '非费用-货款',
     FALSE, '货款进入主营业务收入或销售退款，不计平台费用。', 900, 'seed', 'seed'),
    ('jd', '京东', 'settlement', 'commission', '佣金',
     NULL, 'none', NULL, 0, 'platform_commission', '平台佣金',
     TRUE, '京东结算单佣金净额，退款时的正向返还自动冲减费用。', 10, 'seed', 'seed'),
    ('jd', '京东', 'settlement', 'transaction_service_fee', '交易服务费',
     NULL, 'none', NULL, 0, 'platform_service_fee', '平台服务费',
     TRUE, '京东交易服务费净额。', 20, 'seed', 'seed'),
    ('jd', '京东', 'settlement', 'product_insurance_service_fee', '商品保险服务费',
     NULL, 'none', NULL, 0, 'product_insurance_expense', '商品保险',
     TRUE, '京东商品保险服务费净额。', 30, 'seed', 'seed'),
    ('jd', '京东', 'settlement', 'freight_insurance_service_fee', '运费保险服务费',
     NULL, 'none', NULL, 0, 'freight_insurance_expense', '运费保险',
     TRUE, '京东运费保险服务费净额。', 31, 'seed', 'seed'),
    ('jd', '京东', 'settlement', 'jd_bean_follow_order', '随单送的京豆',
     NULL, 'none', NULL, 0, 'jd_bean_expense', '京豆费用',
     TRUE, '京东随单赠送京豆费用。', 40, 'seed', 'seed'),
    ('jd', '京东', 'settlement', 'collected_delivery_fee', '代收配送费',
     NULL, 'none', NULL, 0, 'non_expense_collected_delivery_fee', '非费用-代收配送费',
     FALSE, '代商家收取的配送费收入，不属于平台费用。', 902, 'seed', 'seed'),
    ('jd', '京东', 'settlement', 'comprehensive_penalty', '综合违约金',
     NULL, 'none', NULL, 0, 'penalty_expense', '违约金',
     TRUE, '京东综合违约金，建议归入一级分类违约金。', 70, 'seed', 'seed'),

    ('jd', '京东', 'fund', 'merchant_settlement', '商户结算',
     '商户结算', 'any', NULL, 100,
     'non_expense_merchant_settlement', '非费用-商户结算',
     FALSE, '结算单各费用项汇总后的钱包动账，仅用于跨日对账。', 900, 'seed', 'seed'),
    ('jd', '京东', 'fund', 'post_settlement_refund', '售后退款质保金扣除',
     '转账-售后退款质保金扣除', 'any', NULL, 100,
     'non_expense_sales_refund', '非费用-销售退款',
     FALSE, '已结算订单的退款本金进入主营业务收入冲减，不计平台费用。', 901, 'seed', 'seed'),
    ('jd', '京东', 'fund', 'jd_union_deduction', '京东联盟扣款',
     NULL, 'exact', '京东联盟扣款', 80,
     'promotion_expense', '推广费',
     TRUE, '京东联盟扣款计入推广费。', 50, 'seed', 'seed'),
    ('jd', '京东', 'fund', 'jd_union_supplement', '京东联盟补款',
     NULL, 'exact', '京东联盟补款', 80,
     'promotion_expense', '推广费',
     TRUE, '京东联盟补款按负推广费冲减。', 51, 'seed', 'seed'),
    ('jd', '京东', 'fund', 'wallet_consumption_order', '消费订单',
     NULL, 'exact', '消费订单', 80,
     'promotion_expense', '推广费',
     TRUE, '用户确认余额支付消费订单9200元属于推广费。', 52, 'seed', 'seed'),
    ('jd', '京东', 'fund', 'direct_compensation_deduction', '直赔退款代扣',
     NULL, 'prefix', '直赔退款代扣', 80,
     'after_sales_compensation_expense', '售后赔付',
     TRUE, '商家直赔资金扣款计入售后赔付。', 60, 'seed', 'seed'),
    ('jd', '京东', 'fund', 'retention_compensation_insurance_claim', '挽单补偿险理赔',
     '转账', 'contains', '挽单补偿险', 80,
     'freight_insurance_expense', '运费保险',
     TRUE, '命中含挽单补偿险的转账理赔描述，收入方向按负费用冲减运费保险。', 32, 'seed', 'seed')
ON CONFLICT DO NOTHING;

UPDATE dim.dim_platform_fee_mapping
SET
    classification_note = '京东综合违约金，建议归入一级分类违约金。',
    updated_by = 'seed'
WHERE platform_code = 'jd'
  AND source_document_type = 'settlement'
  AND secondary_category_code = 'comprehensive_penalty'
  AND created_by = 'seed'
  AND classification_note
      = '京东综合违约金；当前来源金额为0，保留人工分类供后续使用。';

UPDATE dim.dim_platform_fee_mapping
SET
    source_business_type = '转账',
    source_description_match_type = 'contains',
    source_description_match_value = '挽单补偿险',
    mapping_priority = 80,
    classification_note
        = '命中含挽单补偿险的转账理赔描述，收入方向按负费用冲减运费保险。',
    updated_by = 'seed'
WHERE platform_code = 'jd'
  AND source_document_type = 'fund'
  AND secondary_category_code = 'retention_compensation_insurance_claim'
  AND created_by = 'seed'
  AND source_description_match_type = 'prefix'
  AND source_description_match_value = '订单号：';
