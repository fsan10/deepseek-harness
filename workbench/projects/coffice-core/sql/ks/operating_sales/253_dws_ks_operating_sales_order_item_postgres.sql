CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_ks_operating_sales_order_item
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
            'COMMENT ON COLUMN dws.dws_ks_operating_sales_order_item.%I IS %L',
            item.attname,
            REPLACE(COALESCE(item.description, item.attname), '抖音', '快手')
        );
    END LOOP;
END $$;

COMMENT ON TABLE dws.dws_ks_operating_sales_order_item IS '快手运营成交订单行DWS，一行一个非刷单订单商品行；实付款达到2000元的订单整单排除。';
COMMENT ON COLUMN dws.dws_ks_operating_sales_order_item.refund_amount IS '快手退款金额；订单状态为交易关闭时取本行GMV，否则为0，单位元。';
COMMENT ON COLUMN dws.dws_ks_operating_sales_order_item.is_closed_refund IS '订单状态是否为交易关闭；true表示本行GMV计入快手退款。';
COMMENT ON COLUMN dws.dws_ks_operating_sales_order_item.traffic_content_type IS '标准化流量结构一级维度，来源订单载体；空值、横杠和暂无来源统一为未提供。';
COMMENT ON COLUMN dws.dws_ks_operating_sales_order_item.traffic_channel IS '标准化流量结构二级维度，来源渠道；空值、横杠和暂无来源统一为未提供。';
