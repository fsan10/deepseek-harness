-- 平台、店铺与公司映射后台页面和维护操作权限。
INSERT INTO iam.permission_resource (
    resource_code, resource_name, resource_type, module_code,
    parent_resource_id, route_path, display_order, is_active, updated_at
)
SELECT 'system.platform_shop_company.view', '平台店铺公司映射页面', 'page', 'system',
       parent.resource_id, '/system/#platformShopCompany', 70, TRUE, NOW()
FROM iam.permission_resource parent
WHERE parent.resource_code = 'module.system'
ON CONFLICT (resource_code) DO UPDATE SET
    resource_name = EXCLUDED.resource_name,
    resource_type = EXCLUDED.resource_type,
    module_code = EXCLUDED.module_code,
    parent_resource_id = EXCLUDED.parent_resource_id,
    route_path = EXCLUDED.route_path,
    display_order = EXCLUDED.display_order,
    is_active = TRUE,
    updated_at = NOW();

INSERT INTO iam.permission_resource (
    resource_code, resource_name, resource_type, module_code,
    parent_resource_id, route_path, display_order, is_active, updated_at
)
SELECT 'system.platform_shop_company.manage', '维护平台店铺公司映射', 'action', 'system',
       parent.resource_id, NULL, 71, TRUE, NOW()
FROM iam.permission_resource parent
WHERE parent.resource_code = 'system.platform_shop_company.view'
ON CONFLICT (resource_code) DO UPDATE SET
    resource_name = EXCLUDED.resource_name,
    resource_type = EXCLUDED.resource_type,
    module_code = EXCLUDED.module_code,
    parent_resource_id = EXCLUDED.parent_resource_id,
    route_path = EXCLUDED.route_path,
    display_order = EXCLUDED.display_order,
    is_active = TRUE,
    updated_at = NOW();
