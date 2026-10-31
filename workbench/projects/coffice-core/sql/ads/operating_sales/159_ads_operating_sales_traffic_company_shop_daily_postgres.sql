CREATE SCHEMA IF NOT EXISTS ads;

CREATE TABLE IF NOT EXISTS ads.ads_operating_sales_traffic_company_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    traffic_content_type VARCHAR(128) NOT NULL,
    traffic_channel VARCHAR(128) NOT NULL,
    gmv_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_sub_order_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (
        stat_date,
        platform_code,
        company_code,
        shop_code,
        traffic_content_type,
        traffic_channel
    )
);

COMMENT ON TABLE ads.ads_operating_sales_traffic_company_shop_daily IS '运营成交流量结构ADS，一天、平台、公司、店铺、流量体裁和流量渠道一行，服务两级流量结构及对应GMV占比。';
COMMENT ON COLUMN ads.ads_operating_sales_traffic_company_shop_daily.stat_date IS '各平台确认的成交统计日期自然日，用作DataEase日期筛选字段。';
COMMENT ON COLUMN ads.ads_operating_sales_traffic_company_shop_daily.platform_code IS '标准平台编码。';
COMMENT ON COLUMN ads.ads_operating_sales_traffic_company_shop_daily.platform_name IS '平台展示名称，用作DataEase平台筛选。';
COMMENT ON COLUMN ads.ads_operating_sales_traffic_company_shop_daily.company_code IS '公司稳定编码，来自有效期内DIM；未命中为unmapped。';
COMMENT ON COLUMN ads.ads_operating_sales_traffic_company_shop_daily.company_name IS '公司完整名称，用作DataEase公司筛选；未命中为未匹配公司。';
COMMENT ON COLUMN ads.ads_operating_sales_traffic_company_shop_daily.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN ads.ads_operating_sales_traffic_company_shop_daily.shop_name IS '标准店铺名称，用作DataEase店铺筛选。';
COMMENT ON COLUMN ads.ads_operating_sales_traffic_company_shop_daily.traffic_content_type IS '流量结构一级维度，来自平台确认的体裁字段；空值、横杠、暂无来源或源未提供统一为未提供。';
COMMENT ON COLUMN ads.ads_operating_sales_traffic_company_shop_daily.traffic_channel IS '流量结构二级维度，来自平台确认的渠道字段；空值、横杠、暂无来源或源未提供统一为未提供。';
COMMENT ON COLUMN ads.ads_operating_sales_traffic_company_shop_daily.gmv_amount IS '对应流量体裁和流量渠道的非刷单商品行原价GMV，单位元。';
COMMENT ON COLUMN ads.ads_operating_sales_traffic_company_shop_daily.included_sub_order_count IS '对应流量结构纳入的非刷单订单商品行数。';
COMMENT ON COLUMN ads.ads_operating_sales_traffic_company_shop_daily.source_updated_at IS '参与本行汇总的DWS记录最晚来源更新时间。';
COMMENT ON COLUMN ads.ads_operating_sales_traffic_company_shop_daily.created_at IS 'ADS记录创建时间。';
COMMENT ON COLUMN ads.ads_operating_sales_traffic_company_shop_daily.updated_at IS 'ADS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_ads_operating_sales_traffic_company
    ON ads.ads_operating_sales_traffic_company_shop_daily (company_code, stat_date);

CREATE INDEX IF NOT EXISTS idx_ads_operating_sales_traffic_platform
    ON ads.ads_operating_sales_traffic_company_shop_daily (platform_code, stat_date);

CREATE INDEX IF NOT EXISTS idx_ads_operating_sales_traffic_dimension
    ON ads.ads_operating_sales_traffic_company_shop_daily (traffic_content_type, traffic_channel);
