DO $$
DECLARE
    missing_influencer_id_count BIGINT;
BEGIN
    SELECT COUNT(*) INTO missing_influencer_id_count
    FROM dwd.dwd_douyin_influencer_sales_order_item_detail d
    WHERE d.traffic_source = '精选联盟'
      AND (d.influencer_id_raw IS NULL OR d.influencer_id_raw = '-')
      AND NOT EXISTS (
          SELECT 1
          FROM dwd.dwd_douyin_influencer_sales_order_item_detail brush
          WHERE brush.platform_code = d.platform_code
            AND brush.shop_code = d.shop_code
            AND brush.main_order_no = d.main_order_no
            AND brush.order_pay_amount > 2000
      );

    IF missing_influencer_id_count > 0 THEN
        RAISE EXCEPTION '精选联盟非刷单范围有%条记录缺少达人ID，未确认空ID口径，停止刷新DWS', missing_influencer_id_count;
    END IF;
END $$;

TRUNCATE TABLE dws.dws_douyin_influencer_sales_order_item;

INSERT INTO dws.dws_douyin_influencer_sales_order_item (
    stat_date,
    stat_month,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    main_order_no,
    sub_order_no,
    traffic_source,
    order_status,
    after_sale_status,
    influencer_id,
    influencer_name,
    influencer_key,
    traffic_channel,
    product_unit_price,
    order_pay_amount,
    gmv_amount,
    refund_amount,
    is_closed_refund,
    included_sub_order_count,
    source_id,
    source_batch_id,
    source_updated_at,
    updated_at
)
SELECT
    d.stat_date,
    DATE_TRUNC('month', d.stat_date)::date,
    d.platform_code,
    d.platform_name,
    d.shop_code,
    d.shop_name,
    d.main_order_no,
    d.sub_order_no,
    d.traffic_source,
    d.order_status,
    d.after_sale_status,
    d.influencer_id_raw,
    CASE
        WHEN d.influencer_id_raw = '0' THEN '其他'
        ELSE COALESCE(d.influencer_name_raw, '未命名达人')
    END,
    d.platform_code || '|' || d.influencer_id_raw,
    d.traffic_channel,
    d.product_unit_price,
    d.order_pay_amount,
    d.product_unit_price,
    CASE WHEN d.order_status = '已关闭' THEN d.product_unit_price ELSE 0 END,
    d.order_status = '已关闭',
    1,
    d.source_id,
    d.source_batch_id,
    d.source_updated_at,
    NOW()
FROM dwd.dwd_douyin_influencer_sales_order_item_detail d
WHERE d.traffic_source = '精选联盟'
  AND NOT EXISTS (
      SELECT 1
      FROM dwd.dwd_douyin_influencer_sales_order_item_detail brush
      WHERE brush.platform_code = d.platform_code
        AND brush.shop_code = d.shop_code
        AND brush.main_order_no = d.main_order_no
        AND brush.order_pay_amount > 2000
  );
