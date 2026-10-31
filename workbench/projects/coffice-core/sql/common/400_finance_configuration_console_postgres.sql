-- 经营配置全量配置台：DIM 店铺清单、预算变更留痕、营销费用类型及最终权限树。
CREATE SCHEMA IF NOT EXISTS config;

ALTER TABLE config.finance_budget_monthly
    ADD COLUMN IF NOT EXISTS promotion_budget_initialized_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS marketing_budget_initialized_at TIMESTAMPTZ;

UPDATE config.finance_budget_monthly b
SET promotion_budget_initialized_at = COALESCE(
        b.promotion_budget_initialized_at,
        b.created_at
    ),
    marketing_budget_initialized_at = COALESCE(
        b.marketing_budget_initialized_at,
        b.created_at
    );

ALTER TABLE config.finance_promotion_budget_adjustment
    ADD COLUMN IF NOT EXISTS before_amount NUMERIC(18,2),
    ADD COLUMN IF NOT EXISTS after_amount NUMERIC(18,2),
    ADD COLUMN IF NOT EXISTS change_remark VARCHAR(500),
    ADD COLUMN IF NOT EXISTS changed_by VARCHAR(100),
    ADD COLUMN IF NOT EXISTS change_type VARCHAR(32) NOT NULL DEFAULT 'legacy_adjustment';

-- 将旧的已生效调整补齐为可读的前后金额；待审批/已拒绝历史不参与新总预算口径。
WITH legacy_values AS (
    SELECT a.adjustment_id,
           (
               COALESCE(b.promotion_budget_amount, 0)
               + COALESCE(SUM(previous.adjustment_amount), 0)
           )::numeric(18,2) AS before_amount,
           a.adjustment_amount,
           COALESCE(NULLIF(BTRIM(a.reason), ''), '历史预算调整') AS change_remark,
           COALESCE(NULLIF(BTRIM(a.updated_by), ''), NULLIF(BTRIM(a.created_by), ''), 'system_migration') AS changed_by
      FROM config.finance_promotion_budget_adjustment a
      LEFT JOIN config.finance_budget_monthly b ON b.budget_month=a.budget_month
      LEFT JOIN config.finance_promotion_budget_adjustment previous
        ON previous.budget_month=a.budget_month
       AND previous.approval_status='approved'
       AND previous.deleted_at IS NULL
       AND (
            previous.adjustment_date<a.adjustment_date
            OR (previous.adjustment_date=a.adjustment_date AND previous.adjustment_id<a.adjustment_id)
       )
     WHERE a.before_amount IS NULL
       AND a.approval_status='approved'
       AND a.deleted_at IS NULL
     GROUP BY a.adjustment_id,b.promotion_budget_amount,a.adjustment_amount,a.reason,a.updated_by,a.created_by
)
UPDATE config.finance_promotion_budget_adjustment a
   SET before_amount=v.before_amount,
       after_amount=(v.before_amount+v.adjustment_amount)::numeric(18,2),
       change_remark=v.change_remark,
       changed_by=v.changed_by
  FROM legacy_values v
 WHERE a.adjustment_id=v.adjustment_id;

CREATE TABLE IF NOT EXISTS config.finance_marketing_budget_change_history (
    history_id BIGSERIAL PRIMARY KEY,
    budget_month DATE NOT NULL,
    before_amount NUMERIC(18,2) NOT NULL,
    after_amount NUMERIC(18,2) NOT NULL,
    change_amount NUMERIC(18,2) NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    changed_by VARCHAR(100) NOT NULL,
    remark VARCHAR(500) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_finance_marketing_history_month_start
        CHECK (budget_month = DATE_TRUNC('month', budget_month)::date),
    CONSTRAINT ck_finance_marketing_history_amounts
        CHECK (after_amount >= 0 AND change_amount = after_amount - before_amount),
    CONSTRAINT ck_finance_marketing_history_remark
        CHECK (BTRIM(remark) <> '')
);

CREATE TABLE IF NOT EXISTS config.finance_marketing_expense_type (
    expense_type_id BIGSERIAL PRIMARY KEY,
    expense_type_code VARCHAR(64) NOT NULL,
    expense_type_name VARCHAR(100) NOT NULL,
    remark VARCHAR(500),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_finance_expense_type_code UNIQUE (expense_type_code),
    CONSTRAINT uq_finance_expense_type_name UNIQUE (expense_type_name),
    CONSTRAINT ck_finance_expense_type_code CHECK (expense_type_code ~ '^[a-z][a-z0-9_]{1,63}$'),
    CONSTRAINT ck_finance_expense_type_name CHECK (BTRIM(expense_type_name) <> '')
);

CREATE OR REPLACE FUNCTION config.set_finance_configuration_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_finance_marketing_expense_type_updated_at
    ON config.finance_marketing_expense_type;
CREATE TRIGGER trg_finance_marketing_expense_type_updated_at
    BEFORE UPDATE ON config.finance_marketing_expense_type
    FOR EACH ROW EXECUTE FUNCTION config.set_finance_configuration_updated_at();

INSERT INTO config.finance_marketing_expense_type(
    expense_type_code, expense_type_name, remark, is_active, created_by, updated_by
)
SELECT 'legacy_' || SUBSTRING(md5(BTRIM(expense_type)) FROM 1 FOR 24),
       BTRIM(expense_type), '历史营销费用类型，迁移后可在费用类型管理中维护', TRUE,
       'system_migration', 'system_migration'
FROM config.finance_marketing_expense_detail
WHERE deleted_at IS NULL AND NULLIF(BTRIM(expense_type), '') IS NOT NULL
GROUP BY BTRIM(expense_type)
ON CONFLICT DO NOTHING;

INSERT INTO config.finance_marketing_expense_type(
    expense_type_code, expense_type_name, remark, is_active, created_by, updated_by
)
VALUES
    ('celebrity_cooperation', '明星合作', '明星或达人合作费用', TRUE, 'system_migration', 'system_migration'),
    ('advertising_cooperation', '广告合作', '广告投放及内容合作费用', TRUE, 'system_migration', 'system_migration'),
    ('brand_communication', '品牌传播', '品牌传播及公关费用', TRUE, 'system_migration', 'system_migration'),
    ('event_sponsorship', '活动赞助', '活动、展会及赞助费用', TRUE, 'system_migration', 'system_migration'),
    ('other_marketing', '其他营销', '其他整体营销费用', TRUE, 'system_migration', 'system_migration')
ON CONFLICT DO NOTHING;

COMMENT ON COLUMN config.finance_budget_monthly.promotion_budget_initialized_at IS '推广总预算首次设置时间；为空表示本月尚未设置推广总预算。';
COMMENT ON COLUMN config.finance_budget_monthly.marketing_budget_initialized_at IS '营销总预算首次设置时间；为空表示本月尚未设置营销总预算。';
COMMENT ON COLUMN config.finance_budget_monthly.promotion_budget_amount IS '推广总预算初始金额，单位元；后续修改通过不可覆盖的预算调整流水累计形成有效总预算，不再走审批。';

COMMENT ON COLUMN config.finance_promotion_budget_adjustment.before_amount IS '本次推广总预算调整前的有效总额，单位元；历史旧审批记录可能为空。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.after_amount IS '本次推广总预算调整后的有效总额，单位元；历史旧审批记录可能为空。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.change_remark IS '本次预算调整备注；后续修改必须填写。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.changed_by IS '执行本次预算调整的操作人显示名。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.change_type IS '变更来源类型：budget_update为总预算修改，legacy_adjustment为历史兼容记录。';
COMMENT ON TABLE config.finance_promotion_budget_adjustment IS '推广总预算不可覆盖的调整审计流水；新流程不再审批，approval_status仅为旧数据兼容字段且新记录固定为approved。';
COMMENT ON COLUMN config.finance_promotion_budget_adjustment.approval_status IS '历史兼容字段；新流程不再使用待审批、已通过、已拒绝业务状态，新产生的调整固定为approved。';

COMMENT ON TABLE config.finance_marketing_budget_change_history IS '营销总预算变更历史；每次首次设置后的金额修改独立留痕，不覆盖历史记录。';
COMMENT ON COLUMN config.finance_marketing_budget_change_history.history_id IS '营销预算变更历史代理主键。';
COMMENT ON COLUMN config.finance_marketing_budget_change_history.budget_month IS '变更归属月份，固定为当月第一天。';
COMMENT ON COLUMN config.finance_marketing_budget_change_history.before_amount IS '修改前营销总预算，单位元。';
COMMENT ON COLUMN config.finance_marketing_budget_change_history.after_amount IS '修改后营销总预算，单位元。';
COMMENT ON COLUMN config.finance_marketing_budget_change_history.change_amount IS '营销总预算本次变更金额，单位元，可正可负。';
COMMENT ON COLUMN config.finance_marketing_budget_change_history.changed_at IS '预算变更操作时间，带时区。';
COMMENT ON COLUMN config.finance_marketing_budget_change_history.changed_by IS '预算变更操作人显示名。';
COMMENT ON COLUMN config.finance_marketing_budget_change_history.remark IS '预算变更备注，后续修改必填。';
COMMENT ON COLUMN config.finance_marketing_budget_change_history.created_at IS '历史记录创建时间，带时区。';

COMMENT ON TABLE config.finance_marketing_expense_type IS '营销费用类型DIM；营销费用登记只能选择启用类型，类型新增和状态维护在本表完成。';
COMMENT ON COLUMN config.finance_marketing_expense_type.expense_type_id IS '营销费用类型代理主键。';
COMMENT ON COLUMN config.finance_marketing_expense_type.expense_type_code IS '营销费用类型稳定编码，供接口和历史记录引用。';
COMMENT ON COLUMN config.finance_marketing_expense_type.expense_type_name IS '营销费用类型展示名称。';
COMMENT ON COLUMN config.finance_marketing_expense_type.remark IS '营销费用类型维护备注。';
COMMENT ON COLUMN config.finance_marketing_expense_type.is_active IS '类型是否启用；停用后不能登记新费用，但不影响历史流水展示。';
COMMENT ON COLUMN config.finance_marketing_expense_type.created_by IS '类型创建人显示名。';
COMMENT ON COLUMN config.finance_marketing_expense_type.updated_by IS '类型最后修改人显示名。';
COMMENT ON COLUMN config.finance_marketing_expense_type.created_at IS '类型创建时间，带时区。';
COMMENT ON COLUMN config.finance_marketing_expense_type.updated_at IS '类型最后更新时间，带时区。';

CREATE INDEX IF NOT EXISTS idx_finance_marketing_history_month
    ON config.finance_marketing_budget_change_history (budget_month, changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_finance_expense_type_active
    ON config.finance_marketing_expense_type (is_active, expense_type_name);

-- 最终页面查看权限。
WITH resources(resource_code,resource_name,route_path,display_order) AS (
    VALUES
    ('finance_budget.overview.view','经营指标总览页面','/ingest/#financeOverview',10),
    ('finance_budget.gsv.view','GSV目标管理页面','/ingest/#financeGsv',20),
    ('finance_budget.promotion.view','推广预算执行页面','/ingest/#financePromotion',30),
    ('finance_budget.shop_budget.view','店铺预算分配页面','/ingest/#financeShopBudget',31),
    ('finance_budget.adjustment.view','预算调整记录页面','/ingest/#financeAdjustments',32),
    ('finance_budget.recharge.view','充值流水页面','/ingest/#financeRecharges',33),
    ('finance_budget.spend.view','推广消耗页面','/ingest/#financeSpend',34),
    ('finance_budget.marketing.view','营销预算管理页面','/ingest/#financeMarketing',40),
    ('finance_budget.expense_type.view','营销费用类型管理页面','/ingest/#financeExpenseTypes',41)
)
INSERT INTO iam.permission_resource(
    resource_code,resource_name,resource_type,module_code,parent_resource_id,route_path,display_order,is_active,updated_at
)
SELECT item.resource_code,item.resource_name,'page','operating_config',module.resource_id,
       item.route_path,item.display_order,TRUE,NOW()
FROM resources item
JOIN iam.permission_resource module ON module.resource_code='module.operating_config'
ON CONFLICT(resource_code) DO UPDATE SET
    resource_name=EXCLUDED.resource_name,
    resource_type=EXCLUDED.resource_type,
    module_code=EXCLUDED.module_code,
    parent_resource_id=EXCLUDED.parent_resource_id,
    route_path=EXCLUDED.route_path,
    display_order=EXCLUDED.display_order,
    is_active=TRUE,
    updated_at=NOW();

WITH resources(resource_code,resource_name,parent_code,display_order) AS (
    VALUES
    ('finance_budget.gsv_total.manage','设置财务月度总GSV目标','finance_budget.gsv.view',21),
    ('finance_budget.gsv_detail.manage','分配或调整店铺GSV目标','finance_budget.gsv.view',22),
    ('finance_budget.promotion_total.manage','设置或调整推广总预算','finance_budget.promotion.view',31),
    ('finance_budget.shop_budget.manage','分配或调整店铺推广预算','finance_budget.shop_budget.view',35),
    ('finance_budget.promotion_recharge.manage','登记推广充值','finance_budget.recharge.view',36),
    ('finance_budget.marketing_budget.manage','设置或调整营销预算','finance_budget.marketing.view',42),
    ('finance_budget.marketing_expense.manage','登记营销费用','finance_budget.marketing.view',43),
    ('finance_budget.expense_type.manage','维护营销费用类型','finance_budget.expense_type.view',44)
)
INSERT INTO iam.permission_resource(
    resource_code,resource_name,resource_type,module_code,parent_resource_id,route_path,display_order,is_active,updated_at
)
SELECT item.resource_code,item.resource_name,'action','operating_config',parent.resource_id,
       NULL,item.display_order,TRUE,NOW()
FROM resources item
JOIN iam.permission_resource parent ON parent.resource_code=item.parent_code
ON CONFLICT(resource_code) DO UPDATE SET
    resource_name=EXCLUDED.resource_name,
    resource_type=EXCLUDED.resource_type,
    module_code=EXCLUDED.module_code,
    parent_resource_id=EXCLUDED.parent_resource_id,
    display_order=EXCLUDED.display_order,
    is_active=TRUE,
    updated_at=NOW();

-- 399 号迁移先创建了推广明细/调整操作码；最终模型分别归并到店铺预算和推广总预算。
WITH legacy_map(old_code,new_code) AS (
    VALUES
    ('finance_budget.promotion_detail.manage','finance_budget.shop_budget.manage'),
    ('finance_budget.promotion_adjust.manage','finance_budget.promotion_total.manage')
)
INSERT INTO iam.role_permission(role_id,resource_id,granted_at)
SELECT assignment.role_id,new_resource.resource_id,NOW()
FROM iam.role_permission assignment
JOIN iam.permission_resource old_resource ON old_resource.resource_id=assignment.resource_id
JOIN legacy_map mapping ON mapping.old_code=old_resource.resource_code
JOIN iam.permission_resource new_resource ON new_resource.resource_code=mapping.new_code
ON CONFLICT(role_id,resource_id) DO NOTHING;

WITH legacy_map(old_code,new_code) AS (
    VALUES
    ('finance_budget.promotion_detail.manage','finance_budget.shop_budget.manage'),
    ('finance_budget.promotion_adjust.manage','finance_budget.promotion_total.manage')
)
INSERT INTO iam.department_permission(department_id,resource_id,granted_at)
SELECT assignment.department_id,new_resource.resource_id,NOW()
FROM iam.department_permission assignment
JOIN iam.permission_resource old_resource ON old_resource.resource_id=assignment.resource_id
JOIN legacy_map mapping ON mapping.old_code=old_resource.resource_code
JOIN iam.permission_resource new_resource ON new_resource.resource_code=mapping.new_code
ON CONFLICT(department_id,resource_id) DO NOTHING;

WITH legacy_map(old_code,new_code) AS (
    VALUES
    ('finance_budget.promotion_detail.manage','finance_budget.shop_budget.manage'),
    ('finance_budget.promotion_adjust.manage','finance_budget.promotion_total.manage')
)
INSERT INTO iam.user_permission(user_id,resource_id,permission_effect,granted_at)
SELECT assignment.user_id,new_resource.resource_id,assignment.permission_effect,NOW()
FROM iam.user_permission assignment
JOIN iam.permission_resource old_resource ON old_resource.resource_id=assignment.resource_id
JOIN legacy_map mapping ON mapping.old_code=old_resource.resource_code
JOIN iam.permission_resource new_resource ON new_resource.resource_code=mapping.new_code
ON CONFLICT(user_id,resource_id) DO NOTHING;

-- 旧推广总览访问权限要覆盖拆分后的全部推广只读页面，避免升级后现有角色失去访问能力。
WITH legacy_map(new_code) AS (
    VALUES
    ('finance_budget.shop_budget.view'),
    ('finance_budget.adjustment.view'),
    ('finance_budget.recharge.view'),
    ('finance_budget.spend.view')
)
INSERT INTO iam.role_permission(role_id,resource_id,granted_at)
SELECT assignment.role_id,new_resource.resource_id,NOW()
FROM iam.role_permission assignment
JOIN iam.permission_resource old_resource ON old_resource.resource_id=assignment.resource_id
JOIN legacy_map mapping ON TRUE
JOIN iam.permission_resource new_resource ON new_resource.resource_code=mapping.new_code
WHERE old_resource.resource_code='finance_budget.promotion.view'
ON CONFLICT(role_id,resource_id) DO NOTHING;

WITH legacy_map(new_code) AS (
    VALUES
    ('finance_budget.shop_budget.view'),
    ('finance_budget.adjustment.view'),
    ('finance_budget.recharge.view'),
    ('finance_budget.spend.view')
)
INSERT INTO iam.department_permission(department_id,resource_id,granted_at)
SELECT assignment.department_id,new_resource.resource_id,NOW()
FROM iam.department_permission assignment
JOIN iam.permission_resource old_resource ON old_resource.resource_id=assignment.resource_id
JOIN legacy_map mapping ON TRUE
JOIN iam.permission_resource new_resource ON new_resource.resource_code=mapping.new_code
WHERE old_resource.resource_code='finance_budget.promotion.view'
ON CONFLICT(department_id,resource_id) DO NOTHING;

WITH legacy_map(new_code) AS (
    VALUES
    ('finance_budget.shop_budget.view'),
    ('finance_budget.adjustment.view'),
    ('finance_budget.recharge.view'),
    ('finance_budget.spend.view')
)
INSERT INTO iam.user_permission(user_id,resource_id,permission_effect,granted_at)
SELECT assignment.user_id,new_resource.resource_id,assignment.permission_effect,NOW()
FROM iam.user_permission assignment
JOIN iam.permission_resource old_resource ON old_resource.resource_id=assignment.resource_id
JOIN legacy_map mapping ON TRUE
JOIN iam.permission_resource new_resource ON new_resource.resource_code=mapping.new_code
WHERE old_resource.resource_code='finance_budget.promotion.view'
ON CONFLICT(user_id,resource_id) DO NOTHING;

UPDATE iam.permission_resource
SET resource_name=CASE resource_code
        WHEN 'finance_budget.promotion_detail.manage' THEN '旧店铺推广预算操作权限（已停用）'
        WHEN 'finance_budget.promotion_adjust.manage' THEN '旧预算调整操作权限（已停用）'
    END,
    is_active=FALSE,
    updated_at=NOW()
WHERE resource_code IN ('finance_budget.promotion_detail.manage','finance_budget.promotion_adjust.manage');

INSERT INTO iam.role_permission(role_id,resource_id,granted_at)
SELECT role.role_id,resource.resource_id,NOW()
FROM iam.role role
CROSS JOIN iam.permission_resource resource
WHERE role.role_code='super_admin'
  AND resource.resource_code IN (
      'module.operating_config',
      'finance_budget.overview.view','finance_budget.gsv.view','finance_budget.gsv_total.manage','finance_budget.gsv_detail.manage',
      'finance_budget.promotion.view','finance_budget.promotion_total.manage',
      'finance_budget.shop_budget.view','finance_budget.shop_budget.manage',
      'finance_budget.adjustment.view','finance_budget.recharge.view','finance_budget.promotion_recharge.manage',
      'finance_budget.spend.view',
      'finance_budget.marketing.view','finance_budget.marketing_budget.manage','finance_budget.marketing_expense.manage',
      'finance_budget.expense_type.view','finance_budget.expense_type.manage'
  )
ON CONFLICT(role_id,resource_id) DO NOTHING;
