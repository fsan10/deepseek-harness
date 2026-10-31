WITH resources(resource_code, resource_name, resource_type, module_code, parent_code, route_path, display_order) AS (
    VALUES
    ('module.dashboard', '经营仪表盘', 'module', 'dashboard', NULL, '/dashboards/', 10),
    ('module.bank', '银行资金', 'module', 'bank', NULL, '/', 20),
    ('module.influencer', '达播运营', 'module', 'influencer', NULL, '/influencer/', 30),
    ('module.ingest', '数据导入', 'module', 'ingest', NULL, '/ingest/', 40),
    ('module.platform_fee', '平台费用管理', 'module', 'platform_fee', NULL, '/ingest/', 50),
    ('module.system', '系统管理', 'module', 'system', NULL, '/system/', 90)
)
INSERT INTO iam.permission_resource (
    resource_code, resource_name, resource_type, module_code,
    parent_resource_id, route_path, display_order, is_active, updated_at
)
SELECT r.resource_code, r.resource_name, r.resource_type, r.module_code,
       NULL, r.route_path, r.display_order, TRUE, NOW()
FROM resources r
ON CONFLICT (resource_code) DO UPDATE SET
    resource_name = EXCLUDED.resource_name,
    resource_type = EXCLUDED.resource_type,
    module_code = EXCLUDED.module_code,
    route_path = EXCLUDED.route_path,
    display_order = EXCLUDED.display_order,
    is_active = TRUE,
    updated_at = NOW();
WITH resources(resource_code, resource_name, resource_type, module_code, parent_code, route_path, display_order) AS (
    VALUES
    ('bank.statement.view', '资金流水编辑页面', 'page', 'bank', 'module.bank', '/#statement', 10),
    ('bank.statement.import', '导入银行流水', 'action', 'bank', 'bank.statement.view', NULL, 11),
    ('bank.statement.split', '拆分与取消拆分', 'action', 'bank', 'bank.statement.view', NULL, 12),
    ('bank.statement.adjust', '流水调账与复原', 'action', 'bank', 'bank.statement.view', NULL, 13),
    ('bank.statement.assign', '批量分配费用与入账', 'action', 'bank', 'bank.statement.view', NULL, 14),
    ('bank.statement.submit', '提交银行流水', 'action', 'bank', 'bank.statement.view', NULL, 15),
    ('bank.statement.withdraw', '撤回银行流水提交', 'action', 'bank', 'bank.statement.view', NULL, 16),
    ('bank.types.view', '费用类型管理页面', 'page', 'bank', 'module.bank', '/#types', 20),
    ('bank.types.manage', '维护费用类型', 'action', 'bank', 'bank.types.view', NULL, 21),
    ('bank.accounts.view', '入账管理页面', 'page', 'bank', 'module.bank', '/#accounts', 30),
    ('bank.accounts.manage', '维护入账科目', 'action', 'bank', 'bank.accounts.view', NULL, 31),
    ('bank.imports.view', '银行导入记录页面', 'page', 'bank', 'module.bank', '/#imports', 40),
    ('bank.logs.view', '银行操作日志页面', 'page', 'bank', 'module.bank', '/#logs', 50),
    ('influencer.assignments.view', '达人商务归属页面', 'page', 'influencer', 'module.influencer', '/influencer/#assignmentPanel', 10),
    ('influencer.assignments.manage', '维护达人商务归属', 'action', 'influencer', 'influencer.assignments.view', NULL, 11),
    ('influencer.targets.view', '商务月度目标页面', 'page', 'influencer', 'module.influencer', '/influencer/#targetPanel', 20),
    ('influencer.targets.manage', '维护商务与月度目标', 'action', 'influencer', 'influencer.targets.view', NULL, 21),
    ('influencer.products.view', '商品品类配置页面', 'page', 'influencer', 'module.influencer', '/influencer/#productCategoryPanel', 30),
    ('influencer.products.manage', '维护商品品类配置', 'action', 'influencer', 'influencer.products.view', NULL, 31),
    ('ingest.upload.view', '数据上传页面', 'page', 'ingest', 'module.ingest', '/ingest/#upload', 10),
    ('ingest.upload.manage', '上传与提交数据文件', 'action', 'ingest', 'ingest.upload.view', NULL, 11),
    ('ingest.runs.view', '导入记录页面', 'page', 'ingest', 'module.ingest', '/ingest/#runs', 20),
    ('ingest.etl.view', 'ETL任务页面', 'page', 'ingest', 'module.ingest', '/ingest/#etl', 30),
    ('ingest.etl.manage', '创建与重试ETL任务', 'action', 'ingest', 'ingest.etl.view', NULL, 31),
    ('ingest.logs.view', '数据导入操作日志页面', 'page', 'ingest', 'module.ingest', '/ingest/#logs', 40),
    ('platform_fee.categories.view', '一级分类管理页面', 'page', 'platform_fee', 'module.platform_fee', '/ingest/#feeCategories', 10),
    ('platform_fee.categories.manage', '维护平台费用一级分类', 'action', 'platform_fee', 'platform_fee.categories.view', NULL, 11),
    ('platform_fee.mappings.view', '费用映射页面', 'page', 'platform_fee', 'module.platform_fee', '/ingest/#feeMappings', 20),
    ('platform_fee.mappings.manage', '维护平台费用映射', 'action', 'platform_fee', 'platform_fee.mappings.view', NULL, 21),
    ('platform_fee.raw.view', '原始费用页面', 'page', 'platform_fee', 'module.platform_fee', '/ingest/#rawFees', 30),
    ('system.dashboard.manage', '看板管理', 'page', 'system', 'module.system', '/system/#dashboards', 10),
    ('system.user.manage', '用户管理', 'page', 'system', 'module.system', '/system/#users', 20),
    ('system.user.password.view', '查看用户密码', 'action', 'system', 'system.user.manage', NULL, 21),
    ('system.department.manage', '部门管理', 'page', 'system', 'module.system', '/system/#departments', 30),
    ('system.role.manage', '角色管理', 'page', 'system', 'module.system', '/system/#roles', 40),
    ('system.permission.manage', '权限管理', 'page', 'system', 'module.system', '/system/#permissions', 50),
    ('system.audit.view', '统一审计日志', 'page', 'system', 'module.system', '/system/#audit', 60)
)
INSERT INTO iam.permission_resource (
    resource_code, resource_name, resource_type, module_code,
    parent_resource_id, route_path, display_order, is_active, updated_at
)
SELECT r.resource_code, r.resource_name, r.resource_type, r.module_code,
       parent.resource_id, r.route_path, r.display_order, TRUE, NOW()
FROM resources r
JOIN iam.permission_resource parent ON parent.resource_code = r.parent_code
ON CONFLICT (resource_code) DO UPDATE SET
    resource_name = EXCLUDED.resource_name,
    resource_type = EXCLUDED.resource_type,
    module_code = EXCLUDED.module_code,
    parent_resource_id = EXCLUDED.parent_resource_id,
    route_path = EXCLUDED.route_path,
    display_order = EXCLUDED.display_order,
    is_active = TRUE,
    updated_at = NOW();

