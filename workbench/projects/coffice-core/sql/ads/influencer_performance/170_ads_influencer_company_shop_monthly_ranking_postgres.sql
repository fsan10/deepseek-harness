CREATE SCHEMA IF NOT EXISTS ads;

CREATE TABLE IF NOT EXISTS ads.ads_influencer_company_shop_monthly_ranking (
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
    current_month_gmv NUMERIC(18,2) NOT NULL,
    previous_month_gmv NUMERIC(18,2) NOT NULL,
    mom_growth_rate NUMERIC(18,6),
    platform_month_gmv NUMERIC(18,2) NOT NULL,
    previous_platform_month_gmv NUMERIC(18,2) NOT NULL,
    platform_mom_growth_rate NUMERIC(18,6),
    platform_month_rank BIGINT NOT NULL,
    is_platform_month_100k_plus BOOLEAN NOT NULL,
    included_sub_order_count BIGINT NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (stat_month, platform_code, company_code, shop_code, influencer_id)
);

COMMENT ON TABLE ads.ads_influencer_company_shop_monthly_ranking IS '达人月度排名ADS，一行一个自然月、平台、公司、店铺和达人，服务月GMV Top5、环比及平台月10万+达人数。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.stat_month IS '订单提交日期所属自然月首日；用户在日期筛选器选完整自然月时使用。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.platform_code IS '标准平台编码。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.platform_name IS '平台中文名称，即Top5图表中的渠道。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.company_code IS '公司稳定编码，按订单日期通过店铺公司DIM生成。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.company_name IS '公司展示名称。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.shop_code IS '标准店铺编码，支持部门手动筛选店铺。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.influencer_id IS '规范达人ID；封禁或注销账号统一为0。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.influencer_name IS '达人展示名称；ID为0时统一为其他。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.influencer_key IS '跨平台达人去重键，由平台编码和达人ID组成。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.business_owner_id IS '当月生效的商务ID；0表示未分配。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.business_owner_name IS '当月生效的商务姓名；无匹配时为未分配商务。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.current_month_gmv IS '当前店铺内该达人当月GMV，单位元；店铺筛选后Top5对此字段SUM。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.previous_month_gmv IS '同平台、公司、店铺和达人上一自然月GMV，无记录时为0，单位元。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.mom_growth_rate IS '店铺粒度环比，等于当月GMV减上月GMV后除以上月GMV；上月为0时为空。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.platform_month_gmv IS '该达人在同平台全部店铺的当月GMV，单位元；平台Top5使用MAX避免多店重复。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.previous_platform_month_gmv IS '该达人在同平台全部店铺的上一自然月GMV，无记录时为0，单位元。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.platform_mom_growth_rate IS '平台全店粒度环比；上月平台GMV为0时为空。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.platform_month_rank IS '该达人按平台全店当月GMV降序的月排名。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.is_platform_month_100k_plus IS '该达人平台全店当月GMV是否大于等于100000元。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.included_sub_order_count IS '当前店铺内该达人当月纳入指标的子订单行数。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.source_updated_at IS '本汇总所属来源记录的最晚ODS入库时间。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.refreshed_at IS 'ADS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_ads_influencer_monthly_platform_rank
    ON ads.ads_influencer_company_shop_monthly_ranking (stat_month, platform_code, platform_month_rank);
CREATE INDEX IF NOT EXISTS idx_ads_influencer_monthly_shop
    ON ads.ads_influencer_company_shop_monthly_ranking (stat_month, shop_code);
CREATE INDEX IF NOT EXISTS idx_ads_influencer_monthly_business
    ON ads.ads_influencer_company_shop_monthly_ranking (stat_month, business_owner_id);

