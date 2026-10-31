CREATE SCHEMA IF NOT EXISTS dwd;

DROP TABLE IF EXISTS dwd.dwd_tmall_operating_sales_order_item_detail;

CREATE TABLE dwd.dwd_tmall_operating_sales_order_item_detail
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
            'COMMENT ON COLUMN dwd.dwd_tmall_operating_sales_order_item_detail.%I IS %L',
            item.attname,
            REPLACE(COALESCE(item.description, item.attname), '抖音', '天猫')
        );
    END LOOP;
END $$;

COMMENT ON TABLE dwd.dwd_tmall_operating_sales_order_item_detail IS '天猫运营成交专属DWD，一行一个标准店铺下最新子订单版本；清洗买家应付货款、商品数量和商家编码，保留全部订单状态及辅助行，不执行刷单、退款或赠品筛选。';
COMMENT ON COLUMN dwd.dwd_tmall_operating_sales_order_item_detail.source_shop_code IS '新销售明细不提供店铺字段，标准店铺严格来自批次上下文，本字段为空。';
COMMENT ON COLUMN dwd.dwd_tmall_operating_sales_order_item_detail.main_order_no IS '天猫主订单编号；成交订单去重及主订单买家应付合计大于2000元刷单排除按此字段执行。';
COMMENT ON COLUMN dwd.dwd_tmall_operating_sales_order_item_detail.sub_order_no IS '天猫子订单编号；标准店铺下作为DWD最新版本业务键。';
COMMENT ON COLUMN dwd.dwd_tmall_operating_sales_order_item_detail.stat_date IS '运营成交统计日期，严格取订单创建时间自然日。';
COMMENT ON COLUMN dwd.dwd_tmall_operating_sales_order_item_detail.order_submitted_at IS '清洗后的订单创建时间。';
COMMENT ON COLUMN dwd.dwd_tmall_operating_sales_order_item_detail.after_sale_status IS '新销售明细不提供售后状态，固定为空且不参与指标。';
COMMENT ON COLUMN dwd.dwd_tmall_operating_sales_order_item_detail.product_id IS '精简ODS不保存平台商品ID，本字段为空；产品占比严格按商家编码映射。';
COMMENT ON COLUMN dwd.dwd_tmall_operating_sales_order_item_detail.merchant_code IS '来源商家编码；全角加号归一后在产品DWS拆分并映射公司统一产品。';
COMMENT ON COLUMN dwd.dwd_tmall_operating_sales_order_item_detail.product_name IS '来源商品标题；DWS用于识别MOCK推荐官和赠品勿拍辅助行。';
COMMENT ON COLUMN dwd.dwd_tmall_operating_sales_order_item_detail.product_spec IS '来源商品属性；产品DWS用于识别“赠”字后的赠品编码组件。';
COMMENT ON COLUMN dwd.dwd_tmall_operating_sales_order_item_detail.product_quantity IS '来源购买数量清洗值，单位件。';
COMMENT ON COLUMN dwd.dwd_tmall_operating_sales_order_item_detail.product_unit_price IS '来源子订单买家应付货款；作为商品行原始GMV金额，不乘购买数量，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_operating_sales_order_item_detail.order_pay_amount IS '来源子订单买家应付货款；按主订单汇总后用于识别合计大于2000元刷单，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_operating_sales_order_item_detail.gmv_amount IS 'DWD原始商品行GMV，等于买家应付货款；DWD不排除辅助行，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_operating_sales_order_item_detail.traffic_content_type IS '销售明细未提供流量体裁，固定为未提供。';
COMMENT ON COLUMN dwd.dwd_tmall_operating_sales_order_item_detail.traffic_channel IS '销售明细未提供流量渠道，固定为未提供。';
