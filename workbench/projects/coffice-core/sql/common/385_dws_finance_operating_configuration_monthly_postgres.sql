CREATE TABLE IF NOT EXISTS dws.dws_finance_operating_shop_monthly (
    budget_month DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    promotion_budget_amount NUMERIC(18,2) NOT NULL,
    gsv_target_amount NUMERIC(18,2) NOT NULL,
    recharge_amount NUMERIC(18,2) NOT NULL,
    pending_recharge_amount NUMERIC(18,2) NOT NULL,
    over_recharge_amount NUMERIC(18,2) NOT NULL,
    recharge_count BIGINT NOT NULL,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (budget_month,platform_code,company_code,shop_code)
);
CREATE TABLE IF NOT EXISTS dws.dws_finance_operating_global_monthly (
    budget_month DATE PRIMARY KEY,
    gsv_target_amount NUMERIC(18,2) NOT NULL,
    initial_promotion_budget_amount NUMERIC(18,2) NOT NULL,
    approved_adjustment_amount NUMERIC(18,2) NOT NULL,
    effective_promotion_budget_amount NUMERIC(18,2) NOT NULL,
    allocated_promotion_budget_amount NUMERIC(18,2) NOT NULL,
    unallocated_promotion_budget_amount NUMERIC(18,2) NOT NULL,
    recharge_amount NUMERIC(18,2) NOT NULL,
    pending_recharge_amount NUMERIC(18,2) NOT NULL,
    marketing_budget_amount NUMERIC(18,2) NOT NULL,
    marketing_expense_amount NUMERIC(18,2) NOT NULL,
    marketing_remaining_amount NUMERIC(18,2) NOT NULL,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE dws.dws_finance_operating_global_monthly
    ADD COLUMN IF NOT EXISTS gsv_target_amount NUMERIC(18,2) NOT NULL DEFAULT 0;
COMMENT ON TABLE dws.dws_finance_operating_shop_monthly IS '经营预算配置店铺月DWS；一月、平台、公司、店铺一行。';
COMMENT ON COLUMN dws.dws_finance_operating_shop_monthly.budget_month IS '预算月份，月初日期。';
COMMENT ON COLUMN dws.dws_finance_operating_shop_monthly.platform_code IS '标准平台编码，来自DIM。';
COMMENT ON COLUMN dws.dws_finance_operating_shop_monthly.platform_name IS '标准平台名称，来自DIM。';
COMMENT ON COLUMN dws.dws_finance_operating_shop_monthly.company_code IS '标准公司编码，来自DIM。';
COMMENT ON COLUMN dws.dws_finance_operating_shop_monthly.company_name IS '公司名称，来自DIM。';
COMMENT ON COLUMN dws.dws_finance_operating_shop_monthly.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_finance_operating_shop_monthly.shop_name IS '标准店铺名称，来自DIM。';
COMMENT ON COLUMN dws.dws_finance_operating_shop_monthly.promotion_budget_amount IS '店铺当月推广预算，单位元。';
COMMENT ON COLUMN dws.dws_finance_operating_shop_monthly.gsv_target_amount IS '店铺当月GSV目标，单位元。';
COMMENT ON COLUMN dws.dws_finance_operating_shop_monthly.recharge_amount IS '店铺当月累计已充值额度，单位元。';
COMMENT ON COLUMN dws.dws_finance_operating_shop_monthly.pending_recharge_amount IS '待充值额度=店铺推广预算-累计已充值，单位元，可为负。';
COMMENT ON COLUMN dws.dws_finance_operating_shop_monthly.over_recharge_amount IS '超出店铺预算的充值金额=max(已充值-预算,0)，单位元。';
COMMENT ON COLUMN dws.dws_finance_operating_shop_monthly.recharge_count IS '当月有效充值流水笔数。';
COMMENT ON COLUMN dws.dws_finance_operating_shop_monthly.source_updated_at IS '参与聚合的配置记录最晚更新时间。';
COMMENT ON COLUMN dws.dws_finance_operating_shop_monthly.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_finance_operating_shop_monthly.updated_at IS 'DWS记录最后刷新时间。';
COMMENT ON TABLE dws.dws_finance_operating_global_monthly IS '经营预算配置整体月DWS；一月一行，不带平台、公司、部门和店铺维度。';
COMMENT ON COLUMN dws.dws_finance_operating_global_monthly.budget_month IS '预算月份，月初日期。';
COMMENT ON COLUMN dws.dws_finance_operating_global_monthly.gsv_target_amount IS '财务设定的当月整体GSV总目标，单位元；不从店铺目标明细汇总。';
COMMENT ON COLUMN dws.dws_finance_operating_global_monthly.initial_promotion_budget_amount IS '财务月初批准的推广预算总额，单位元。';
COMMENT ON COLUMN dws.dws_finance_operating_global_monthly.approved_adjustment_amount IS '已审批推广预算调整净额，单位元。';
COMMENT ON COLUMN dws.dws_finance_operating_global_monthly.effective_promotion_budget_amount IS '有效推广预算=月初预算+已审批调整，单位元。';
COMMENT ON COLUMN dws.dws_finance_operating_global_monthly.allocated_promotion_budget_amount IS '已分配到店铺的推广预算合计，单位元。';
COMMENT ON COLUMN dws.dws_finance_operating_global_monthly.unallocated_promotion_budget_amount IS '未分配推广预算=有效预算-店铺预算合计，单位元。';
COMMENT ON COLUMN dws.dws_finance_operating_global_monthly.recharge_amount IS '全部店铺当月累计已充值，单位元。';
COMMENT ON COLUMN dws.dws_finance_operating_global_monthly.pending_recharge_amount IS '整体待充值额度=有效推广预算-累计已充值，单位元。';
COMMENT ON COLUMN dws.dws_finance_operating_global_monthly.marketing_budget_amount IS '公司整体营销预算，单位元。';
COMMENT ON COLUMN dws.dws_finance_operating_global_monthly.marketing_expense_amount IS '公司整体营销费用实际发生额，单位元。';
COMMENT ON COLUMN dws.dws_finance_operating_global_monthly.marketing_remaining_amount IS '整体营销预算余额=营销预算-营销费用，单位元。';
COMMENT ON COLUMN dws.dws_finance_operating_global_monthly.source_updated_at IS '参与聚合的配置记录最晚更新时间。';
COMMENT ON COLUMN dws.dws_finance_operating_global_monthly.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_finance_operating_global_monthly.updated_at IS 'DWS记录最后刷新时间。';
