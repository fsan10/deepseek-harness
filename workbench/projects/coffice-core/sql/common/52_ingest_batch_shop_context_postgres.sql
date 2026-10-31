CREATE SCHEMA IF NOT EXISTS common;

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
COMMENT ON COLUMN common.v_ingest_batch_shop_context.batch_id IS 'ODS文件导入批次ID。';
COMMENT ON COLUMN common.v_ingest_batch_shop_context.platform_code IS '导入批次标准平台编码。';
COMMENT ON COLUMN common.v_ingest_batch_shop_context.platform_name IS '导入批次标准平台名称。';
COMMENT ON COLUMN common.v_ingest_batch_shop_context.shop_code IS '导入批次经DIM确认的标准店铺编码。';
COMMENT ON COLUMN common.v_ingest_batch_shop_context.shop_name IS '导入批次经DIM确认的标准店铺名称。';
COMMENT ON COLUMN common.v_ingest_batch_shop_context.shop_identity_key IS '由平台编码和店铺编码生成的稳定店铺身份键。';
COMMENT ON COLUMN common.v_ingest_batch_shop_context.company_code IS '当前有效店铺公司关系中的公司稳定编码，仅用于映射审计。';
COMMENT ON COLUMN common.v_ingest_batch_shop_context.company_name IS '当前有效店铺公司关系中的公司名称，仅用于映射审计。';
COMMENT ON COLUMN common.v_ingest_batch_shop_context.data_domain IS '导入批次数据域。';
COMMENT ON COLUMN common.v_ingest_batch_shop_context.target_table IS '导入批次目标ODS表名。';
COMMENT ON COLUMN common.v_ingest_batch_shop_context.source_file_name IS '导入批次源文件名。';
COMMENT ON COLUMN common.v_ingest_batch_shop_context.shop_mapping_status IS '导入批次店铺映射状态。';
COMMENT ON COLUMN common.v_ingest_batch_shop_context.shop_mapping_source IS '导入批次店铺映射来源。';
COMMENT ON COLUMN common.v_ingest_batch_shop_context.ingest_status IS '文件导入执行状态。';
COMMENT ON COLUMN common.v_ingest_batch_shop_context.updated_at IS '导入日志最后更新时间。';
