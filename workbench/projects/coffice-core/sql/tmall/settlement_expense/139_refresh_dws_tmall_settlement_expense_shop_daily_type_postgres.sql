TRUNCATE TABLE dws.dws_tmall_settlement_expense_shop_daily_type;

INSERT INTO dws.dws_tmall_settlement_expense_shop_daily_type (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    expense_type_code, expense_type_name, expense_amount, included_event_count,
    source_updated_at, updated_at
)
SELECT
    stat_date, platform_code, MAX(platform_name), shop_code, MAX(shop_name),
    CASE expense_item
        WHEN '先用后付服务费' THEN 'pay_later_service_fee'
        WHEN '光合平台软件服务费' THEN 'guanghe_software_service_fee'
        WHEN '品牌新享-首单拉新计划(KY_ITEM)' THEN 'brand_new_customer_plan'
        WHEN '基础软件服务费' THEN 'basic_software_service_fee'
        WHEN '淘金币软件服务费' THEN 'tao_coin_software_service_fee'
        WHEN '淘宝内容推广服务费' THEN 'taobao_content_promotion_fee'
        WHEN '天猫佣金（类目系统）' THEN 'tmall_category_commission'
        WHEN '限时红包代商家垫付扣回' THEN 'limited_red_packet_recovery'
        ELSE 'tmall_' || MD5(expense_item)
    END,
    expense_item,
    ROUND(SUM(expense_amount), 2),
    COUNT(*), MAX(source_updated_at), NOW()
FROM dwd.dwd_tmall_settlement_expense_event_detail
WHERE expense_amount <> 0
GROUP BY stat_date, platform_code, shop_code, expense_item;

