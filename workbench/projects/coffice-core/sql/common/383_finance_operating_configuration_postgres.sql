CREATE SCHEMA IF NOT EXISTS config;

CREATE TABLE IF NOT EXISTS config.finance_budget_monthly (
    budget_month DATE PRIMARY KEY,
    gsv_target_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    promotion_budget_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    marketing_budget_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    remark VARCHAR(500),
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_finance_budget_month_start CHECK (budget_month = DATE_TRUNC('month', budget_month)::date),
    CONSTRAINT ck_finance_budget_amount_nonnegative CHECK (gsv_target_amount >= 0 AND promotion_budget_amount >= 0 AND marketing_budget_amount >= 0)
);

ALTER TABLE config.finance_budget_monthly
    ADD COLUMN IF NOT EXISTS gsv_target_amount NUMERIC(18,2) NOT NULL DEFAULT 0;
ALTER TABLE config.finance_budget_monthly DROP CONSTRAINT IF EXISTS ck_finance_budget_amount_nonnegative;
ALTER TABLE config.finance_budget_monthly
    ADD CONSTRAINT ck_finance_budget_amount_nonnegative
    CHECK (gsv_target_amount >= 0 AND promotion_budget_amount >= 0 AND marketing_budget_amount >= 0);

CREATE TABLE IF NOT EXISTS config.finance_shop_plan_monthly (
    shop_plan_id BIGSERIAL PRIMARY KEY,
    budget_month DATE NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    promotion_budget_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    gsv_target_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    remark VARCHAR(500),
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    deleted_by VARCHAR(100),
    CONSTRAINT ck_finance_shop_plan_month_start CHECK (budget_month = DATE_TRUNC('month', budget_month)::date),
    CONSTRAINT ck_finance_shop_plan_amount_nonnegative CHECK (promotion_budget_amount >= 0 AND gsv_target_amount >= 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_finance_shop_plan_active
    ON config.finance_shop_plan_monthly (budget_month, shop_code) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS config.finance_promotion_recharge_detail (
    recharge_id BIGSERIAL PRIMARY KEY,
    recharge_date DATE NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    recharge_amount NUMERIC(18,2) NOT NULL,
    document_no VARCHAR(100),
    remark VARCHAR(500),
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    deleted_by VARCHAR(100),
    CONSTRAINT ck_finance_recharge_amount_positive CHECK (recharge_amount > 0)
);

CREATE TABLE IF NOT EXISTS config.finance_promotion_budget_adjustment (
    adjustment_id BIGSERIAL PRIMARY KEY,
    budget_month DATE NOT NULL,
    adjustment_date DATE NOT NULL,
    adjustment_amount NUMERIC(18,2) NOT NULL,
    approval_no VARCHAR(100),
    reason VARCHAR(500) NOT NULL,
    approval_status VARCHAR(16) NOT NULL DEFAULT 'approved',
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    deleted_by VARCHAR(100),
    CONSTRAINT ck_finance_adjustment_month_start CHECK (budget_month = DATE_TRUNC('month', budget_month)::date),
    CONSTRAINT ck_finance_adjustment_amount_nonzero CHECK (adjustment_amount <> 0),
    CONSTRAINT ck_finance_adjustment_status CHECK (approval_status IN ('pending','approved','rejected'))
);

CREATE TABLE IF NOT EXISTS config.finance_marketing_expense_detail (
    marketing_expense_id BIGSERIAL PRIMARY KEY,
    expense_date DATE NOT NULL,
    expense_amount NUMERIC(18,2) NOT NULL,
    expense_type VARCHAR(100) NOT NULL,
    counterparty VARCHAR(255),
    document_no VARCHAR(100),
    remark VARCHAR(500),
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    deleted_by VARCHAR(100),
    CONSTRAINT ck_finance_marketing_expense_positive CHECK (expense_amount > 0)
);

CREATE OR REPLACE FUNCTION config.set_finance_configuration_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'finance_budget_monthly','finance_shop_plan_monthly','finance_promotion_recharge_detail',
        'finance_promotion_budget_adjustment','finance_marketing_expense_detail'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%I_updated_at ON config.%I', table_name, table_name);
        EXECUTE format('CREATE TRIGGER trg_%I_updated_at BEFORE UPDATE ON config.%I FOR EACH ROW EXECUTE FUNCTION config.set_finance_configuration_updated_at()', table_name, table_name);
    END LOOP;
END $$;

COMMENT ON TABLE config.finance_budget_monthly IS '经营配置中心财务月度总控；每月一行，维护总GSV目标、推广预算总额与整体营销预算。';
COMMENT ON COLUMN config.finance_budget_monthly.budget_month IS '预算月份，固定为当月第一天。';
COMMENT ON COLUMN config.finance_budget_monthly.gsv_target_amount IS '财务设定的当月公司整体GSV总目标，单位元；不由店铺明细反向汇总，实际GSV可超目标。';
COMMENT ON COLUMN config.finance_budget_monthly.promotion_budget_amount IS '财务批准的月初推广预算总额，单位元；额外审批通过调整流水增减。';
COMMENT ON COLUMN config.finance_budget_monthly.marketing_budget_amount IS '公司整体营销预算，单位元；不按平台、公司、部门或店铺拆分。';
COMMENT ON COLUMN config.finance_budget_monthly.remark IS '财务对本月总预算的说明。';
COMMENT ON COLUMN config.finance_budget_monthly.created_by IS '创建记录的用户显示名。';
COMMENT ON COLUMN config.finance_budget_monthly.updated_by IS '最后修改记录的用户显示名。';
COMMENT ON COLUMN config.finance_budget_monthly.created_at IS '记录创建时间，带时区。';
COMMENT ON COLUMN config.finance_budget_monthly.updated_at IS '记录最后修改时间，带时区。';

COMMENT ON TABLE config.finance_shop_plan_monthly IS '部门或运营按店铺维护的月度推广预算与店铺GSV目标明细；不覆盖财务月度总控，店铺的平台和公司只能从DIM取得。';
COMMENT ON COLUMN config.finance_shop_plan_monthly.shop_plan_id IS '店铺月度计划代理主键。';
COMMENT ON COLUMN config.finance_shop_plan_monthly.budget_month IS '预算及目标所属月份，固定为当月第一天。';
COMMENT ON COLUMN config.finance_shop_plan_monthly.shop_code IS '标准店铺编码；平台、公司和店铺名称不在本表冗余维护。';
COMMENT ON COLUMN config.finance_shop_plan_monthly.promotion_budget_amount IS '分配给该店铺的当月推广预算，单位元。';
COMMENT ON COLUMN config.finance_shop_plan_monthly.gsv_target_amount IS '部门或运营设定的该店铺当月GSV目标明细，单位元；实际GSV由订单指标计算且不封顶。';
COMMENT ON COLUMN config.finance_shop_plan_monthly.remark IS '店铺月度计划说明。';
COMMENT ON COLUMN config.finance_shop_plan_monthly.created_by IS '创建记录的用户显示名。';
COMMENT ON COLUMN config.finance_shop_plan_monthly.updated_by IS '最后修改记录的用户显示名。';
COMMENT ON COLUMN config.finance_shop_plan_monthly.created_at IS '记录创建时间，带时区。';
COMMENT ON COLUMN config.finance_shop_plan_monthly.updated_at IS '记录最后修改时间，带时区。';
COMMENT ON COLUMN config.finance_shop_plan_monthly.deleted_at IS '软删除时间；为空表示有效。';
COMMENT ON COLUMN config.finance_shop_plan_monthly.deleted_by IS '执行软删除的用户显示名。';

COMMENT ON TABLE config.finance_promotion_recharge_detail IS '推广账户充值流水；每次向某店铺充值一行，累计充值用于计算待充值额度。';
COMMENT ON COLUMN config.finance_promotion_recharge_detail.recharge_id IS '推广充值流水代理主键。';
COMMENT ON COLUMN config.finance_promotion_recharge_detail.recharge_date IS '财务实际充值日期。';
COMMENT ON COLUMN config.finance_promotion_recharge_detail.shop_code IS '接受充值的标准店铺编码；维度从DIM取得。';
COMMENT ON COLUMN config.finance_promotion_recharge_detail.recharge_amount IS '本次推广充值金额，单位元，必须大于0。';
COMMENT ON COLUMN config.finance_promotion_recharge_detail.document_no IS '充值单据号、审批号或付款凭证号。';
COMMENT ON COLUMN config.finance_promotion_recharge_detail.remark IS '充值用途或补充说明。';
COMMENT ON COLUMN config.finance_promotion_recharge_detail.created_by IS '创建记录的用户显示名。';
COMMENT ON COLUMN config.finance_promotion_recharge_detail.updated_by IS '最后修改记录的用户显示名。';
COMMENT ON COLUMN config.finance_promotion_recharge_detail.created_at IS '记录创建时间，带时区。';
COMMENT ON COLUMN config.finance_promotion_recharge_detail.updated_at IS '记录最后修改时间，带时区。';
COMMENT ON COLUMN config.finance_promotion_recharge_detail.deleted_at IS '软删除时间；为空表示有效。';
COMMENT ON COLUMN config.finance_promotion_recharge_detail.deleted_by IS '执行软删除的用户显示名。';

COMMENT ON TABLE config.finance_promotion_budget_adjustment IS '推广预算追加或调减审批流水；只有approved状态参与有效预算。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.adjustment_id IS '推广预算调整代理主键。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.budget_month IS '调整归属预算月份，固定为当月第一天。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.adjustment_date IS '预算调整申请或审批日期。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.adjustment_amount IS '推广预算调整金额，单位元；追加为正、调减为负且不可为0。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.approval_no IS '预算审批单号。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.reason IS '预算调整原因。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.approval_status IS '审批状态：pending待审批、approved已通过、rejected已拒绝。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.created_by IS '创建记录的用户显示名。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.updated_by IS '最后修改记录的用户显示名。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.created_at IS '记录创建时间，带时区。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.updated_at IS '记录最后修改时间，带时区。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.deleted_at IS '软删除时间；为空表示有效。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.deleted_by IS '执行软删除的用户显示名。';

COMMENT ON TABLE config.finance_marketing_expense_detail IS '公司整体营销费用手工流水，例如明星合作或品牌广告；不按平台、公司、部门和店铺拆分。';
COMMENT ON COLUMN config.finance_marketing_expense_detail.marketing_expense_id IS '营销费用流水代理主键。';
COMMENT ON COLUMN config.finance_marketing_expense_detail.expense_date IS '营销费用发生日期。';
COMMENT ON COLUMN config.finance_marketing_expense_detail.expense_amount IS '本次营销费用金额，单位元，必须大于0。';
COMMENT ON COLUMN config.finance_marketing_expense_detail.expense_type IS '营销费用类型，例如明星合作或品牌广告。';
COMMENT ON COLUMN config.finance_marketing_expense_detail.counterparty IS '收款方或合作方。';
COMMENT ON COLUMN config.finance_marketing_expense_detail.document_no IS '合同、审批或付款单据号。';
COMMENT ON COLUMN config.finance_marketing_expense_detail.remark IS '营销事项说明。';
COMMENT ON COLUMN config.finance_marketing_expense_detail.created_by IS '创建记录的用户显示名。';
COMMENT ON COLUMN config.finance_marketing_expense_detail.updated_by IS '最后修改记录的用户显示名。';
COMMENT ON COLUMN config.finance_marketing_expense_detail.created_at IS '记录创建时间，带时区。';
COMMENT ON COLUMN config.finance_marketing_expense_detail.updated_at IS '记录最后修改时间，带时区。';
COMMENT ON COLUMN config.finance_marketing_expense_detail.deleted_at IS '软删除时间；为空表示有效。';
COMMENT ON COLUMN config.finance_marketing_expense_detail.deleted_by IS '执行软删除的用户显示名。';

CREATE INDEX IF NOT EXISTS idx_finance_recharge_shop_date ON config.finance_promotion_recharge_detail (shop_code, recharge_date) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_finance_adjustment_month_status ON config.finance_promotion_budget_adjustment (budget_month, approval_status) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_finance_marketing_expense_date ON config.finance_marketing_expense_detail (expense_date) WHERE deleted_at IS NULL;

INSERT INTO iam.permission_resource(resource_code,resource_name,resource_type,module_code,parent_resource_id,route_path,display_order,is_active,updated_at)
VALUES('module.operating_config','经营配置','module','operating_config',NULL,'/ingest/',60,TRUE,NOW())
ON CONFLICT(resource_code) DO UPDATE SET resource_name=EXCLUDED.resource_name,resource_type=EXCLUDED.resource_type,module_code=EXCLUDED.module_code,route_path=EXCLUDED.route_path,display_order=EXCLUDED.display_order,is_active=TRUE,updated_at=NOW();

INSERT INTO iam.permission_resource(resource_code,resource_name,resource_type,module_code,parent_resource_id,route_path,display_order,is_active,updated_at)
SELECT 'finance_budget.view','经营配置页面','page','operating_config',p.resource_id,'/ingest/#financeOverview',10,TRUE,NOW()
FROM iam.permission_resource p WHERE p.resource_code='module.operating_config'
ON CONFLICT(resource_code) DO UPDATE SET resource_name=EXCLUDED.resource_name,resource_type=EXCLUDED.resource_type,module_code=EXCLUDED.module_code,parent_resource_id=EXCLUDED.parent_resource_id,route_path=EXCLUDED.route_path,display_order=EXCLUDED.display_order,is_active=TRUE,updated_at=NOW();

INSERT INTO iam.permission_resource(resource_code,resource_name,resource_type,module_code,parent_resource_id,route_path,display_order,is_active,updated_at)
SELECT 'finance_budget.manage','维护预算目标、充值及营销费用','action','operating_config',p.resource_id,NULL,11,TRUE,NOW()
FROM iam.permission_resource p WHERE p.resource_code='finance_budget.view'
ON CONFLICT(resource_code) DO UPDATE SET resource_name=EXCLUDED.resource_name,resource_type=EXCLUDED.resource_type,module_code=EXCLUDED.module_code,parent_resource_id=EXCLUDED.parent_resource_id,route_path=EXCLUDED.route_path,display_order=EXCLUDED.display_order,is_active=TRUE,updated_at=NOW();

UPDATE iam.permission_resource
SET resource_name='经营配置维护（旧权限，已停用）',is_active=FALSE,updated_at=NOW()
WHERE resource_code='finance_budget.manage';

INSERT INTO iam.permission_resource(resource_code,resource_name,resource_type,module_code,parent_resource_id,route_path,display_order,is_active,updated_at)
SELECT 'finance_budget.total.manage','维护财务月度总控、充值及营销费用','action','operating_config',p.resource_id,NULL,11,TRUE,NOW()
FROM iam.permission_resource p WHERE p.resource_code='finance_budget.view'
ON CONFLICT(resource_code) DO UPDATE SET resource_name=EXCLUDED.resource_name,resource_type=EXCLUDED.resource_type,module_code=EXCLUDED.module_code,parent_resource_id=EXCLUDED.parent_resource_id,route_path=EXCLUDED.route_path,display_order=EXCLUDED.display_order,is_active=TRUE,updated_at=NOW();

INSERT INTO iam.permission_resource(resource_code,resource_name,resource_type,module_code,parent_resource_id,route_path,display_order,is_active,updated_at)
SELECT 'finance_budget.detail.manage','维护店铺GSV目标与推广预算明细','action','operating_config',p.resource_id,NULL,12,TRUE,NOW()
FROM iam.permission_resource p WHERE p.resource_code='finance_budget.view'
ON CONFLICT(resource_code) DO UPDATE SET resource_name=EXCLUDED.resource_name,resource_type=EXCLUDED.resource_type,module_code=EXCLUDED.module_code,parent_resource_id=EXCLUDED.parent_resource_id,route_path=EXCLUDED.route_path,display_order=EXCLUDED.display_order,is_active=TRUE,updated_at=NOW();

INSERT INTO iam.role_permission(role_id,resource_id,granted_at)
SELECT r.role_id,p.resource_id,NOW()
FROM iam.role r CROSS JOIN iam.permission_resource p
WHERE r.role_code='super_admin' AND p.resource_code IN ('module.operating_config','finance_budget.view','finance_budget.total.manage','finance_budget.detail.manage')
ON CONFLICT(role_id,resource_id) DO NOTHING;
