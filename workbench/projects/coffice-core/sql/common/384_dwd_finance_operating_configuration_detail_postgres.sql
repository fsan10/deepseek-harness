CREATE TABLE IF NOT EXISTS dwd.dwd_finance_operating_configuration_detail (
    configuration_event_key VARCHAR(180) PRIMARY KEY,
    event_type VARCHAR(32) NOT NULL,
    source_id BIGINT,
    business_date DATE NOT NULL,
    budget_month DATE NOT NULL,
    platform_code VARCHAR(32),
    platform_name VARCHAR(64),
    company_code VARCHAR(32),
    company_name VARCHAR(255),
    shop_code VARCHAR(128),
    shop_name VARCHAR(255),
    promotion_budget_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    gsv_target_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    recharge_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    promotion_adjustment_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    marketing_budget_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    marketing_expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    approval_status VARCHAR(16),
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_dwd_finance_config_event_type CHECK (event_type IN ('monthly_control','shop_plan','recharge','promotion_adjustment','marketing_expense'))
);
COMMENT ON TABLE dwd.dwd_finance_operating_configuration_detail IS '经营预算配置指标专属DWD；统一清洗月度总控、店铺计划、推广充值、预算调整和整体营销费用事件。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.configuration_event_key IS '来源类型与来源主键组成的稳定事件键。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.event_type IS '配置事件类型：monthly_control/shop_plan/recharge/promotion_adjustment/marketing_expense。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.source_id IS '配置来源表代理主键；月度总控无代理主键时为空。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.business_date IS '事件业务日期；月度配置使用月初日期，流水使用实际发生日期。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.budget_month IS '预算归属月份，固定为当月第一天。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.platform_code IS '标准平台编码；店铺类事件按业务日期从DIM匹配，整体事件为空。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.platform_name IS '标准平台名称；店铺类事件来自DIM，整体事件为空。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.company_code IS '标准公司编码；店铺类事件来自DIM，整体事件为空。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.company_name IS '公司名称；店铺类事件来自DIM，整体事件为空。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.shop_code IS '标准店铺编码；整体事件为空。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.shop_name IS '标准店铺名称，来自DIM；整体事件为空。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.promotion_budget_amount IS '月初推广预算或店铺分配预算，单位元。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.gsv_target_amount IS '月度总控或店铺明细GSV目标，单位元；event_type区分来源。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.recharge_amount IS '推广账户充值金额，单位元。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.promotion_adjustment_amount IS '推广预算追加或调减金额，单位元；仅已审批事件写入非零值。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.marketing_budget_amount IS '整体营销预算，单位元。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.marketing_expense_amount IS '整体营销费用实际发生金额，单位元。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.approval_status IS '预算调整审批状态；其他事件为空。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.source_updated_at IS '来源配置记录最后更新时间。';
COMMENT ON COLUMN dwd.dwd_finance_operating_configuration_detail.created_at IS 'DWD记录生成时间。';
