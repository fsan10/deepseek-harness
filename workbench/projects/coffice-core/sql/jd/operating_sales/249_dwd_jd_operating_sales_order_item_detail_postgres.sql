CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_jd_operating_sales_order_item_detail
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
            'COMMENT ON COLUMN dwd.dwd_jd_operating_sales_order_item_detail.%I IS %L',
            item.attname,
            REPLACE(COALESCE(item.description, item.attname), '抖音', '京东')
        );
    END LOOP;
END $$;

COMMENT ON TABLE dwd.dwd_jd_operating_sales_order_item_detail IS '京东运营成交指标专属DWD，一行一个ODS订单商品行，保留全部订单状态，不执行刷单或退款筛选。';
COMMENT ON COLUMN dwd.dwd_jd_operating_sales_order_item_detail.source_shop_code IS '京东订单源门店字段当前为空且不可靠，保留为空；标准店铺严格来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_jd_operating_sales_order_item_detail.main_order_no IS '京东订单号，成交订单数和刷单整单排除均按此字段处理。';
COMMENT ON COLUMN dwd.dwd_jd_operating_sales_order_item_detail.sub_order_no IS '京东订单商品行稳定键，由订单号、商品规格字段和同商品行序号组成，与导入批次无关。';
COMMENT ON COLUMN dwd.dwd_jd_operating_sales_order_item_detail.stat_date IS '运营成交统计日期，取ODS下单时间的自然日。';
COMMENT ON COLUMN dwd.dwd_jd_operating_sales_order_item_detail.order_submitted_at IS '订单下单时间，来自ODS下单时间。';
COMMENT ON COLUMN dwd.dwd_jd_operating_sales_order_item_detail.after_sale_status IS '京东订单ODS未提供售后状态，保留为空。';
COMMENT ON COLUMN dwd.dwd_jd_operating_sales_order_item_detail.merchant_code IS '公司商家编码，来自ODS商家SKUID，组合装在产品DWS拆分。';
COMMENT ON COLUMN dwd.dwd_jd_operating_sales_order_item_detail.product_spec IS '赠品判断文本，使用ODS商品名称。';
COMMENT ON COLUMN dwd.dwd_jd_operating_sales_order_item_detail.product_unit_price IS '商品行GMV原值，来自ODS京东价，单位元，不乘数量。';
COMMENT ON COLUMN dwd.dwd_jd_operating_sales_order_item_detail.order_pay_amount IS '刷单判断金额，来自ODS应付金额，单位元。';
COMMENT ON COLUMN dwd.dwd_jd_operating_sales_order_item_detail.traffic_content_type IS '流量结构一级维度，来自ODS订单来源。';
COMMENT ON COLUMN dwd.dwd_jd_operating_sales_order_item_detail.traffic_channel IS '流量结构二级维度，来自ODS订单渠道。';
