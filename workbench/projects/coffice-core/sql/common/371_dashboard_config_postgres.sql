CREATE SCHEMA IF NOT EXISTS config;

CREATE TABLE IF NOT EXISTS config.dashboard (
    dashboard_id BIGSERIAL PRIMARY KEY,
    dashboard_code VARCHAR(64) NOT NULL,
    dashboard_name VARCHAR(120) NOT NULL,
    dashboard_description VARCHAR(500) NOT NULL DEFAULT '',
    share_url VARCHAR(500) NOT NULL,
    icon_name VARCHAR(64) NOT NULL DEFAULT 'dashboard',
    display_order INTEGER NOT NULL DEFAULT 0,
    allow_fullscreen BOOLEAN NOT NULL DEFAULT TRUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    permission_resource_id BIGINT NOT NULL REFERENCES iam.permission_resource(resource_id) ON DELETE RESTRICT,
    created_by BIGINT REFERENCES iam.user_account(user_id) ON DELETE SET NULL,
    updated_by BIGINT REFERENCES iam.user_account(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT uq_config_dashboard_code UNIQUE (dashboard_code),
    CONSTRAINT uq_config_dashboard_permission UNIQUE (permission_resource_id),
    CONSTRAINT ck_config_dashboard_code CHECK (dashboard_code ~ '^[a-z][a-z0-9_]{1,63}$'),
    CONSTRAINT ck_config_dashboard_name CHECK (BTRIM(dashboard_name) <> ''),
    CONSTRAINT ck_config_dashboard_order CHECK (display_order >= 0),
    CONSTRAINT ck_config_dashboard_share_url CHECK (
        share_url ~ '^https?://192[.]168[.]77[.]111:8100/#/de-link/[A-Za-z0-9_-]+$'
    )
);

CREATE INDEX IF NOT EXISTS idx_config_dashboard_navigation
    ON config.dashboard(is_active, display_order, dashboard_id)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_config_dashboard_name
    ON config.dashboard(dashboard_name)
    WHERE deleted_at IS NULL;

COMMENT ON SCHEMA config IS '经营配置中心自身的可维护业务配置对象，不包含ODS原始数据。';
COMMENT ON TABLE config.dashboard IS 'DataEase公共分享看板配置；后台权限仅控制经营配置中心内的可见与进入。';
COMMENT ON COLUMN config.dashboard.dashboard_id IS '看板内部自增主键。';
COMMENT ON COLUMN config.dashboard.dashboard_code IS '系统自动生成的全局唯一英文snake_case编码，同时作为动态权限资源和内部路由稳定标识；创建后不可修改。';
COMMENT ON COLUMN config.dashboard.dashboard_name IS '看板在导航和页面顶部显示的可编辑名称。';
COMMENT ON COLUMN config.dashboard.dashboard_description IS '看板用途和口径边界说明。';
COMMENT ON COLUMN config.dashboard.share_url IS '允许嵌入的DataEase公共分享链接，仅限192.168.77.111:8100的/de-link地址。';
COMMENT ON COLUMN config.dashboard.icon_name IS '导航展示图标名称；由前端限定图标集合渲染。';
COMMENT ON COLUMN config.dashboard.display_order IS '看板在经营仪表盘分组内的排序，数值越小越靠前。';
COMMENT ON COLUMN config.dashboard.allow_fullscreen IS '是否允许用户在经营配置中心内进入看板全屏模式。';
COMMENT ON COLUMN config.dashboard.is_active IS '看板是否启用；停用后立即从普通用户导航移除。';
COMMENT ON COLUMN config.dashboard.permission_resource_id IS '对应iam.permission_resource动态看板权限资源主键。';
COMMENT ON COLUMN config.dashboard.created_by IS '创建看板配置的用户主键。';
COMMENT ON COLUMN config.dashboard.updated_by IS '最后修改看板配置的用户主键。';
COMMENT ON COLUMN config.dashboard.created_at IS '看板配置创建时间，带时区。';
COMMENT ON COLUMN config.dashboard.updated_at IS '看板配置最后更新时间，带时区。';
COMMENT ON COLUMN config.dashboard.deleted_at IS '看板软删除时间；NULL表示未删除。';
