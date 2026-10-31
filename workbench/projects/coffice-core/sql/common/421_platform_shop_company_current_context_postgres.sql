-- 版本化DIM允许预设未来映射；当前导入上下文必须按当前日期选中实际生效版本。
CREATE OR REPLACE VIEW common.v_ingest_batch_shop_context AS
SELECT
    log.batch_id,
    log.platform_code,
    log.platform_name,
    log.shop_code,
    log.shop_name,
    log.shop_identity_key,
    dim.company_code,
    dim.company_name,
    log.data_domain,
    log.target_table,
    log.source_file_name,
    log.shop_mapping_status,
    log.shop_mapping_source,
    log.ingest_status,
    log.updated_at
FROM ods.ods_file_ingest_log log
LEFT JOIN dim.dim_platform_shop_company dim
    ON dim.shop_identity_key = log.shop_identity_key
   AND dim.is_active
   AND CURRENT_DATE >= dim.valid_from
   AND (dim.valid_to IS NULL OR CURRENT_DATE <= dim.valid_to);

COMMENT ON VIEW common.v_ingest_batch_shop_context IS '统一导入批次店铺上下文，按当前日期关联有效店铺公司版本，供各指标DWD通过batch_id获取已确认的平台、店铺和公司映射。';
COMMENT ON COLUMN dim.dim_platform_shop_company.platform_code IS '平台业务编码；后台允许维护自定义编码，但指标加工仍需对应平台ETL支持。';
COMMENT ON COLUMN dim.dim_platform_shop_company.platform_name IS '平台展示名称；自定义平台由后台显式维护。';
COMMENT ON COLUMN dim.dim_platform_shop_company.shop_identity_key IS '稳定店铺身份键，由规范化平台编码和店铺编码生成，不包含公司或店铺名称。';
