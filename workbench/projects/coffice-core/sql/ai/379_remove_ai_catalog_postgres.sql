-- 删除可配置的数据目录；AI 运行时只受控探查启用数据源中实际可读的 ads、dim 对象。
-- 仅修改 ai schema 和对应 IAM 资源，不触碰任何 ODS 对象或数据。

DROP TABLE IF EXISTS ai.catalog_column;
DROP TABLE IF EXISTS ai.data_catalog;

ALTER TABLE IF EXISTS ai.data_source
    DROP COLUMN IF EXISTS allowed_schemas;

DELETE FROM iam.permission_resource
WHERE resource_code = 'ai.catalog.manage';
