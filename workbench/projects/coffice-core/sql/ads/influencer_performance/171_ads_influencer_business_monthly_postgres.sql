CREATE SCHEMA IF NOT EXISTS ads;

CREATE TABLE IF NOT EXISTS ads.ads_influencer_business_monthly (
    stat_month DATE NOT NULL,
    business_owner_id BIGINT NOT NULL,
    business_owner_name VARCHAR(128) NOT NULL,
    gmv_target NUMERIC(18,2) NOT NULL,
    actual_gmv_amount NUMERIC(18,2) NOT NULL,
    completion_rate NUMERIC(18,6) NOT NULL,
    assigned_influencer_count BIGINT NOT NULL,
    active_influencer_count BIGINT NOT NULL,
    influencer_100k_plus_count BIGINT NOT NULL,
    refund_amount NUMERIC(18,2) NOT NULL,
    refund_rate NUMERIC(18,6) NOT NULL,
    source_updated_at TIMESTAMPTZ,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (stat_month, business_owner_id)
);

COMMENT ON TABLE ads.ads_influencer_business_monthly IS '达人商务月度业绩ADS，一行一个自然月和商务，服务跨平台GMV目标、实际达成、完成率、归属达人数和月10万+达人数。';
COMMENT ON COLUMN ads.ads_influencer_business_monthly.stat_month IS '商务业绩所属自然月首日。';
COMMENT ON COLUMN ads.ads_influencer_business_monthly.business_owner_id IS '商务ID；0为未分配商务审计行。';
COMMENT ON COLUMN ads.ads_influencer_business_monthly.business_owner_name IS '商务姓名；ID为0时固定为未分配商务。';
COMMENT ON COLUMN ads.ads_influencer_business_monthly.gmv_target IS '配置页维护的商务当月跨平台达人GMV目标，单位元；未配置为0。';
COMMENT ON COLUMN ads.ads_influencer_business_monthly.actual_gmv_amount IS '按当月生效归属汇总的该商务名下达人跨平台GMV，单位元。';
COMMENT ON COLUMN ads.ads_influencer_business_monthly.completion_rate IS '完成率，等于实际达人GMV除以当月GMV目标；目标为0时记0。';
COMMENT ON COLUMN ads.ads_influencer_business_monthly.assigned_influencer_count IS '截至当月最新归属版本中该商务跨平台管理的达人总量，不要求当月产生GMV。';
COMMENT ON COLUMN ads.ads_influencer_business_monthly.active_influencer_count IS '当月实际产生达人GMV的该商务名下跨平台活跃达人数。';
COMMENT ON COLUMN ads.ads_influencer_business_monthly.influencer_100k_plus_count IS '当月跨平台GMV大于等于100000元的该商务名下达人数。';
COMMENT ON COLUMN ads.ads_influencer_business_monthly.refund_amount IS '该商务名下达人当月跨平台退款金额，单位元。';
COMMENT ON COLUMN ads.ads_influencer_business_monthly.refund_rate IS '该商务名下达人当月退款率，等于退款除以实际GMV；GMV为0时记0。';
COMMENT ON COLUMN ads.ads_influencer_business_monthly.source_updated_at IS '该商务当月实际业绩来源记录的最晚ODS入库时间；无业绩时为空。';
COMMENT ON COLUMN ads.ads_influencer_business_monthly.refreshed_at IS 'ADS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_ads_influencer_business_monthly_name
    ON ads.ads_influencer_business_monthly (business_owner_name, stat_month);
