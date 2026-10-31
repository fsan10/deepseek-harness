CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_xhs_operating_sales_order_item
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
            'COMMENT ON COLUMN dws.dws_xhs_operating_sales_order_item.%I IS %L',
            item.attname,
            REPLACE(COALESCE(item.description, item.attname), '抖音', '小红书')
        );
    END LOOP;
END $$;

COMMENT ON TABLE dws.dws_xhs_operating_sales_order_item IS '小红书运营成交订单行DWS，一行一个非刷单订单SKU商品行；用户应付金额达到2000元的订单整单排除。';
COMMENT ON COLUMN dws.dws_xhs_operating_sales_order_item.refund_amount IS '小红书当前订单状态没有已关闭等价枚举，退款金额固定为0；售后状态不作为退款代理。';
COMMENT ON COLUMN dws.dws_xhs_operating_sales_order_item.is_closed_refund IS '小红书当前没有已关闭等价订单状态，固定为false。';
COMMENT ON COLUMN dws.dws_xhs_operating_sales_order_item.traffic_content_type IS 'ODS未提供稳定流量体裁，固定为未提供。';
COMMENT ON COLUMN dws.dws_xhs_operating_sales_order_item.traffic_channel IS 'ODS未提供稳定流量渠道，固定为未提供。';
