ALTER TABLE ads.ads_influencer_company_shop_daily
    ADD COLUMN IF NOT EXISTS source_influencer_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS company_influencer_id BIGINT,
    ADD COLUMN IF NOT EXISTS company_influencer_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS influencer_identity_key VARCHAR(256);

UPDATE ads.ads_influencer_company_shop_daily
SET source_influencer_id = COALESCE(source_influencer_id, influencer_id),
    company_influencer_name = COALESCE(company_influencer_name, influencer_name),
    influencer_identity_key = COALESCE(
        influencer_identity_key,
        'source:' || platform_code || ':' || influencer_id
    )
WHERE source_influencer_id IS NULL
   OR company_influencer_name IS NULL
   OR influencer_identity_key IS NULL;

ALTER TABLE ads.ads_influencer_company_shop_daily
    ALTER COLUMN source_influencer_id SET NOT NULL,
    ALTER COLUMN company_influencer_name SET NOT NULL,
    ALTER COLUMN influencer_identity_key SET NOT NULL,
    DROP CONSTRAINT IF EXISTS ads_influencer_company_shop_daily_pkey;

ALTER TABLE ads.ads_influencer_company_shop_daily
    ADD CONSTRAINT ads_influencer_company_shop_daily_pkey
    PRIMARY KEY (
        stat_date,
        platform_code,
        company_code,
        shop_code,
        influencer_identity_key
    );

CREATE INDEX IF NOT EXISTS idx_ads_influencer_daily_company_influencer
    ON ads.ads_influencer_company_shop_daily (
        company_influencer_id,
        stat_date
    );

ALTER TABLE ads.ads_influencer_company_shop_monthly_ranking
    ADD COLUMN IF NOT EXISTS source_influencer_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS company_influencer_id BIGINT,
    ADD COLUMN IF NOT EXISTS company_influencer_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS influencer_identity_key VARCHAR(256);

UPDATE ads.ads_influencer_company_shop_monthly_ranking
SET source_influencer_id = COALESCE(source_influencer_id, influencer_id),
    company_influencer_name = COALESCE(company_influencer_name, influencer_name),
    influencer_identity_key = COALESCE(
        influencer_identity_key,
        'source:' || platform_code || ':' || influencer_id
    )
WHERE source_influencer_id IS NULL
   OR company_influencer_name IS NULL
   OR influencer_identity_key IS NULL;

ALTER TABLE ads.ads_influencer_company_shop_monthly_ranking
    ALTER COLUMN source_influencer_id SET NOT NULL,
    ALTER COLUMN company_influencer_name SET NOT NULL,
    ALTER COLUMN influencer_identity_key SET NOT NULL,
    DROP CONSTRAINT IF EXISTS ads_influencer_company_shop_monthly_ranking_pkey;

ALTER TABLE ads.ads_influencer_company_shop_monthly_ranking
    ADD CONSTRAINT ads_influencer_company_shop_monthly_ranking_pkey
    PRIMARY KEY (
        stat_month,
        platform_code,
        company_code,
        shop_code,
        influencer_identity_key
    );

CREATE INDEX IF NOT EXISTS idx_ads_influencer_monthly_company_influencer
    ON ads.ads_influencer_company_shop_monthly_ranking (
        company_influencer_id,
        stat_month
    );

COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.source_influencer_id IS
    '汇总行包含的平台来源达人ID代表值；同一公司达人多个来源账号汇总时取稳定最小值，仅供追溯。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.company_influencer_id IS
    '公司统一达人ID；未映射平台账号为空。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.company_influencer_name IS
    '公司统一达人名称；未映射时使用平台昵称。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_daily.influencer_identity_key IS
    '事实稳定身份键；已映射为company前缀，未映射为source加平台和来源UID。';

COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.source_influencer_id IS
    '月汇总包含的平台来源达人ID代表值，仅供追溯。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.company_influencer_id IS
    '公司统一达人ID；未映射平台账号为空。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.company_influencer_name IS
    '公司统一达人名称；未映射时使用平台昵称。';
COMMENT ON COLUMN ads.ads_influencer_company_shop_monthly_ranking.influencer_identity_key IS
    '月事实稳定身份键；所有事实聚合和上月关联只使用本字段而不使用展示名称。';
