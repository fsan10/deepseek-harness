TRUNCATE TABLE dws.dws_wechat_channels_operating_sales_order_item;

INSERT INTO dws.dws_wechat_channels_operating_sales_order_item (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    main_order_no, sub_order_no, order_status, after_sale_status,
    product_id, product_name, traffic_content_type, traffic_channel,
    product_unit_price, order_pay_amount, gmv_amount, refund_amount,
    is_closed_refund, sold_unit_count, included_sub_order_count,
    source_id, source_batch_id, source_updated_at, updated_at
)
SELECT
    d.stat_date,
    d.platform_code,
    d.platform_name,
    d.shop_code,
    d.shop_name,
    d.main_order_no,
    d.sub_order_no,
    d.order_status,
    d.after_sale_status,
    d.product_id,
    d.product_name,
    CASE
        WHEN d.traffic_content_type IS NULL
          OR BTRIM(d.traffic_content_type) IN ('', '-', '暂无来源')
            THEN '未提供'
        ELSE BTRIM(d.traffic_content_type)
    END,
    CASE
        WHEN d.traffic_channel IS NULL
          OR BTRIM(d.traffic_channel) IN ('', '-', '暂无来源')
            THEN '未提供'
        ELSE BTRIM(d.traffic_channel)
    END,
    d.product_unit_price,
    d.order_pay_amount,
    d.gmv_amount,
    CASE WHEN d.order_status = '已取消' THEN d.gmv_amount ELSE 0 END,
    d.order_status = '已取消',
    CASE WHEN d.gmv_amount > 0 THEN d.product_quantity ELSE 0 END,
    1,
    d.source_id,
    d.source_batch_id,
    d.source_updated_at,
    NOW()
FROM dwd.dwd_wechat_channels_operating_sales_order_item_detail d
WHERE NOT EXISTS (
    SELECT 1
    FROM dwd.dwd_wechat_channels_operating_sales_order_item_detail brush
    WHERE brush.platform_code = d.platform_code
      AND brush.shop_code = d.shop_code
      AND brush.main_order_no = d.main_order_no
      AND brush.order_pay_amount >= 2000
);
