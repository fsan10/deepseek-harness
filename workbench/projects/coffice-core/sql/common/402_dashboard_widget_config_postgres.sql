CREATE SCHEMA IF NOT EXISTS config;

CREATE TABLE IF NOT EXISTS config.dashboard_widget (
    widget_id BIGSERIAL PRIMARY KEY,
    dashboard_id BIGINT NOT NULL REFERENCES config.dashboard(dashboard_id) ON DELETE CASCADE,
    widget_key VARCHAR(128) NOT NULL,
    title VARCHAR(120) NOT NULL,
    widget_type VARCHAR(32) NOT NULL,
    dataset_code VARCHAR(64) NOT NULL,
    metric_code VARCHAR(64) NOT NULL,
    dimension_code VARCHAR(64) NOT NULL DEFAULT 'total',
    query_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    grid_x INTEGER NOT NULL DEFAULT 0,
    grid_y INTEGER NOT NULL DEFAULT 0,
    grid_w INTEGER NOT NULL DEFAULT 3,
    grid_h INTEGER NOT NULL DEFAULT 4,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by BIGINT REFERENCES iam.user_account(user_id) ON DELETE SET NULL,
    updated_by BIGINT REFERENCES iam.user_account(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_config_dashboard_widget_key UNIQUE (dashboard_id, widget_key),
    CONSTRAINT ck_config_dashboard_widget_key CHECK (widget_key ~ '^[a-z][a-z0-9_]{1,63}$'),
    CONSTRAINT ck_config_dashboard_widget_title CHECK (BTRIM(title) <> ''),
    CONSTRAINT ck_config_dashboard_widget_type CHECK (
        widget_type IN (
            'kpi', 'line', 'area', 'bar', 'horizontal_bar', 'stacked_bar',
            'pie', 'donut', 'mixed', 'table', 'text', 'date_filter',
            'company_filter', 'platform_filter', 'shop_filter'
        )
    ),
    CONSTRAINT ck_config_dashboard_widget_grid_x CHECK (grid_x >= 0),
    CONSTRAINT ck_config_dashboard_widget_grid_y CHECK (grid_y >= 0),
    CONSTRAINT ck_config_dashboard_widget_grid_w CHECK (grid_w BETWEEN 2 AND 12),
    CONSTRAINT ck_config_dashboard_widget_grid_h CHECK (grid_h BETWEEN 2 AND 24),
    CONSTRAINT ck_config_dashboard_widget_order CHECK (display_order >= 0)
);

CREATE INDEX IF NOT EXISTS idx_config_dashboard_widget_navigation
    ON config.dashboard_widget (dashboard_id, is_active, display_order, widget_id);

COMMENT ON TABLE config.dashboard_widget IS
    'DataEase看板组件配置；只保存看板布局、指标编码和查询参数，不保存指标事实数据。';
COMMENT ON COLUMN config.dashboard_widget.widget_id IS
    '看板组件内部自增主键。';
COMMENT ON COLUMN config.dashboard_widget.dashboard_id IS
    '所属看板主键；看板删除时组件随之删除。';
COMMENT ON COLUMN config.dashboard_widget.widget_key IS
    '看板内组件稳定编码，用于配置更新和前端定位。';
COMMENT ON COLUMN config.dashboard_widget.title IS
    '组件展示标题。';
COMMENT ON COLUMN config.dashboard_widget.widget_type IS
    '组件类型：KPI、趋势、柱状图、饼图、表格或筛选器等枚举。';
COMMENT ON COLUMN config.dashboard_widget.dataset_code IS
    '组件使用的数据集编码；数据集实际查询对象由看板服务约束。';
COMMENT ON COLUMN config.dashboard_widget.metric_code IS
    '组件展示的指标编码。';
COMMENT ON COLUMN config.dashboard_widget.dimension_code IS
    '组件分组维度编码；total表示总计。';
COMMENT ON COLUMN config.dashboard_widget.query_config IS
    '组件查询和展示参数JSON；不应写入凭据或原始业务事实。';
COMMENT ON COLUMN config.dashboard_widget.grid_x IS
    '组件在看板网格中的横坐标。';
COMMENT ON COLUMN config.dashboard_widget.grid_y IS
    '组件在看板网格中的纵坐标。';
COMMENT ON COLUMN config.dashboard_widget.grid_w IS
    '组件占用的网格宽度，范围2到12。';
COMMENT ON COLUMN config.dashboard_widget.grid_h IS
    '组件占用的网格高度，范围2到24。';
COMMENT ON COLUMN config.dashboard_widget.display_order IS
    '同一看板组件的展示顺序，数值越小越靠前。';
COMMENT ON COLUMN config.dashboard_widget.is_active IS
    '组件是否启用；停用组件不在看板中展示。';
COMMENT ON COLUMN config.dashboard_widget.created_by IS
    '创建组件配置的IAM用户主键。';
COMMENT ON COLUMN config.dashboard_widget.updated_by IS
    '最后修改组件配置的IAM用户主键。';
COMMENT ON COLUMN config.dashboard_widget.created_at IS
    '组件配置创建时间，带时区。';
COMMENT ON COLUMN config.dashboard_widget.updated_at IS
    '组件配置最后更新时间，带时区。';
