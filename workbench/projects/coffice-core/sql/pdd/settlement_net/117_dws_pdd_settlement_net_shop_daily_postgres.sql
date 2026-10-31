CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_pdd_settlement_net_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    display_expense_amount NUMERIC(18,2),
    settlement_net_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_settlement_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    validation_difference_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_event_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code)
);

ALTER TABLE dws.dws_pdd_settlement_net_shop_daily
    ADD COLUMN IF NOT EXISTS display_expense_amount NUMERIC(18,2);

COMMENT ON TABLE dws.dws_pdd_settlement_net_shop_daily IS '拼多多结算净额店铺日汇总表，提现、转账、退款等全部账务类型均纳入。';
COMMENT ON COLUMN dws.dws_pdd_settlement_net_shop_daily.stat_date IS '结算净额统计日期，取发生时间日期。';
COMMENT ON COLUMN dws.dws_pdd_settlement_net_shop_daily.platform_code IS '标准平台编码，固定为pdd。';
COMMENT ON COLUMN dws.dws_pdd_settlement_net_shop_daily.platform_name IS '平台展示名称，固定为拼多多。';
COMMENT ON COLUMN dws.dws_pdd_settlement_net_shop_daily.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_pdd_settlement_net_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_pdd_settlement_net_shop_daily.income_amount IS '店铺日结算收入净额；原收入加原退款类型及0020005优惠券退款的带符号金额，允许为负，单位元。';
COMMENT ON COLUMN dws.dws_pdd_settlement_net_shop_daily.expense_amount IS '店铺日正向结算支出；原支出剔除已移入收入的退款，保留提现和账户转账，单位元。';
COMMENT ON COLUMN dws.dws_pdd_settlement_net_shop_daily.display_expense_amount IS '结算透视表展示支出，等于负expense_amount，由拼多多DWS生成符号，单位元；不参与收入减支出的内部净额公式。';
COMMENT ON COLUMN dws.dws_pdd_settlement_net_shop_daily.settlement_net_amount IS '店铺日计算结算净额，等于收入减支出，单位元。';
COMMENT ON COLUMN dws.dws_pdd_settlement_net_shop_daily.source_settlement_amount IS '店铺日源带符号流水金额，仅用于公式核验，单位元。';
COMMENT ON COLUMN dws.dws_pdd_settlement_net_shop_daily.validation_difference_amount IS '店铺日计算净额减源带符号流水金额的差额，单位元。';
COMMENT ON COLUMN dws.dws_pdd_settlement_net_shop_daily.included_event_count IS '纳入计算的全部账务事件数，不执行任何额外排除。';
COMMENT ON COLUMN dws.dws_pdd_settlement_net_shop_daily.source_updated_at IS '参与汇总的DWD记录最晚来源时间。';
COMMENT ON COLUMN dws.dws_pdd_settlement_net_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_pdd_settlement_net_shop_daily.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_pdd_settlement_net_date
    ON dws.dws_pdd_settlement_net_shop_daily (stat_date);

