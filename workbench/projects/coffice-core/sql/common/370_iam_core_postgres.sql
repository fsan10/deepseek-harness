CREATE SCHEMA IF NOT EXISTS iam;

CREATE TABLE IF NOT EXISTS iam.department (
    department_id BIGSERIAL PRIMARY KEY,
    department_code VARCHAR(64) NOT NULL,
    department_name VARCHAR(100) NOT NULL,
    parent_department_id BIGINT REFERENCES iam.department(department_id) ON DELETE RESTRICT,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT uq_iam_department_code UNIQUE (department_code),
    CONSTRAINT ck_iam_department_code CHECK (department_code ~ '^[a-z][a-z0-9_]{1,63}$'),
    CONSTRAINT ck_iam_department_name CHECK (BTRIM(department_name) <> ''),
    CONSTRAINT ck_iam_department_order CHECK (display_order >= 0),
    CONSTRAINT ck_iam_department_not_self CHECK (parent_department_id IS NULL OR parent_department_id <> department_id)
);

CREATE TABLE IF NOT EXISTS iam.user_account (
    user_id BIGSERIAL PRIMARY KEY,
    username VARCHAR(64) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    department_id BIGINT REFERENCES iam.department(department_id) ON DELETE RESTRICT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_super_admin BOOLEAN NOT NULL DEFAULT FALSE,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    session_version INTEGER NOT NULL DEFAULT 1,
    password_changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT uq_iam_user_username UNIQUE (username),
    CONSTRAINT ck_iam_user_username CHECK (username ~ '^[a-z][a-z0-9_.-]{2,63}$'),
    CONSTRAINT ck_iam_user_display_name CHECK (BTRIM(display_name) <> ''),
    CONSTRAINT ck_iam_user_failed_login CHECK (failed_login_count >= 0),
    CONSTRAINT ck_iam_user_session_version CHECK (session_version >= 1)
);

CREATE TABLE IF NOT EXISTS iam.role (
    role_id BIGSERIAL PRIMARY KEY,
    role_code VARCHAR(64) NOT NULL,
    role_name VARCHAR(100) NOT NULL,
    role_description VARCHAR(500) NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT uq_iam_role_code UNIQUE (role_code),
    CONSTRAINT ck_iam_role_code CHECK (role_code ~ '^[a-z][a-z0-9_]{1,63}$'),
    CONSTRAINT ck_iam_role_name CHECK (BTRIM(role_name) <> '')
);

CREATE TABLE IF NOT EXISTS iam.user_role (
    user_id BIGINT NOT NULL REFERENCES iam.user_account(user_id) ON DELETE CASCADE,
    role_id BIGINT NOT NULL REFERENCES iam.role(role_id) ON DELETE CASCADE,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    granted_by BIGINT REFERENCES iam.user_account(user_id) ON DELETE SET NULL,
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS iam.permission_resource (
    resource_id BIGSERIAL PRIMARY KEY,
    resource_code VARCHAR(128) NOT NULL,
    resource_name VARCHAR(120) NOT NULL,
    resource_type VARCHAR(24) NOT NULL,
    module_code VARCHAR(64) NOT NULL,
    parent_resource_id BIGINT REFERENCES iam.permission_resource(resource_id) ON DELETE RESTRICT,
    route_path VARCHAR(255),
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_iam_permission_resource_code UNIQUE (resource_code),
    CONSTRAINT ck_iam_permission_resource_code CHECK (resource_code ~ '^[a-z][a-z0-9_.:-]{2,127}$'),
    CONSTRAINT ck_iam_permission_resource_name CHECK (BTRIM(resource_name) <> ''),
    CONSTRAINT ck_iam_permission_resource_type CHECK (resource_type IN ('module', 'page', 'action', 'dashboard')),
    CONSTRAINT ck_iam_permission_resource_order CHECK (display_order >= 0),
    CONSTRAINT ck_iam_permission_resource_not_self CHECK (parent_resource_id IS NULL OR parent_resource_id <> resource_id)
);

CREATE TABLE IF NOT EXISTS iam.role_permission (
    role_id BIGINT NOT NULL REFERENCES iam.role(role_id) ON DELETE CASCADE,
    resource_id BIGINT NOT NULL REFERENCES iam.permission_resource(resource_id) ON DELETE CASCADE,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    granted_by BIGINT REFERENCES iam.user_account(user_id) ON DELETE SET NULL,
    PRIMARY KEY (role_id, resource_id)
);

CREATE TABLE IF NOT EXISTS iam.department_permission (
    department_id BIGINT NOT NULL REFERENCES iam.department(department_id) ON DELETE CASCADE,
    resource_id BIGINT NOT NULL REFERENCES iam.permission_resource(resource_id) ON DELETE CASCADE,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    granted_by BIGINT REFERENCES iam.user_account(user_id) ON DELETE SET NULL,
    PRIMARY KEY (department_id, resource_id)
);

CREATE TABLE IF NOT EXISTS iam.user_permission (
    user_id BIGINT NOT NULL REFERENCES iam.user_account(user_id) ON DELETE CASCADE,
    resource_id BIGINT NOT NULL REFERENCES iam.permission_resource(resource_id) ON DELETE CASCADE,
    permission_effect VARCHAR(8) NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    granted_by BIGINT REFERENCES iam.user_account(user_id) ON DELETE SET NULL,
    PRIMARY KEY (user_id, resource_id),
    CONSTRAINT ck_iam_user_permission_effect CHECK (permission_effect IN ('allow', 'deny'))
);

CREATE TABLE IF NOT EXISTS iam.user_session (
    session_token_hash CHAR(64) PRIMARY KEY,
    csrf_token_hash CHAR(64) NOT NULL,
    user_id BIGINT NOT NULL REFERENCES iam.user_account(user_id) ON DELETE CASCADE,
    user_session_version INTEGER NOT NULL,
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    idle_expires_at TIMESTAMPTZ NOT NULL,
    absolute_expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    CONSTRAINT ck_iam_session_version CHECK (user_session_version >= 1),
    CONSTRAINT ck_iam_session_expiry CHECK (idle_expires_at <= absolute_expires_at)
);

CREATE TABLE IF NOT EXISTS iam.login_attempt (
    login_attempt_id BIGSERIAL PRIMARY KEY,
    username VARCHAR(64) NOT NULL,
    ip_address VARCHAR(45),
    is_success BOOLEAN NOT NULL,
    failure_reason VARCHAR(64),
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS iam.audit_log (
    audit_log_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES iam.user_account(user_id) ON DELETE SET NULL,
    username VARCHAR(64),
    action_code VARCHAR(96) NOT NULL,
    target_type VARCHAR(64) NOT NULL,
    target_id VARCHAR(128),
    change_before JSONB,
    change_after JSONB,
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_iam_department_parent ON iam.department(parent_department_id, display_order) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_iam_department_active ON iam.department(is_active, display_order) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_iam_user_department ON iam.user_account(department_id, is_active) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_iam_user_active ON iam.user_account(is_active, username) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_iam_user_role_role ON iam.user_role(role_id, user_id);
CREATE INDEX IF NOT EXISTS idx_iam_resource_parent ON iam.permission_resource(parent_resource_id, display_order);
CREATE INDEX IF NOT EXISTS idx_iam_resource_module ON iam.permission_resource(module_code, resource_type, display_order) WHERE is_active;
CREATE INDEX IF NOT EXISTS idx_iam_role_permission_resource ON iam.role_permission(resource_id, role_id);
CREATE INDEX IF NOT EXISTS idx_iam_department_permission_resource ON iam.department_permission(resource_id, department_id);
CREATE INDEX IF NOT EXISTS idx_iam_user_permission_resource ON iam.user_permission(resource_id, permission_effect, user_id);
CREATE INDEX IF NOT EXISTS idx_iam_session_user ON iam.user_session(user_id, revoked_at, absolute_expires_at);
CREATE INDEX IF NOT EXISTS idx_iam_session_expiry ON iam.user_session(idle_expires_at, absolute_expires_at) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_iam_login_attempt_lookup ON iam.login_attempt(username, ip_address, attempted_at DESC);
CREATE INDEX IF NOT EXISTS idx_iam_audit_created ON iam.audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_iam_audit_user ON iam.audit_log(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_iam_audit_target ON iam.audit_log(target_type, target_id, created_at DESC);

COMMENT ON SCHEMA iam IS '经营配置中心身份认证、组织、角色、权限、会话和统一审计对象。';
COMMENT ON TABLE iam.department IS '经营配置中心多级部门树；软删除保留历史授权和用户归属。';
COMMENT ON COLUMN iam.department.department_id IS '部门内部自增主键。';
COMMENT ON COLUMN iam.department.department_code IS '部门唯一英文snake_case编码。';
COMMENT ON COLUMN iam.department.department_name IS '部门中文展示名称。';
COMMENT ON COLUMN iam.department.parent_department_id IS '上级部门主键；NULL表示根部门。';
COMMENT ON COLUMN iam.department.display_order IS '同级部门展示顺序，数值越小越靠前。';
COMMENT ON COLUMN iam.department.is_active IS '部门是否启用；停用部门不再提供继承权限。';
COMMENT ON COLUMN iam.department.created_at IS '部门创建时间，带时区。';
COMMENT ON COLUMN iam.department.updated_at IS '部门最后更新时间，带时区。';
COMMENT ON COLUMN iam.department.deleted_at IS '部门软删除时间；NULL表示未删除。';
COMMENT ON TABLE iam.user_account IS '经营配置中心后台用户账号，不保存任何明文密码。';
COMMENT ON COLUMN iam.user_account.user_id IS '用户内部自增主键。';
COMMENT ON COLUMN iam.user_account.username IS '登录用户名；服务层统一转为小写，数据库唯一。';
COMMENT ON COLUMN iam.user_account.display_name IS '用户中文展示名称。';
COMMENT ON COLUMN iam.user_account.password_hash IS 'bcrypt密码哈希，包含算法版本、成本和随机盐。';
COMMENT ON COLUMN iam.user_account.department_id IS '用户直属部门主键。';
COMMENT ON COLUMN iam.user_account.is_active IS '用户是否允许登录和继续使用已有会话。';
COMMENT ON COLUMN iam.user_account.is_super_admin IS '是否为超级管理员；超级管理员拥有全部有效资源。';
COMMENT ON COLUMN iam.user_account.failed_login_count IS '自最近成功登录后的连续失败次数。';
COMMENT ON COLUMN iam.user_account.locked_until IS '登录失败限制的锁定截止时间，带时区。';
COMMENT ON COLUMN iam.user_account.session_version IS '会话失效版本；禁用或重置密码时递增使旧会话失效。';
COMMENT ON COLUMN iam.user_account.password_changed_at IS '最后修改或重置密码时间，带时区。';
COMMENT ON COLUMN iam.user_account.last_login_at IS '最后成功登录时间，带时区。';
COMMENT ON COLUMN iam.user_account.created_at IS '用户创建时间，带时区。';
COMMENT ON COLUMN iam.user_account.updated_at IS '用户最后更新时间，带时区。';
COMMENT ON COLUMN iam.user_account.deleted_at IS '用户软删除时间；当前功能仅启停用户，NULL表示有效记录。';
COMMENT ON TABLE iam.role IS '经营配置中心角色定义。';
COMMENT ON COLUMN iam.role.role_id IS '角色内部自增主键。';
COMMENT ON COLUMN iam.role.role_code IS '角色唯一英文snake_case编码。';
COMMENT ON COLUMN iam.role.role_name IS '角色中文展示名称。';
COMMENT ON COLUMN iam.role.role_description IS '角色职责说明。';
COMMENT ON COLUMN iam.role.is_active IS '角色是否参与最终权限计算。';
COMMENT ON COLUMN iam.role.created_at IS '角色创建时间，带时区。';
COMMENT ON COLUMN iam.role.updated_at IS '角色最后更新时间，带时区。';
COMMENT ON COLUMN iam.role.deleted_at IS '角色软删除时间；NULL表示未删除。';
COMMENT ON TABLE iam.user_role IS '用户与角色多对多关系。';
COMMENT ON COLUMN iam.user_role.user_id IS '被授予角色的用户主键。';
COMMENT ON COLUMN iam.user_role.role_id IS '授予的角色主键。';
COMMENT ON COLUMN iam.user_role.granted_at IS '角色授予时间，带时区。';
COMMENT ON COLUMN iam.user_role.granted_by IS '执行授予操作的用户主键。';
COMMENT ON TABLE iam.permission_resource IS '统一页面、操作和动态看板权限资源树。';
COMMENT ON COLUMN iam.permission_resource.resource_id IS '权限资源内部自增主键。';
COMMENT ON COLUMN iam.permission_resource.resource_code IS '权限判断使用的全局唯一稳定编码。';
COMMENT ON COLUMN iam.permission_resource.resource_name IS '权限资源中文展示名称。';
COMMENT ON COLUMN iam.permission_resource.resource_type IS '资源类型：module模块、page页面、action操作或dashboard看板。';
COMMENT ON COLUMN iam.permission_resource.module_code IS '资源所属业务模块编码。';
COMMENT ON COLUMN iam.permission_resource.parent_resource_id IS '权限树上级资源主键。';
COMMENT ON COLUMN iam.permission_resource.route_path IS '页面或接口的参考路由；动态看板存放后台看板路由。';
COMMENT ON COLUMN iam.permission_resource.display_order IS '权限树展示顺序，数值越小越靠前。';
COMMENT ON COLUMN iam.permission_resource.is_active IS '资源是否参与授权和最终权限计算。';
COMMENT ON COLUMN iam.permission_resource.created_at IS '资源创建时间，带时区。';
COMMENT ON COLUMN iam.permission_resource.updated_at IS '资源最后更新时间，带时区。';
COMMENT ON TABLE iam.role_permission IS '角色允许的权限资源；角色层仅提供允许授权。';
COMMENT ON COLUMN iam.role_permission.role_id IS '获得权限的角色主键。';
COMMENT ON COLUMN iam.role_permission.resource_id IS '被允许访问的资源主键。';
COMMENT ON COLUMN iam.role_permission.granted_at IS '权限授予时间，带时区。';
COMMENT ON COLUMN iam.role_permission.granted_by IS '执行授予操作的用户主键。';
COMMENT ON TABLE iam.department_permission IS '部门允许的权限资源；用户继承直属部门及全部启用上级部门。';
COMMENT ON COLUMN iam.department_permission.department_id IS '获得权限的部门主键。';
COMMENT ON COLUMN iam.department_permission.resource_id IS '被允许访问的资源主键。';
COMMENT ON COLUMN iam.department_permission.granted_at IS '权限授予时间，带时区。';
COMMENT ON COLUMN iam.department_permission.granted_by IS '执行授予操作的用户主键。';
COMMENT ON TABLE iam.user_permission IS '用户直接允许或拒绝权限；直接拒绝优先于除超级管理员外的全部来源。';
COMMENT ON COLUMN iam.user_permission.user_id IS '直接授权的用户主键。';
COMMENT ON COLUMN iam.user_permission.resource_id IS '直接授权或拒绝的资源主键。';
COMMENT ON COLUMN iam.user_permission.permission_effect IS '直接授权效果：allow允许或deny拒绝。';
COMMENT ON COLUMN iam.user_permission.granted_at IS '直接授权更新时间，带时区。';
COMMENT ON COLUMN iam.user_permission.granted_by IS '执行直接授权操作的用户主键。';
COMMENT ON TABLE iam.user_session IS '服务端登录会话；浏览器Cookie仅保存随机原始令牌，数据库只保存SHA-256令牌摘要。';
COMMENT ON COLUMN iam.user_session.session_token_hash IS '随机会话令牌的SHA-256十六进制摘要，不可用于还原Cookie。';
COMMENT ON COLUMN iam.user_session.csrf_token_hash IS 'CSRF随机令牌的SHA-256十六进制摘要。';
COMMENT ON COLUMN iam.user_session.user_id IS '会话所属用户主键。';
COMMENT ON COLUMN iam.user_session.user_session_version IS '创建或刷新会话时的用户会话版本。';
COMMENT ON COLUMN iam.user_session.ip_address IS '创建会话的客户端IP地址。';
COMMENT ON COLUMN iam.user_session.user_agent IS '创建会话的浏览器User-Agent，最多500字符。';
COMMENT ON COLUMN iam.user_session.created_at IS '会话创建时间，带时区。';
COMMENT ON COLUMN iam.user_session.last_seen_at IS '会话最后活动时间，带时区。';
COMMENT ON COLUMN iam.user_session.idle_expires_at IS '会话无操作过期时间，带时区。';
COMMENT ON COLUMN iam.user_session.absolute_expires_at IS '会话绝对过期时间，带时区。';
COMMENT ON COLUMN iam.user_session.revoked_at IS '会话主动注销或失效时间；NULL表示未撤销。';
COMMENT ON TABLE iam.login_attempt IS '登录成功和失败尝试记录，用于失败限制与安全审计。';
COMMENT ON COLUMN iam.login_attempt.login_attempt_id IS '登录尝试内部自增主键。';
COMMENT ON COLUMN iam.login_attempt.username IS '尝试登录的规范化用户名。';
COMMENT ON COLUMN iam.login_attempt.ip_address IS '登录尝试来源IP地址。';
COMMENT ON COLUMN iam.login_attempt.is_success IS '本次登录是否成功。';
COMMENT ON COLUMN iam.login_attempt.failure_reason IS '失败原因编码；成功时为NULL。';
COMMENT ON COLUMN iam.login_attempt.attempted_at IS '登录尝试时间，带时区。';
COMMENT ON TABLE iam.audit_log IS '认证、用户、组织、权限、看板和系统管理统一审计日志。';
COMMENT ON COLUMN iam.audit_log.audit_log_id IS '审计日志内部自增主键。';
COMMENT ON COLUMN iam.audit_log.user_id IS '操作用户主键；匿名登录失败可为NULL。';
COMMENT ON COLUMN iam.audit_log.username IS '操作时用户名快照，避免用户变更影响历史。';
COMMENT ON COLUMN iam.audit_log.action_code IS '操作类型稳定编码。';
COMMENT ON COLUMN iam.audit_log.target_type IS '操作对象类型。';
COMMENT ON COLUMN iam.audit_log.target_id IS '操作对象业务主键或编码文本。';
COMMENT ON COLUMN iam.audit_log.change_before IS '变更前非敏感字段JSON快照；禁止保存密码和令牌。';
COMMENT ON COLUMN iam.audit_log.change_after IS '变更后非敏感字段JSON快照；禁止保存密码和令牌。';
COMMENT ON COLUMN iam.audit_log.ip_address IS '操作来源IP地址。';
COMMENT ON COLUMN iam.audit_log.user_agent IS '操作浏览器User-Agent，最多500字符。';
COMMENT ON COLUMN iam.audit_log.created_at IS '审计日志创建时间，带时区。';
