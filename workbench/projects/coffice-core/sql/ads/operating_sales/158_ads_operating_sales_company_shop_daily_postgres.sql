CREATE SCHEMA IF NOT EXISTS ads;

CREATE TABLE IF NOT EXISTS ads.ads_operating_sales_company_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    gmv_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    refund_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    refund_rate NUMERIC(18,6) NOT NULL DEFAULT 0,
    transaction_order_count BIGINT NOT NULL DEFAULT 0,
    sold_unit_count NUMERIC(18,2) NOT NULL DEFAULT 0,
    transaction_unit_price NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_sub_order_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (stat_date, platform_code, company_code, shop_code)
);

COMMENT ON TABLE ads.ads_operating_sales_company_shop_daily IS '运营成交公司店铺日ADS，一天、平台、公司、店铺一行，服务GMV、退款、退款率、主订单数、件单价指标卡及平台GMV占比。';
COMMENT ON COLUMN ads.ads_operating_sales_company_shop_daily.stat_date IS '各平台确认的成交统计日期自然日，用作DataEase日期筛选字段。';
COMMENT ON COLUMN ads.ads_operating_sales_company_shop_daily.platform_code IS '标准平台编码，作为平台稳定标识。';
COMMENT ON COLUMN ads.ads_operating_sales_company_shop_daily.platform_name IS '平台展示名称，用作平台筛选和各平台GMV占比类别。';
COMMENT ON COLUMN ads.ads_operating_sales_company_shop_daily.company_code IS '公司稳定编码，来自有效期内的平台店铺公司DIM；未命中为unmapped。';
COMMENT ON COLUMN ads.ads_operating_sales_company_shop_daily.company_name IS '公司完整名称，用作DataEase公司筛选；未命中为未匹配公司。';
COMMENT ON COLUMN ads.ads_operating_sales_company_shop_daily.shop_code IS '标准店铺编码，来自平台DWS。';
COMMENT ON COLUMN ads.ads_operating_sales_company_shop_daily.shop_name IS '标准店铺名称，优先来自DIM，用作DataEase店铺筛选。';
COMMENT ON COLUMN ads.ads_operating_sales_company_shop_daily.gmv_amount IS '运营总成交额GMV，整单排除订单应付或实付金额达到2000元的刷单订单后，直接汇总平台确认的商品行原价，不乘商品数量，单位元。';
COMMENT ON COLUMN ads.ads_operating_sales_company_shop_daily.refund_amount IS '总退款代理金额，按各平台已确认的订单关闭或取消状态汇总商品行GMV，售后状态不参与，单位元。';
COMMENT ON COLUMN ads.ads_operating_sales_company_shop_daily.refund_rate IS '日退款率，refund_amount除以gmv_amount；跨日期筛选应使用两字段汇总后相除。';
COMMENT ON COLUMN ads.ads_operating_sales_company_shop_daily.transaction_order_count IS '成交总订单数，按非刷单订单号在成交统计日期、平台、公司、店铺内去重。';
COMMENT ON COLUMN ads.ads_operating_sales_company_shop_daily.sold_unit_count IS '成交件数分母，仅汇总商品行GMV大于0的商品数量，排除零金额赠品，单位件。';
COMMENT ON COLUMN ads.ads_operating_sales_company_shop_daily.transaction_unit_price IS '日成交件单价，gmv_amount除以sold_unit_count，单位元每件；跨日期筛选应使用两字段汇总后相除。';
COMMENT ON COLUMN ads.ads_operating_sales_company_shop_daily.included_sub_order_count IS '纳入计算的非刷单订单商品行数，包括零GMV赠品行，不按订单状态或售后状态筛选。';
COMMENT ON COLUMN ads.ads_operating_sales_company_shop_daily.source_updated_at IS '参与本行汇总的DWS记录最晚来源更新时间。';
COMMENT ON COLUMN ads.ads_operating_sales_company_shop_daily.created_at IS 'ADS记录创建时间。';
COMMENT ON COLUMN ads.ads_operating_sales_company_shop_daily.updated_at IS 'ADS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_ads_operating_sales_company_daily_company
    ON ads.ads_operating_sales_company_shop_daily (company_code, stat_date);

CREATE INDEX IF NOT EXISTS idx_ads_operating_sales_company_daily_platform
    ON ads.ads_operating_sales_company_shop_daily (platform_code, stat_date);

CREATE INDEX IF NOT EXISTS idx_ads_operating_sales_company_daily_shop
    ON ads.ads_operating_sales_company_shop_daily (shop_code, stat_date);
