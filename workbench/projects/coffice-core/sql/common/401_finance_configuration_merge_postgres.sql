-- 经营配置页面合并：推广预算管理承载店铺预算明细，预算调整记录承载两类预算历史。
-- 本迁移只调整权限归属和历史授权，不删除任何业务流水。

WITH legacy_map(old_code, new_code) AS (
    VALUES
        ('finance_budget.shop_budget.view', 'finance_budget.promotion.view'),
        ('finance_budget.promotion_detail.manage', 'finance_budget.shop_budget.manage'),
        ('finance_budget.promotion_adjust.manage', 'finance_budget.promotion_total.manage')
)
INSERT INTO iam.role_permission(role_id, resource_id, granted_at)
SELECT assignment.role_id, new_resource.resource_id, NOW()
  FROM iam.role_permission assignment
  JOIN iam.permission_resource old_resource
    ON old_resource.resource_id = assignment.resource_id
  JOIN legacy_map mapping
    ON mapping.old_code = old_resource.resource_code
  JOIN iam.permission_resource new_resource
    ON new_resource.resource_code = mapping.new_code
 ON CONFLICT(role_id, resource_id) DO NOTHING;

WITH legacy_map(old_code, new_code) AS (
    VALUES
        ('finance_budget.shop_budget.view', 'finance_budget.promotion.view'),
        ('finance_budget.promotion_detail.manage', 'finance_budget.shop_budget.manage'),
        ('finance_budget.promotion_adjust.manage', 'finance_budget.promotion_total.manage')
)
INSERT INTO iam.department_permission(department_id, resource_id, granted_at)
SELECT assignment.department_id, new_resource.resource_id, NOW()
  FROM iam.department_permission assignment
  JOIN iam.permission_resource old_resource
    ON old_resource.resource_id = assignment.resource_id
  JOIN legacy_map mapping
    ON mapping.old_code = old_resource.resource_code
  JOIN iam.permission_resource new_resource
    ON new_resource.resource_code = mapping.new_code
 ON CONFLICT(department_id, resource_id) DO NOTHING;

WITH legacy_map(old_code, new_code) AS (
    VALUES
        ('finance_budget.shop_budget.view', 'finance_budget.promotion.view'),
        ('finance_budget.promotion_detail.manage', 'finance_budget.shop_budget.manage'),
        ('finance_budget.promotion_adjust.manage', 'finance_budget.promotion_total.manage')
)
INSERT INTO iam.user_permission(user_id, resource_id, permission_effect, granted_at)
SELECT assignment.user_id, new_resource.resource_id, assignment.permission_effect, NOW()
  FROM iam.user_permission assignment
  JOIN iam.permission_resource old_resource
    ON old_resource.resource_id = assignment.resource_id
  JOIN legacy_map mapping
    ON mapping.old_code = old_resource.resource_code
  JOIN iam.permission_resource new_resource
    ON new_resource.resource_code = mapping.new_code
 ON CONFLICT(user_id, resource_id) DO NOTHING;

UPDATE iam.permission_resource
   SET resource_name = '推广预算管理页面',
       route_path = '/ingest/#financePromotion',
       display_order = 30,
       is_active = TRUE,
       updated_at = NOW()
 WHERE resource_code = 'finance_budget.promotion.view';

UPDATE iam.permission_resource AS action
   SET parent_resource_id = page.resource_id,
       resource_name = '分配或调整店铺推广预算',
       is_active = TRUE,
       updated_at = NOW()
  FROM iam.permission_resource page
 WHERE action.resource_code = 'finance_budget.shop_budget.manage'
   AND page.resource_code = 'finance_budget.promotion.view';

UPDATE iam.permission_resource
   SET resource_name = CASE resource_code
           WHEN 'finance_budget.shop_budget.view' THEN '旧店铺预算页面权限（已停用）'
           WHEN 'finance_budget.promotion_detail.manage' THEN '旧店铺预算操作权限（已停用）'
           WHEN 'finance_budget.promotion_adjust.manage' THEN '旧预算调整操作权限（已停用）'
       END,
       is_active = FALSE,
       updated_at = NOW()
 WHERE resource_code IN (
       'finance_budget.shop_budget.view',
       'finance_budget.promotion_detail.manage',
       'finance_budget.promotion_adjust.manage'
 );

-- 兼容旧系统中已有的营销费用分类；类型管理页和登记页都从这张表读取。
INSERT INTO config.finance_marketing_expense_type(
    expense_type_code, expense_type_name, remark, is_active, created_by, updated_by
)
VALUES (
    'talent_cooperation', '达人合作', '达人、主播或内容创作者合作费用', TRUE,
    'system_migration', 'system_migration'
)
ON CONFLICT DO NOTHING;
