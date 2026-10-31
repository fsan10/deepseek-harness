CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_xhs_operating_sales_order_item_detail
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
            'COMMENT ON COLUMN dwd.dwd_xhs_operating_sales_order_item_detail.%I IS %L',
            item.attname,
            REPLACE(COALESCE(item.description, item.attname), '抖音', '小红书')
        );
    END LOOP;
END $$;

COMMENT ON TABLE dwd.dwd_xhs_operating_sales_order_item_detail IS '小红书运营成交指标专属DWD，一行一个ODS订单SKU商品行，保留全部订单和售后状态，不执行刷单或退款筛选。';
COMMENT ON COLUMN dwd.dwd_xhs_operating_sales_order_item_detail.source_shop_code IS '小红书源文件仅提供店铺名称，标准店铺编码严格来自批次店铺上下文；本字段保留为空。';
COMMENT ON COLUMN dwd.dwd_xhs_operating_sales_order_item_detail.main_order_no IS '小红书订单号，成交订单数和刷单整单排除均按此字段处理。';
COMMENT ON COLUMN dwd.dwd_xhs_operating_sales_order_item_detail.sub_order_no IS '小红书订单SKU商品行稳定键，由订单号、商品规格字段和同商品行序号组成，与导入批次无关。';
COMMENT ON COLUMN dwd.dwd_xhs_operating_sales_order_item_detail.stat_date IS '运营成交统计日期，取ODS订单创建时间的自然日。';
COMMENT ON COLUMN dwd.dwd_xhs_operating_sales_order_item_detail.order_submitted_at IS '订单创建时间，来自ODS订单创建时间。';
COMMENT ON COLUMN dwd.dwd_xhs_operating_sales_order_item_detail.merchant_code IS '公司商家编码，来自ODS商家编码，组合装在产品DWS拆分。';
COMMENT ON COLUMN dwd.dwd_xhs_operating_sales_order_item_detail.product_name IS '平台SKU名称，来自ODS SKU名称，仅作订单链接审计。';
COMMENT ON COLUMN dwd.dwd_xhs_operating_sales_order_item_detail.product_spec IS '平台SKU规格，来自ODS SKU规格，用于识别组合装赠品组件。';
COMMENT ON COLUMN dwd.dwd_xhs_operating_sales_order_item_detail.product_unit_price IS '商品行GMV原值，来自ODS商品总价(元)，单位元，不乘数量。';
COMMENT ON COLUMN dwd.dwd_xhs_operating_sales_order_item_detail.order_pay_amount IS '刷单判断金额，来自ODS用户应付金额(元)，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_operating_sales_order_item_detail.traffic_content_type IS 'ODS没有稳定流量体裁字段，固定为未提供。';
COMMENT ON COLUMN dwd.dwd_xhs_operating_sales_order_item_detail.traffic_channel IS 'ODS没有稳定流量渠道字段，固定为未提供。';
