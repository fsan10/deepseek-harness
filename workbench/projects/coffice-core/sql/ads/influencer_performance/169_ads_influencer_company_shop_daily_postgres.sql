CREATE SCHEMA IF NOT EXISTS ads;

CREATE TABLE IF NOT EXISTS ads.ads_influencer_company_shop_daily (
    stat_date DATE NOT NULL,
    stat_month DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    influencer_id VARCHAR(128) NOT NULL,
    influencer_name VARCHAR(255) NOT NULL,
    influencer_key VARCHAR(193) NOT NULL,
    business_owner_id BIGINT NOT NULL,
    business_owner_name VARCHAR(128) NOT NULL,
    assignment_effective_month DATE,
    gmv_amount NUMERIC(18,2) NOT NULL,
    refund_amount NUMERIC(18,2) NOT NULL,
    refund_rate NUMERIC(18,6) NOT NULL,
    included_sub_order_count BIGINT NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (stat_date, platform_code, company_code, shop_code, influencer_id),
    CONSTRAINT ck_ads_influencer_daily_month
        CHECK (stat_month = DATE_TRUNC('month', stat_date)::date)
);

COMMENT ON TABLE ads.ads_influencer_company_shop_daily IS '达人运营自然日ADS，一行一个日期、平台、公司、店铺和达人，服务达人数、GMV、退款、退款率指标卡以及平台达人数图。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.stat_date IS '统计自然日，严格取各平台已确认的订单下单日期；抖音取订单提交日期。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.stat_month IS '统计日期所属自然月首日，用于匹配达人商务归属版本。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.platform_code IS '标准平台编码，用于渠道分组和跨平台达人去重。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.platform_name IS '平台中文名称，即看板渠道，当前覆盖抖音、视频号、快手、天猫、京东、小红书和拼多多。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.company_code IS '公司稳定编码，按统计日期通过dim.dim_platform_shop_company生成；未命中为unmapped。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.company_name IS '公司展示名称，未命中映射时为未匹配公司。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.shop_code IS '标准店铺编码，来自平台DWS。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.shop_name IS '标准店铺名称，供达播部门和其他部门手动筛选自己的店铺。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.influencer_id IS '规范达人ID；抖音封禁或注销账号统一为0；无达人平台补零行固定为__no_influencer__。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.influencer_name IS '达人展示名称；抖音ID为0时统一为其他；无达人平台占位行为无达人。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.influencer_key IS '跨平台达人去重键，由平台编码和达人ID组成；DataEase达人数必须只对gmv_amount大于0的本字段COUNT DISTINCT。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.business_owner_id IS '指标月生效的商务ID；0表示未分配商务。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.business_owner_name IS '指标月生效的商务姓名；无匹配版本时为未分配商务。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.assignment_effective_month IS '实际命中的达人商务归属版本生效月；未分配时为空。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.gmv_amount IS '各平台已确认口径的达人GMV；有达人平台排除大于2000元刷单且不按订单或售后状态筛选，无达人平台为0，单位元。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.refund_amount IS '各平台关闭类订单的同口径达人GMV金额；视频号为已取消，抖音为已关闭，快手和天猫为交易关闭，无达人平台为0，单位元。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.refund_rate IS '日、平台、公司、店铺、达人粒度退款率，等于退款除以GMV；跨日展示应使用SUM退款/SUM GMV重算。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.included_sub_order_count IS '纳入指标的达人订单或商品行数；无达人平台补零行固定为0。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.source_updated_at IS '本汇总所属来源记录的最晚ODS入库时间。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.refreshed_at IS 'ADS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_ads_influencer_daily_company_date
    ON ads.ads_influencer_company_shop_daily (company_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_influencer_daily_platform_date
    ON ads.ads_influencer_company_shop_daily (platform_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_influencer_daily_shop_date
    ON ads.ads_influencer_company_shop_daily (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_influencer_daily_business_date
    ON ads.ads_influencer_company_shop_daily (business_owner_id, stat_date);
