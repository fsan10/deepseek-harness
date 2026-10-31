CREATE SCHEMA IF NOT EXISTS ads;

CREATE TABLE IF NOT EXISTS ads.ads_influencer_commission_company_platform_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    influencer_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, company_code)
);

COMMENT ON TABLE ads.ads_influencer_commission_company_platform_daily IS '八个平台达人佣金公司平台日ADS；抖音、快手、视频号和银行按确认口径计算，天猫、京东、小红书和拼多多按订单自然日补零，服务指标卡、趋势图和公共筛选器。';
COMMENT ON COLUMN ads.ads_influencer_commission_company_platform_daily.stat_date IS '达人佣金统计日期，用作DataEase日期筛选和趋势横轴。';
COMMENT ON COLUMN ads.ads_influencer_commission_company_platform_daily.platform_code IS '标准平台编码，包括douyin、ks、wechat_channels、bank、tmall、jd、xhs和pdd。';
COMMENT ON COLUMN ads.ads_influencer_commission_company_platform_daily.platform_name IS '平台展示名称，用作DataEase平台筛选和趋势系列。';
COMMENT ON COLUMN ads.ads_influencer_commission_company_platform_daily.company_code IS '按统计日期或银行账号名称从DIM解析的公司编码；未匹配时为unmapped。';
COMMENT ON COLUMN ads.ads_influencer_commission_company_platform_daily.company_name IS '标准公司名称；未匹配时为未匹配公司。';
COMMENT ON COLUMN ads.ads_influencer_commission_company_platform_daily.influencer_commission_amount IS '达人佣金指标净费用，费用为正、退款或冲回为负，单位元。';
COMMENT ON COLUMN ads.ads_influencer_commission_company_platform_daily.included_detail_count IS '纳入本行达人佣金计算的结算、动账或银行拆分明细数；四个平台补零行固定为0。';
COMMENT ON COLUMN ads.ads_influencer_commission_company_platform_daily.source_updated_at IS '参与汇总的DWS记录最晚来源更新时间。';
COMMENT ON COLUMN ads.ads_influencer_commission_company_platform_daily.created_at IS 'ADS记录创建时间。';
COMMENT ON COLUMN ads.ads_influencer_commission_company_platform_daily.updated_at IS 'ADS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_ads_influencer_commission_company_date
    ON ads.ads_influencer_commission_company_platform_daily (company_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_influencer_commission_platform_date
    ON ads.ads_influencer_commission_company_platform_daily (platform_code, stat_date);
