ALTER TABLE config.dashboard
    DROP CONSTRAINT IF EXISTS ck_config_dashboard_share_url;

ALTER TABLE config.dashboard
    ADD CONSTRAINT ck_config_dashboard_share_url CHECK (
        share_url ~ '^https?://[^/?#[:space:]]+/#/de-link/[A-Za-z0-9_-]+$'
    );

COMMENT ON CONSTRAINT ck_config_dashboard_share_url ON config.dashboard IS
    '仅校验DataEase公共分享链接格式；允许的服务来源由DATAEASE_PUBLIC_ORIGINS在应用层白名单校验。';
