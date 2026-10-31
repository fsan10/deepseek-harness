CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_wechat_channels_operating_sales_product_allocation
    (LIKE dws.dws_douyin_operating_sales_product_allocation INCLUDING ALL);

DO $$
DECLARE
    item RECORD;
BEGIN
    FOR item IN
        SELECT attname, col_description(attrelid, attnum) AS description
        FROM pg_attribute
        WHERE attrelid = 'dws.dws_douyin_operating_sales_product_allocation'::REGCLASS
          AND attnum > 0
          AND NOT attisdropped
    LOOP
        EXECUTE FORMAT(
            'COMMENT ON COLUMN dws.dws_wechat_channels_operating_sales_product_allocation.%I IS %L',
            item.attname,
            REPLACE(COALESCE(item.description, item.attname), '抖音', '视频号')
        );
    END LOOP;
END $$;

COMMENT ON TABLE dws.dws_wechat_channels_operating_sales_product_allocation IS '视频号运营商品组件DWS；付费和赠品组件均保留，赠品GMV为0。';
COMMENT ON COLUMN dws.dws_wechat_channels_operating_sales_product_allocation.sub_order_no IS '视频号订单商品行稳定键，由订单号、商品规格字段和同商品行序号组成，与导入批次无关。';
