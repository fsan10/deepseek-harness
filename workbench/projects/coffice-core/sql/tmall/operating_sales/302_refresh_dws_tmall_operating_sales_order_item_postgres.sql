TRUNCATE TABLE dws.dws_tmall_operating_sales_order_item;

INSERT INTO dws.dws_tmall_operating_sales_order_item (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    main_order_no, sub_order_no, order_status, after_sale_status,
    product_id, product_name, traffic_content_type, traffic_channel,
    product_unit_price, order_pay_amount, gmv_amount, refund_amount,
    is_closed_refund, sold_unit_count, included_sub_order_count,
    source_id, source_batch_id, source_updated_at, updated_at
)
WITH prepared AS (
    SELECT
        d.*,
        SUM(d.order_pay_amount) OVER (
            PARTITION BY d.platform_code, d.shop_code, d.main_order_no
        ) AS main_order_pay_amount,
        (
            COALESCE(d.product_name, '') = 'MOCK推荐官'
            OR COALESCE(d.product_name, '') LIKE '%赠品勿拍%'
        ) AS is_auxiliary_line
    FROM dwd.dwd_tmall_operating_sales_order_item_detail d
), effective AS (
    SELECT
        p.*,
        CASE WHEN p.is_auxiliary_line THEN 0 ELSE p.gmv_amount END
            AS effective_gmv_amount
    FROM prepared p
    WHERE p.main_order_pay_amount <= 2000
)
SELECT
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    main_order_no,
    sub_order_no,
    order_status,
    after_sale_status,
    product_id,
    product_name,
    '未提供',
    '未提供',
    product_unit_price,
    order_pay_amount,
    effective_gmv_amount,
    CASE WHEN order_status = '交易关闭' THEN effective_gmv_amount ELSE 0 END,
    order_status = '交易关闭',
    CASE WHEN effective_gmv_amount > 0 THEN product_quantity ELSE 0 END,
    1,
    source_id,
    source_batch_id,
    source_updated_at,
    NOW()
FROM effective;
