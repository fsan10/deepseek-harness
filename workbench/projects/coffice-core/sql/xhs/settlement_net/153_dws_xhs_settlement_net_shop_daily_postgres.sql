CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_xhs_settlement_net_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    settlement_net_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_settlement_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    validation_difference_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_event_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code)
);

COMMENT ON TABLE dws.dws_xhs_settlement_net_shop_daily IS '小红书结算净额店铺日汇总表；订单结算、收入型申诉调账和费用类其他服务款全部纳入，净额与源文件总览净收益核验。';
COMMENT ON COLUMN dws.dws_xhs_settlement_net_shop_daily.stat_date IS '结算净额统计日期，取结算时间日期。';
COMMENT ON COLUMN dws.dws_xhs_settlement_net_shop_daily.platform_code IS '标准平台编码，固定为xhs。';
COMMENT ON COLUMN dws.dws_xhs_settlement_net_shop_daily.platform_name IS '平台展示名称，固定为小红书。';
COMMENT ON COLUMN dws.dws_xhs_settlement_net_shop_daily.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_xhs_settlement_net_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_xhs_settlement_net_shop_daily.income_amount IS '店铺日订单结算及申诉调账收入，含退款或收入冲回负数，单位元。';
COMMENT ON COLUMN dws.dws_xhs_settlement_net_shop_daily.expense_amount IS '店铺日费用类其他服务款净额，扣费为正、费用退款或补回为负；申诉调账收入不计入，单位元。';
COMMENT ON COLUMN dws.dws_xhs_settlement_net_shop_daily.settlement_net_amount IS '店铺日计算结算净额，等于收入减支出，单位元。';
COMMENT ON COLUMN dws.dws_xhs_settlement_net_shop_daily.source_settlement_amount IS '店铺日两张源表原始动账金额带符号合计，单位元。';
COMMENT ON COLUMN dws.dws_xhs_settlement_net_shop_daily.validation_difference_amount IS '计算净额减源带符号动账金额的差额，单位元。';
COMMENT ON COLUMN dws.dws_xhs_settlement_net_shop_daily.included_event_count IS '纳入计算的订单结算、申诉调账收入和费用类其他服务款事件数。';
COMMENT ON COLUMN dws.dws_xhs_settlement_net_shop_daily.source_updated_at IS '参与汇总的DWD记录最晚来源时间。';
COMMENT ON COLUMN dws.dws_xhs_settlement_net_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_xhs_settlement_net_shop_daily.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_xhs_settlement_net_date
    ON dws.dws_xhs_settlement_net_shop_daily (stat_date);
