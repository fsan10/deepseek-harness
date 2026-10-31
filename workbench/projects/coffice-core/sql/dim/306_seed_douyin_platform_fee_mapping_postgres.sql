INSERT INTO dim.dim_platform_fee_mapping (
    platform_code,
    platform_name,
    source_document_type,
    secondary_category_code,
    secondary_category_name,
    primary_category_code,
    primary_category_name,
    include_in_platform_expense,
    classification_note,
    display_order,
    created_by,
    updated_by
)
VALUES
    (
        'douyin', '抖音', 'settlement',
        'platform_service_fee', '平台服务费',
        'platform_service_fee', '平台服务费',
        TRUE, '结算单平台技术服务费，正常支出为正、退回为负。', 10,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'settlement',
        'creator_commission', '达人佣金',
        'influencer_commission', '达人佣金',
        TRUE, '与招商服务费共同归入一级分类达人佣金。', 20,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'settlement',
        'service_provider_commission', '服务商佣金',
        'service_provider_commission', '服务商佣金',
        TRUE, '保留独立一级分类，财务可按实际管理口径调整。', 30,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'settlement',
        'channel_share', '渠道分成',
        'channel_share', '渠道分成',
        TRUE, '保留独立一级分类，财务可按实际管理口径调整。', 40,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'settlement',
        'merchant_recruitment_service_fee', '招商服务费',
        'influencer_commission', '达人佣金',
        TRUE, '按照用户确认口径，与达人佣金共同归入一级分类达人佣金。', 21,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'settlement',
        'offsite_promotion_fee', '站外推广费',
        'promotion_expense', '推广费',
        TRUE, '站外推广成交产生的推广费用。', 50,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'settlement',
        'other_share', '其他分成',
        'other_platform_expense', '其他平台费用',
        TRUE, '无法归入已知分成类型的其他分成。', 90,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'fund',
        'goods_settlement_inflow', '货款结算入账',
        'non_expense_goods_settlement', '非费用-货款结算',
        FALSE, '结算净额入账，不是新增收入或费用。', 900,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'fund',
        'refund_order_split', '退款-订单退款触发-分账',
        'non_expense_refund_reconciliation', '非费用-退款勾稽',
        FALSE, '退款相关入账，已与结算单退款及费用退回勾稽。', 910,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'fund',
        'refund_order_reverse_split', '退款-订单退款触发-退分账',
        'non_expense_refund_reconciliation', '非费用-退款勾稽',
        FALSE, '退款相关入账，已与结算单退款及费用退回勾稽。', 911,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'fund',
        'pickup_shipping_fee', '上门取件运费',
        'reverse_logistics_expense', '退货物流费',
        TRUE, '资金单独有的退货履约支出。', 70,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'fund',
        'small_payment', '小额打款',
        'after_sales_expense', '售后费用',
        TRUE, '商家售后安抚、差价补偿等小额打款。', 61,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'fund',
        'promotion_clawback', '平台返现/返券活动追缴用户退回平台',
        'marketing_activity_expense', '营销活动费用',
        TRUE, '平台返现或返券活动追缴形成的商家实际出账。', 55,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'fund',
        'withdrawal', '提现',
        'non_expense_account_transfer', '非费用-账户划转',
        FALSE, '平台账户提现属于资金划转，不计平台费用。', 920,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'fund',
        'rights_insurance', '权益保险',
        'fulfillment_guarantee_expense', '履约保障费',
        TRUE, '资金单独有的权益保险及履约保障支出。', 60,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'fund',
        'consumer_compensation', '消费者赔付',
        'after_sales_expense', '售后费用',
        TRUE, '商家向消费者赔付形成的实际出账。', 62,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'fund',
        'refund_fast_stage_two_replenishment', '退款-极速退二阶段商家资金回补',
        'non_expense_refund_reconciliation', '非费用-退款勾稽',
        FALSE, '退款相关出账，已计入结算单退款冲销。', 912,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'fund',
        'refund_after_settlement_to_user', '退款-结算后退款-退用户',
        'non_expense_refund_reconciliation', '非费用-退款勾稽',
        FALSE, '结算后退款出账，已由结算单负收入冲销。', 913,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'fund',
        'refund_order_subsidy_return', '退款-订单退款触发-退补贴',
        'non_expense_refund_reconciliation', '非费用-退款勾稽',
        FALSE, '退款相关退补贴出账，已与结算单勾稽。', 914,
        'seed', 'seed'
    ),
    (
        'douyin', '抖音', 'fund',
        'refund_transfer_payment_deduction', '退款-退转付扣减商家货款',
        'non_expense_refund_reconciliation', '非费用-退款勾稽',
        FALSE, '退款相关货款扣减，已与结算单勾稽。', 915,
        'seed', 'seed'
    )
ON CONFLICT DO NOTHING;
