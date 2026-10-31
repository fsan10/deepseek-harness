CREATE TABLE IF NOT EXISTS dws.dws_douyin_operating_flow_shop_daily_scene (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    source_document_type VARCHAR(32) NOT NULL,
    source_origin VARCHAR(16) NOT NULL,
    secondary_category_code VARCHAR(128) NOT NULL,
    secondary_category_name VARCHAR(768) NOT NULL,
    primary_category_code VARCHAR(64) NOT NULL,
    primary_category_name VARCHAR(128) NOT NULL,
    operating_treatment VARCHAR(16),
    mapping_status VARCHAR(16) NOT NULL,
    source_signed_amount NUMERIC(18,2) NOT NULL,
    income_amount NUMERIC(18,2) NOT NULL,
    expense_amount NUMERIC(18,2) NOT NULL,
    excluded_amount NUMERIC(18,2) NOT NULL,
    included_detail_count BIGINT NOT NULL,
    source_detail_count BIGINT NOT NULL,
    exclusion_reason TEXT NOT NULL,
    source_updated_at TIMESTAMPTZ,
    mapping_updated_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(stat_date,platform_code,shop_code,source_document_type,source_origin,secondary_category_code)
);
COMMENT ON TABLE dws.dws_douyin_operating_flow_shop_daily_scene IS '经营收支全部场景，分类缺失保留总额，排除项保留明细，来源公式及防重沿用同一资金链路。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.stat_date IS '统计日期，沿用平台既有业务日期。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.platform_code IS '标准平台编码。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.platform_name IS '平台展示名称。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.shop_code IS '通过ODS批次上下文确定的标准店铺。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.source_document_type IS '来源单据：settlement结算，fund资金。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.source_origin IS '来源公式阶段：income收入项目，expense费用项目，excluded账户或核对流水。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.secondary_category_code IS '来源业务项目稳定编码。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.secondary_category_name IS '原始业务场景或金额项目名称。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.primary_category_code IS '分类编码，未映射固定unmapped。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.primary_category_name IS '分类名称，缺失或停用时为未映射。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.operating_treatment IS '经营归属income收入、expense支出、excluded不计入；空值表示性质待确认。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.mapping_status IS '分类状态mapped已映射、unmapped未映射。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.source_signed_amount IS '原公式项目净额，收入方向为正；保留不计入项目原始金额，单位元。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.income_amount IS '归属收入金额，负数冲减收入，单位元。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.expense_amount IS '归属支出金额，负数冲减费用，单位元。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.excluded_amount IS '不计入经营收支的有符号金额，单位元。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.included_detail_count IS '来源公式纳入明细数。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.source_detail_count IS '来源明细数。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.exclusion_reason IS '排除或待确认原因，保留防重及仅核对说明。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.source_updated_at IS '最晚ODS入库时间。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.mapping_updated_at IS '归属或分类最后更新时间。';
COMMENT ON COLUMN dws.dws_douyin_operating_flow_shop_daily_scene.updated_at IS '本次加工刷新时间。';
