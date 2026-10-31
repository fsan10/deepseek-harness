CREATE SCHEMA IF NOT EXISTS dws;

DROP TABLE IF EXISTS dws.dws_tmall_operating_sales_product_allocation;

CREATE TABLE dws.dws_tmall_operating_sales_product_allocation
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
            'COMMENT ON COLUMN dws.dws_tmall_operating_sales_product_allocation.%I IS %L',
            item.attname,
            REPLACE(COALESCE(item.description, item.attname), '抖音', '天猫')
        );
    END LOOP;
END $$;

COMMENT ON TABLE dws.dws_tmall_operating_sales_product_allocation IS '天猫运营商品组件DWS；推荐官辅助行排除，赠品勿拍和规格赠品保留但GMV为0，购物金作为非商品识别。';
COMMENT ON COLUMN dws.dws_tmall_operating_sales_product_allocation.source_line_gmv_amount IS '来源有效商品行GMV，取买家应付货款且不按订单状态筛选，单位元。';
COMMENT ON COLUMN dws.dws_tmall_operating_sales_product_allocation.allocated_gmv_amount IS '按付费编码组件数量权重分摊的买家应付货款；最后一个组件吸收分币差，单位元。';
