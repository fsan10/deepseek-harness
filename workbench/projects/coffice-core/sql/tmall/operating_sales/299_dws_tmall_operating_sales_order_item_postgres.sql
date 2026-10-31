CREATE SCHEMA IF NOT EXISTS dws;

DROP TABLE IF EXISTS dws.dws_tmall_operating_sales_order_item;

CREATE TABLE dws.dws_tmall_operating_sales_order_item
    (LIKE dws.dws_douyin_operating_sales_order_item INCLUDING ALL);

DO $$
DECLARE
    item RECORD;
BEGIN
    FOR item IN
        SELECT attname, col_description(attrelid, attnum) AS description
        FROM pg_attribute
        WHERE attrelid = 'dws.dws_douyin_operating_sales_order_item'::REGCLASS
          AND attnum > 0
          AND NOT attisdropped
    LOOP
        EXECUTE FORMAT(
            'COMMENT ON COLUMN dws.dws_tmall_operating_sales_order_item.%I IS %L',
            item.attname,
            REPLACE(COALESCE(item.description, item.attname), '抖音', '天猫')
        );
    END LOOP;
END $$;

COMMENT ON TABLE dws.dws_tmall_operating_sales_order_item IS '天猫运营成交订单行DWS，一行一个非刷单子订单；主订单买家应付合计大于2000元整单排除，辅助行保留为零GMV以维持主订单计数。';
COMMENT ON COLUMN dws.dws_tmall_operating_sales_order_item.product_unit_price IS '来源买家应付货款原值，单位元；MOCK推荐官和赠品勿拍辅助行在gmv_amount中归零。';
COMMENT ON COLUMN dws.dws_tmall_operating_sales_order_item.order_pay_amount IS '来源子订单买家应付货款，按主订单合计大于2000元时整单不进入DWS。';
COMMENT ON COLUMN dws.dws_tmall_operating_sales_order_item.gmv_amount IS '天猫运营GMV：买家应付货款；MOCK推荐官和赠品勿拍辅助行归零，不按订单状态筛选，单位元。';
COMMENT ON COLUMN dws.dws_tmall_operating_sales_order_item.refund_amount IS '订单状态为交易关闭时取同口径有效商品行GMV，否则为0，单位元。';
COMMENT ON COLUMN dws.dws_tmall_operating_sales_order_item.is_closed_refund IS '订单状态是否为交易关闭；辅助行即使命中状态也只产生0元退款。';
COMMENT ON COLUMN dws.dws_tmall_operating_sales_order_item.sold_unit_count IS '有效商品行GMV大于0时取购买数量；推荐官、赠品勿拍及零金额行记0件。';
COMMENT ON COLUMN dws.dws_tmall_operating_sales_order_item.traffic_content_type IS '销售明细未提供流量体裁，固定为未提供。';
COMMENT ON COLUMN dws.dws_tmall_operating_sales_order_item.traffic_channel IS '销售明细未提供流量渠道，固定为未提供。';
