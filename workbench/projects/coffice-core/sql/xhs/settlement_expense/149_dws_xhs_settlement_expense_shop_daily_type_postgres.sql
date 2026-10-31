CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_xhs_settlement_expense_shop_daily_type (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    expense_type_code VARCHAR(64) NOT NULL,
    expense_type_name VARCHAR(128) NOT NULL,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_event_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code, expense_type_code)
);

COMMENT ON TABLE dws.dws_xhs_settlement_expense_shop_daily_type IS '小红书结算支出店铺日类型汇总表；仅汇总费用类其他服务款，申诉调账收入在收入DWS单独汇总。';
COMMENT ON COLUMN dws.dws_xhs_settlement_expense_shop_daily_type.stat_date IS '支出统计日期，取结算时间日期。';
COMMENT ON COLUMN dws.dws_xhs_settlement_expense_shop_daily_type.platform_code IS '标准平台编码，固定为xhs。';
COMMENT ON COLUMN dws.dws_xhs_settlement_expense_shop_daily_type.platform_name IS '平台展示名称，固定为小红书。';
COMMENT ON COLUMN dws.dws_xhs_settlement_expense_shop_daily_type.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_xhs_settlement_expense_shop_daily_type.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_xhs_settlement_expense_shop_daily_type.expense_type_code IS '由源业务款项映射的支出类型英文编码。';
COMMENT ON COLUMN dws.dws_xhs_settlement_expense_shop_daily_type.expense_type_name IS '支出类型中文名称，直接使用源业务款项。';
COMMENT ON COLUMN dws.dws_xhs_settlement_expense_shop_daily_type.expense_amount IS '店铺日业务款项费用净额，源动账金额取反后汇总；扣费为正，退款、补偿或调账返还为负，单位元。';
COMMENT ON COLUMN dws.dws_xhs_settlement_expense_shop_daily_type.included_event_count IS '纳入该类型的其他服务款事件数。';
COMMENT ON COLUMN dws.dws_xhs_settlement_expense_shop_daily_type.source_updated_at IS '参与汇总的DWD记录最晚来源时间。';
COMMENT ON COLUMN dws.dws_xhs_settlement_expense_shop_daily_type.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_xhs_settlement_expense_shop_daily_type.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_xhs_settlement_expense_date
    ON dws.dws_xhs_settlement_expense_shop_daily_type (stat_date);
