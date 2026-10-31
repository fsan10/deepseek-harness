WITH seed (
    secondary_category_code,
    secondary_category_name,
    source_business_type,
    primary_category_code,
    primary_category_name,
    include_in_platform_expense,
    classification_note,
    display_order
) AS (
    VALUES
        ('tmall_fund_order_receipt_aggregate', '交易收款 + 订单收款', '交易收款', 'sales_income', '商品销售收入', FALSE, '聚合账户订单收款，进入主营业务收入，不计平台费用。', 10),
        ('tmall_fund_order_receipt_alipay', '交易付款 + 订单收款', '交易付款', 'sales_income', '商品销售收入', FALSE, '支付宝账户订单收款，进入主营业务收入，不计平台费用。', 11),
        ('tmall_fund_sales_refund_aggregate', '交易退款(售后) + 销售退款', '交易退款(售后)', 'sales_refund', '销售退款', FALSE, '聚合账户售后退款，冲减主营业务收入，不计平台费用。', 20),
        ('tmall_fund_sales_refund_alipay', '交易退款 + 销售退款', '交易退款', 'sales_refund', '销售退款', FALSE, '支付宝账户售后退款，冲减主营业务收入，不计平台费用。', 21),
        ('tmall_fund_withdrawal', '提现 + 账户提现', '提现', 'excluded', '不计平台费用', FALSE, '账户提现属于资金转出，不计主营收入或平台费用。', 99),

        ('tmall_fund_brand_new_deduction_aggregate', '扣款 + 品牌新享-首单拉新计划', '扣款', 'promotion_expense', '推广费', TRUE, '品牌新享首单拉新扣款。', 30),
        ('tmall_fund_brand_new_refund_aggregate', '扣款退回 + 品牌新享-首单拉新计划', '扣款退回', 'promotion_expense', '推广费', TRUE, '品牌新享首单拉新退款，按负费用冲减推广费。', 31),
        ('tmall_fund_brand_new_alipay', '交易分账 + 品牌新享-首单拉新计划', '交易分账', 'promotion_expense', '推广费', TRUE, '支付宝品牌新享扣款和退款净额。', 32),
        ('tmall_fund_content_promotion_aggregate', '扣款 + 淘宝内容推广服务费', '扣款', 'promotion_expense', '推广费', TRUE, '聚合账户淘宝内容推广服务费。', 33),
        ('tmall_fund_content_promotion_alipay', '交易分账 + 淘宝内容推广服务费', '交易分账', 'promotion_expense', '推广费', TRUE, '支付宝淘宝内容推广服务费及退款净额。', 34),
        ('tmall_fund_taobaoke_commission', '交易分账 + 淘宝客佣金', '交易分账', 'promotion_expense', '推广费', TRUE, '淘宝客渠道推广佣金。', 35),
        ('tmall_fund_union_commission_transfer', '转账 + 淘宝联盟佣金', '转账', 'promotion_expense', '推广费', TRUE, '淘宝联盟佣金代扣与推广佣金返还净额。', 36),
        ('tmall_fund_union_commission_other', '其它 + 淘宝联盟佣金', '其它', 'promotion_expense', '推广费', TRUE, '其它业务类型下的淘宝联盟推广佣金返还，按负费用冲减推广费。', 37),

        ('tmall_fund_category_commission', '转账 + 天猫佣金（类目系统）', '转账', 'platform_commission', '平台佣金', TRUE, '天猫类目系统佣金扣款及返还净额。', 40),

        ('tmall_fund_basic_service_aggregate', '扣款 + 基础软件服务费', '扣款', 'platform_service_fee', '平台服务费', TRUE, '聚合账户基础软件服务费。', 50),
        ('tmall_fund_basic_service_alipay', '交易分账 + 基础软件服务费', '交易分账', 'platform_service_fee', '平台服务费', TRUE, '支付宝基础软件服务费。', 51),
        ('tmall_fund_guanghe_service_aggregate', '扣款 + 光合平台软件服务费', '扣款', 'platform_service_fee', '平台服务费', TRUE, '聚合账户光合平台软件服务费。', 52),
        ('tmall_fund_guanghe_service_alipay', '交易分账 + 光合平台软件服务费', '交易分账', 'platform_service_fee', '平台服务费', TRUE, '支付宝光合平台软件服务费。', 53),
        ('tmall_fund_pay_later_service', '交易分账 + 先用后付技术服务费', '交易分账', 'platform_service_fee', '平台服务费', TRUE, '先用后付技术服务费。', 54),
        ('tmall_fund_consumer_experience_service', '转账 + 消费者体验提升计划服务费', '转账', 'platform_service_fee', '平台服务费', TRUE, '消费者体验提升计划服务费。', 55),

        ('tmall_fund_red_packet_aggregate', '扣款 + 限时红包代商家垫付扣回', '扣款', 'marketing_discount_fee', '营销优惠费', TRUE, '聚合账户限时红包垫付扣回。', 60),
        ('tmall_fund_red_packet_refund_aggregate', '扣款退回 + 限时红包代商家垫付扣回', '扣款退回', 'marketing_discount_fee', '营销优惠费', TRUE, '限时红包垫付扣回退款，按负费用冲减营销优惠费。', 61),
        ('tmall_fund_red_packet_alipay', '交易分账 + 限时红包代商家垫付扣回', '交易分账', 'marketing_discount_fee', '营销优惠费', TRUE, '支付宝限时红包垫付扣回及退款净额。', 62),
        ('tmall_fund_tao_coin_aggregate', '扣款 + 淘金币软件服务费', '扣款', 'marketing_discount_fee', '营销优惠费', TRUE, '聚合账户淘金币软件服务费。', 63),
        ('tmall_fund_tao_coin_alipay', '交易分账 + 淘金币软件服务费', '交易分账', 'marketing_discount_fee', '营销优惠费', TRUE, '支付宝淘金币软件服务费及退款净额。', 64),
        ('tmall_fund_points', '转账 + 代扣返点积分', '转账', 'marketing_discount_fee', '营销优惠费', TRUE, '返点积分代扣与退回净额。', 65),

        ('tmall_fund_consolidation_logistics', '转账 + 商家集运物流服务费', '转账', 'logistics_fee', '物流费用', TRUE, '商家集运物流服务费。', 70),
        ('tmall_fund_consolidation_operation', '转账 + 商家集运中转操作费', '转账', 'logistics_fee', '物流费用', TRUE, '商家集运中转操作费。', 71),
        ('tmall_fund_small_payment', '其它 + 小额打款', '其它', 'small_payment', '小额打款', TRUE, '支付宝小额打款。', 80),
        ('tmall_fund_guarantee_insurance_recovery', '其它 + 天猫保证金履约险追偿', '其它', 'guarantee_insurance', '履约保险费', TRUE, '天猫保证金履约险追偿。', 81)
)
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
    is_active,
    created_by,
    updated_by
)
SELECT
    'tmall',
    '天猫',
    'fund',
    secondary_category_code,
    secondary_category_name,
    source_business_type,
    'none',
    NULL,
    100,
    primary_category_code,
    primary_category_name,
    include_in_platform_expense,
    classification_note,
    display_order,
    TRUE,
    'seed_tmall_platform_fee_mapping',
    'seed_tmall_platform_fee_mapping'
FROM seed
ON CONFLICT (platform_code, source_document_type, secondary_category_code)
DO NOTHING;

