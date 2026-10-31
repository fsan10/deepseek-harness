-- 经营配置按页面和操作拆分权限；历史权限保留但停用，避免破坏既有授权记录。
WITH resources(resource_code,resource_name,resource_type,module_code,parent_code,route_path,display_order) AS (
    VALUES
    ('finance_budget.overview.view','经营指标总览页面','page','operating_config','module.operating_config','/ingest/#financeOverview',10),
    ('finance_budget.gsv.view','GSV目标管理页面','page','operating_config','module.operating_config','/ingest/#financeGsv',20),
    ('finance_budget.gsv_total.manage','设置财务月度总GSV目标','action','operating_config','finance_budget.gsv.view',NULL,21),
    ('finance_budget.gsv_detail.manage','设置店铺GSV目标及批量导入','action','operating_config','finance_budget.gsv.view',NULL,22),
    ('finance_budget.promotion.view','推广预算执行页面','page','operating_config','module.operating_config','/ingest/#financePromotion',30),
    ('finance_budget.promotion_total.manage','设置推广总预算','action','operating_config','finance_budget.promotion.view',NULL,31),
    ('finance_budget.promotion_detail.manage','维护店铺推广预算分配','action','operating_config','finance_budget.promotion.view',NULL,32),
    ('finance_budget.promotion_recharge.manage','登记推广充值','action','operating_config','finance_budget.promotion.view',NULL,33),
    ('finance_budget.promotion_adjust.manage','调整推广预算','action','operating_config','finance_budget.promotion.view',NULL,34),
    ('finance_budget.marketing.view','营销预算管理页面','page','operating_config','module.operating_config','/ingest/#financeMarketing',40),
    ('finance_budget.marketing_budget.manage','设置或修改营销预算','action','operating_config','finance_budget.marketing.view',NULL,41),
    ('finance_budget.marketing_expense.manage','登记营销费用','action','operating_config','finance_budget.marketing.view',NULL,42)
)
INSERT INTO iam.permission_resource(
    resource_code,resource_name,resource_type,module_code,parent_resource_id,route_path,display_order,is_active,updated_at
)
SELECT r.resource_code,r.resource_name,r.resource_type,r.module_code,parent.resource_id,r.route_path,r.display_order,TRUE,NOW()
FROM resources r
JOIN iam.permission_resource parent ON parent.resource_code=r.parent_code
WHERE r.resource_type='page'
ON CONFLICT(resource_code) DO UPDATE SET
    resource_name=EXCLUDED.resource_name,
    resource_type=EXCLUDED.resource_type,
    module_code=EXCLUDED.module_code,
    parent_resource_id=EXCLUDED.parent_resource_id,
    route_path=EXCLUDED.route_path,
    display_order=EXCLUDED.display_order,
    is_active=TRUE,
    updated_at=NOW();

WITH resources(resource_code,resource_name,resource_type,module_code,parent_code,route_path,display_order) AS (
    VALUES
    ('finance_budget.gsv_total.manage','设置财务月度总GSV目标','action','operating_config','finance_budget.gsv.view',NULL,21),
    ('finance_budget.gsv_detail.manage','设置店铺GSV目标及批量导入','action','operating_config','finance_budget.gsv.view',NULL,22),
    ('finance_budget.promotion_total.manage','设置推广总预算','action','operating_config','finance_budget.promotion.view',NULL,31),
    ('finance_budget.promotion_detail.manage','维护店铺推广预算分配','action','operating_config','finance_budget.promotion.view',NULL,32),
    ('finance_budget.promotion_recharge.manage','登记推广充值','action','operating_config','finance_budget.promotion.view',NULL,33),
    ('finance_budget.promotion_adjust.manage','调整推广预算','action','operating_config','finance_budget.promotion.view',NULL,34),
    ('finance_budget.marketing_budget.manage','设置或修改营销预算','action','operating_config','finance_budget.marketing.view',NULL,41),
    ('finance_budget.marketing_expense.manage','登记营销费用','action','operating_config','finance_budget.marketing.view',NULL,42)
)
INSERT INTO iam.permission_resource(
    resource_code,resource_name,resource_type,module_code,parent_resource_id,route_path,display_order,is_active,updated_at
)
SELECT r.resource_code,r.resource_name,r.resource_type,r.module_code,parent.resource_id,r.route_path,r.display_order,TRUE,NOW()
FROM resources r
JOIN iam.permission_resource parent ON parent.resource_code=r.parent_code
ON CONFLICT(resource_code) DO UPDATE SET
    resource_name=EXCLUDED.resource_name,
    resource_type=EXCLUDED.resource_type,
    module_code=EXCLUDED.module_code,
    parent_resource_id=EXCLUDED.parent_resource_id,
    route_path=EXCLUDED.route_path,
    display_order=EXCLUDED.display_order,
    is_active=TRUE,
    updated_at=NOW();

WITH legacy_map(old_code,new_code) AS (
    VALUES
    ('finance_budget.view','finance_budget.overview.view'),
    ('finance_budget.view','finance_budget.gsv.view'),
    ('finance_budget.view','finance_budget.promotion.view'),
    ('finance_budget.view','finance_budget.marketing.view'),
    ('finance_budget.manage','finance_budget.gsv_total.manage'),
    ('finance_budget.manage','finance_budget.gsv_detail.manage'),
    ('finance_budget.manage','finance_budget.promotion_total.manage'),
    ('finance_budget.manage','finance_budget.promotion_detail.manage'),
    ('finance_budget.manage','finance_budget.promotion_recharge.manage'),
    ('finance_budget.manage','finance_budget.promotion_adjust.manage'),
    ('finance_budget.manage','finance_budget.marketing_budget.manage'),
    ('finance_budget.manage','finance_budget.marketing_expense.manage'),
    ('finance_budget.total.manage','finance_budget.gsv_total.manage'),
    ('finance_budget.total.manage','finance_budget.promotion_total.manage'),
    ('finance_budget.total.manage','finance_budget.promotion_recharge.manage'),
    ('finance_budget.total.manage','finance_budget.promotion_adjust.manage'),
    ('finance_budget.total.manage','finance_budget.marketing_budget.manage'),
    ('finance_budget.total.manage','finance_budget.marketing_expense.manage'),
    ('finance_budget.detail.manage','finance_budget.gsv_detail.manage'),
    ('finance_budget.detail.manage','finance_budget.promotion_detail.manage')
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
    ('finance_budget.view','finance_budget.overview.view'),
    ('finance_budget.view','finance_budget.gsv.view'),
    ('finance_budget.view','finance_budget.promotion.view'),
    ('finance_budget.view','finance_budget.marketing.view'),
    ('finance_budget.manage','finance_budget.gsv_total.manage'),
    ('finance_budget.manage','finance_budget.gsv_detail.manage'),
    ('finance_budget.manage','finance_budget.promotion_total.manage'),
    ('finance_budget.manage','finance_budget.promotion_detail.manage'),
    ('finance_budget.manage','finance_budget.promotion_recharge.manage'),
    ('finance_budget.manage','finance_budget.promotion_adjust.manage'),
    ('finance_budget.manage','finance_budget.marketing_budget.manage'),
    ('finance_budget.manage','finance_budget.marketing_expense.manage'),
    ('finance_budget.total.manage','finance_budget.gsv_total.manage'),
    ('finance_budget.total.manage','finance_budget.promotion_total.manage'),
    ('finance_budget.total.manage','finance_budget.promotion_recharge.manage'),
    ('finance_budget.total.manage','finance_budget.promotion_adjust.manage'),
    ('finance_budget.total.manage','finance_budget.marketing_budget.manage'),
    ('finance_budget.total.manage','finance_budget.marketing_expense.manage'),
    ('finance_budget.detail.manage','finance_budget.gsv_detail.manage'),
    ('finance_budget.detail.manage','finance_budget.promotion_detail.manage')
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
    ('finance_budget.view','finance_budget.overview.view'),
    ('finance_budget.view','finance_budget.gsv.view'),
    ('finance_budget.view','finance_budget.promotion.view'),
    ('finance_budget.view','finance_budget.marketing.view'),
    ('finance_budget.manage','finance_budget.gsv_total.manage'),
    ('finance_budget.manage','finance_budget.gsv_detail.manage'),
    ('finance_budget.manage','finance_budget.promotion_total.manage'),
    ('finance_budget.manage','finance_budget.promotion_detail.manage'),
    ('finance_budget.manage','finance_budget.promotion_recharge.manage'),
    ('finance_budget.manage','finance_budget.promotion_adjust.manage'),
    ('finance_budget.manage','finance_budget.marketing_budget.manage'),
    ('finance_budget.manage','finance_budget.marketing_expense.manage'),
    ('finance_budget.total.manage','finance_budget.gsv_total.manage'),
    ('finance_budget.total.manage','finance_budget.promotion_total.manage'),
    ('finance_budget.total.manage','finance_budget.promotion_recharge.manage'),
    ('finance_budget.total.manage','finance_budget.promotion_adjust.manage'),
    ('finance_budget.total.manage','finance_budget.marketing_budget.manage'),
    ('finance_budget.total.manage','finance_budget.marketing_expense.manage'),
    ('finance_budget.detail.manage','finance_budget.gsv_detail.manage'),
    ('finance_budget.detail.manage','finance_budget.promotion_detail.manage')
)
INSERT INTO iam.user_permission(user_id,resource_id,permission_effect,granted_at)
SELECT assignment.user_id,new_resource.resource_id,assignment.permission_effect,NOW()
FROM iam.user_permission assignment
JOIN iam.permission_resource old_resource ON old_resource.resource_id=assignment.resource_id
JOIN legacy_map mapping ON mapping.old_code=old_resource.resource_code
JOIN iam.permission_resource new_resource ON new_resource.resource_code=mapping.new_code
ON CONFLICT(user_id,resource_id) DO NOTHING;

UPDATE iam.permission_resource
SET resource_name=CASE resource_code
        WHEN 'finance_budget.view' THEN '经营配置旧页面权限（已停用）'
        WHEN 'finance_budget.manage' THEN '经营配置旧维护权限（已停用）'
        WHEN 'finance_budget.total.manage' THEN '经营配置旧总控权限（已停用）'
        WHEN 'finance_budget.detail.manage' THEN '经营配置旧明细权限（已停用）'
    END,
    is_active=FALSE,
    updated_at=NOW()
WHERE resource_code IN ('finance_budget.view','finance_budget.manage','finance_budget.total.manage','finance_budget.detail.manage');

INSERT INTO iam.role_permission(role_id,resource_id,granted_at)
SELECT role.role_id,resource.resource_id,NOW()
FROM iam.role role
CROSS JOIN iam.permission_resource resource
WHERE role.role_code='super_admin'
  AND resource.resource_code IN (
      'module.operating_config',
      'finance_budget.overview.view','finance_budget.gsv.view','finance_budget.gsv_total.manage','finance_budget.gsv_detail.manage',
      'finance_budget.promotion.view','finance_budget.promotion_total.manage','finance_budget.promotion_detail.manage',
      'finance_budget.promotion_recharge.manage','finance_budget.promotion_adjust.manage',
      'finance_budget.marketing.view','finance_budget.marketing_budget.manage','finance_budget.marketing_expense.manage'
  )
ON CONFLICT(role_id,resource_id) DO NOTHING;
