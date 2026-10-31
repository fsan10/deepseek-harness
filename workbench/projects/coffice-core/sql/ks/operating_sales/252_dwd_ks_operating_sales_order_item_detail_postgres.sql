CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_ks_operating_sales_order_item_detail
    (LIKE dwd.dwd_douyin_operating_sales_order_item_detail INCLUDING ALL);

DO $$
DECLARE
    item RECORD;
BEGIN
    FOR item IN
        SELECT attname, col_description(attrelid, attnum) AS description
        FROM pg_attribute
        WHERE attrelid = 'dwd.dwd_douyin_operating_sales_order_item_detail'::REGCLASS
          AND attnum > 0
          AND NOT attisdropped
    LOOP
        EXECUTE FORMAT(
            'COMMENT ON COLUMN dwd.dwd_ks_operating_sales_order_item_detail.%I IS %L',
            item.attname,
            REPLACE(COALESCE(item.description, item.attname), '抖音', '快手')
        );
    END LOOP;
END $$;

COMMENT ON TABLE dwd.dwd_ks_operating_sales_order_item_detail IS '快手运营成交指标专属DWD，一行一个ODS订单商品行，保留全部订单和售后状态，不执行刷单或退款筛选。';
COMMENT ON COLUMN dwd.dwd_ks_operating_sales_order_item_detail.source_shop_code IS '快手源服务门店不是可靠标准店铺编码，保留为空；标准店铺严格来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_ks_operating_sales_order_item_detail.main_order_no IS '快手订单号，成交订单数和刷单整单排除均按此字段处理。';
COMMENT ON COLUMN dwd.dwd_ks_operating_sales_order_item_detail.sub_order_no IS '快手订单商品行稳定键，由订单号、商品规格字段和同商品行序号组成，与导入批次无关。';
COMMENT ON COLUMN dwd.dwd_ks_operating_sales_order_item_detail.stat_date IS '运营成交统计日期，取ODS订单创建时间的自然日。';
COMMENT ON COLUMN dwd.dwd_ks_operating_sales_order_item_detail.order_submitted_at IS '订单创建时间，来自ODS订单创建时间。';
COMMENT ON COLUMN dwd.dwd_ks_operating_sales_order_item_detail.merchant_code IS '来源SKU编码原值；历史缩写仅在快手产品分摊DWS归一为公司编码格式。';
COMMENT ON COLUMN dwd.dwd_ks_operating_sales_order_item_detail.product_unit_price IS '商品行GMV原值，来自ODS商品单价，清除币种符号后解析，单位元，不乘数量。';
COMMENT ON COLUMN dwd.dwd_ks_operating_sales_order_item_detail.order_pay_amount IS '刷单判断金额，来自ODS实付款，清除币种符号后解析，单位元。';
COMMENT ON COLUMN dwd.dwd_ks_operating_sales_order_item_detail.traffic_content_type IS '流量结构一级维度，来自ODS订单载体。';
COMMENT ON COLUMN dwd.dwd_ks_operating_sales_order_item_detail.traffic_channel IS '流量结构二级维度，来自ODS渠道。';
