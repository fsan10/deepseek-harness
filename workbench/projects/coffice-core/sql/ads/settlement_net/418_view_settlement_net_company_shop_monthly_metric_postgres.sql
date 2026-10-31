CREATE SCHEMA IF NOT EXISTS ads;

CREATE OR REPLACE VIEW ads.v_settlement_net_company_shop_monthly_metric AS
SELECT
    m.stat_month,
    m.platform_code,
    m.platform_name,
    m.company_code,
    m.company_name,
    m.shop_code,
    m.shop_name,
    v.metric_order,
    v.metric_code,
    v.metric_name,
    v.amount
FROM ads.ads_settlement_net_company_shop_monthly m
CROSS JOIN LATERAL (
    VALUES
        (1::SMALLINT, 'income'::VARCHAR(32), '收入'::VARCHAR(64), m.income_amount),
        (2::SMALLINT, 'expense'::VARCHAR(32), '支出'::VARCHAR(64), COALESCE(m.display_expense_amount, m.expense_amount)),
        (3::SMALLINT, 'settlement_net'::VARCHAR(32), '结算净额'::VARCHAR(64), m.settlement_net_amount)
) AS v (
    metric_order,
    metric_code,
    metric_name,
    amount
);

COMMENT ON VIEW ads.v_settlement_net_company_shop_monthly_metric IS '结算净额公司店铺月度DataEase透视视图；将收入、支出和结算净额三个宽表金额展开为指标行。';
COMMENT ON COLUMN ads.v_settlement_net_company_shop_monthly_metric.stat_month IS '统计月份首日，建议作为DataEase透视表列维度。';
COMMENT ON COLUMN ads.v_settlement_net_company_shop_monthly_metric.platform_code IS '标准平台编码。';
COMMENT ON COLUMN ads.v_settlement_net_company_shop_monthly_metric.platform_name IS '平台展示名称，建议作为DataEase透视表行维度一级。';
COMMENT ON COLUMN ads.v_settlement_net_company_shop_monthly_metric.company_code IS '公司稳定编码。';
COMMENT ON COLUMN ads.v_settlement_net_company_shop_monthly_metric.company_name IS '公司展示名称。';
COMMENT ON COLUMN ads.v_settlement_net_company_shop_monthly_metric.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN ads.v_settlement_net_company_shop_monthly_metric.shop_name IS '标准店铺名称，建议作为DataEase透视表行维度二级。';
COMMENT ON COLUMN ads.v_settlement_net_company_shop_monthly_metric.metric_order IS '指标显示顺序：1收入、2支出、3结算净额。';
COMMENT ON COLUMN ads.v_settlement_net_company_shop_monthly_metric.metric_code IS '指标稳定编码：income、expense或settlement_net。';
COMMENT ON COLUMN ads.v_settlement_net_company_shop_monthly_metric.metric_name IS '指标展示名称：收入、支出或结算净额，建议作为DataEase透视表行维度三级。';
COMMENT ON COLUMN ads.v_settlement_net_company_shop_monthly_metric.amount IS '指标展示金额，单位元；支出优先使用DWS确认并经日月ADS汇总的display_expense_amount，未指定时沿用expense_amount；DataEase按月份求和，净额使用独立settlement_net指标。';
