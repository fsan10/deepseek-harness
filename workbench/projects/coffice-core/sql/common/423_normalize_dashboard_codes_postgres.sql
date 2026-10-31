-- 看板编码统一为系统生成格式，并同步修复动态权限资源的编码和路由。
-- 该迁移同时负责默认DataEase看板的幂等种子，避免旧的人工编码被重新写回。
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
DECLARE
    dashboard_row RECORD;
    default_row RECORD;
    candidate_code TEXT;
    permission_code TEXT;
    new_resource_id BIGINT;
    has_dashboard_slug BOOLEAN;
    has_renderer BOOLEAN;
    has_category_code BOOLEAN;
    has_default_filters BOOLEAN;
    has_navigation_visible BOOLEAN;
    insert_columns TEXT;
    insert_values TEXT;
BEGIN
    -- 先为全部历史看板生成不可读且不可修改的系统编码；包括已软删除记录，
    -- 防止唯一约束下未来重新使用历史编码。
    FOR dashboard_row IN
        SELECT d.dashboard_id, d.dashboard_code, d.permission_resource_id
        FROM config.dashboard d
        WHERE d.dashboard_code !~ '^dashboard_[0-9a-f]{32}$'
        ORDER BY d.dashboard_id
        FOR UPDATE
    LOOP
        LOOP
            candidate_code := 'dashboard_' || replace(gen_random_uuid()::text, '-', '');
            permission_code := 'dashboard.view.' || candidate_code;
            EXIT WHEN NOT EXISTS (
                SELECT 1 FROM config.dashboard d WHERE d.dashboard_code = candidate_code
            ) AND NOT EXISTS (
                SELECT 1 FROM iam.permission_resource p WHERE p.resource_code = permission_code
            );
        END LOOP;

        UPDATE iam.permission_resource
        SET resource_code = permission_code,
            route_path = '/dashboards/?code=' || candidate_code,
            updated_at = NOW()
        WHERE resource_id = dashboard_row.permission_resource_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION '看板 % 缺少对应的动态权限资源', dashboard_row.dashboard_id;
        END IF;

        UPDATE config.dashboard
        SET dashboard_code = candidate_code,
            updated_at = NOW()
        WHERE dashboard_id = dashboard_row.dashboard_id;
    END LOOP;

    -- 已符合格式的历史记录也统一校正权限资源编码和内部路由。
    UPDATE iam.permission_resource resource
    SET resource_code = 'dashboard.view.' || dashboard.dashboard_code,
        route_path = '/dashboards/?code=' || dashboard.dashboard_code,
        updated_at = NOW()
    FROM config.dashboard dashboard
    WHERE dashboard.permission_resource_id = resource.resource_id
      AND (
          resource.resource_code IS DISTINCT FROM 'dashboard.view.' || dashboard.dashboard_code
          OR resource.route_path IS DISTINCT FROM '/dashboards/?code=' || dashboard.dashboard_code
      );

    SELECT EXISTS(
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'config' AND table_name = 'dashboard' AND column_name = 'dashboard_slug'
    ) INTO has_dashboard_slug;
    SELECT EXISTS(
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'config' AND table_name = 'dashboard' AND column_name = 'renderer'
    ) INTO has_renderer;
    SELECT EXISTS(
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'config' AND table_name = 'dashboard' AND column_name = 'category_code'
    ) INTO has_category_code;
    SELECT EXISTS(
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'config' AND table_name = 'dashboard' AND column_name = 'default_filters'
    ) INTO has_default_filters;
    SELECT EXISTS(
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'config' AND table_name = 'dashboard' AND column_name = 'is_navigation_visible'
    ) INTO has_navigation_visible;

    -- 默认看板以分享链接作为种子身份；已有记录（包括软删除记录）不重复创建。
    FOR default_row IN
        SELECT *
        FROM (VALUES
            ('经营看板一'::TEXT,
             'DataEase公共分享看板；后台权限仅限制经营配置中心内的可见与进入。'::TEXT,
             'http://192.168.77.111:8100/#/de-link/I9O1mwdA'::TEXT, 10),
            ('经营看板二'::TEXT,
             'DataEase公共分享看板；后台权限仅限制经营配置中心内的可见与进入。'::TEXT,
             'http://192.168.77.111:8100/#/de-link/D7Yoez1x'::TEXT, 20)
        ) AS defaults(dashboard_name, dashboard_description, share_url, display_order)
    LOOP
        SELECT d.dashboard_code
        INTO candidate_code
        FROM config.dashboard d
        WHERE d.share_url = default_row.share_url
        ORDER BY d.dashboard_id
        LIMIT 1;
        IF FOUND THEN
            CONTINUE;
        END IF;

        LOOP
            candidate_code := 'dashboard_' || replace(gen_random_uuid()::text, '-', '');
            permission_code := 'dashboard.view.' || candidate_code;
            EXIT WHEN NOT EXISTS (
                SELECT 1 FROM config.dashboard d WHERE d.dashboard_code = candidate_code
            ) AND NOT EXISTS (
                SELECT 1 FROM iam.permission_resource p WHERE p.resource_code = permission_code
            );
        END LOOP;

        SELECT module.resource_id
        INTO new_resource_id
        FROM iam.permission_resource module
        WHERE module.resource_code = 'module.dashboard';
        IF new_resource_id IS NULL THEN
            RAISE EXCEPTION '缺少经营仪表盘权限模块，无法创建默认看板';
        END IF;

        INSERT INTO iam.permission_resource (
            resource_code, resource_name, resource_type, module_code,
            parent_resource_id, route_path, display_order, is_active, updated_at
        ) VALUES (
            permission_code, '查看' || default_row.dashboard_name, 'dashboard', 'dashboard',
            new_resource_id, '/dashboards/?code=' || candidate_code, default_row.display_order, TRUE, NOW()
        ) RETURNING resource_id INTO new_resource_id;

        insert_columns := 'dashboard_code,dashboard_name,dashboard_description,share_url,icon_name,display_order,allow_fullscreen,is_active,permission_resource_id';
        insert_values := format(
            '%L,%L,%L,%L,%L,%s,TRUE,TRUE,%s',
            candidate_code, default_row.dashboard_name, default_row.dashboard_description,
            default_row.share_url, 'dashboard', default_row.display_order, new_resource_id
        );
        IF has_dashboard_slug THEN
            insert_columns := insert_columns || ',dashboard_slug';
            insert_values := insert_values || format(',%L', candidate_code);
        END IF;
        IF has_renderer THEN
            insert_columns := insert_columns || ',renderer';
            insert_values := insert_values || ',''dataease''';
        END IF;
        IF has_category_code THEN
            insert_columns := insert_columns || ',category_code';
            insert_values := insert_values || ',''legacy''';
        END IF;
        IF has_default_filters THEN
            insert_columns := insert_columns || ',default_filters';
            insert_values := insert_values || ',''{}''::jsonb';
        END IF;
        IF has_navigation_visible THEN
            insert_columns := insert_columns || ',is_navigation_visible';
            insert_values := insert_values || ',TRUE';
        END IF;
        EXECUTE format(
            'INSERT INTO config.dashboard (%s) VALUES (%s)',
            insert_columns, insert_values
        );
    END LOOP;
END $$;
