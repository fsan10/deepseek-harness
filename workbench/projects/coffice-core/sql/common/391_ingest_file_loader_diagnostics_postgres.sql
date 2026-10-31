-- 为每个上传文件保留 Loader 的退出码和标准输出摘要。
-- 该迁移只增加可空审计字段，不改写已有 ODS 或导入记录。
ALTER TABLE ops.ingest_file_task
    ADD COLUMN IF NOT EXISTS loader_exit_code INTEGER,
    ADD COLUMN IF NOT EXISTS output_summary TEXT;

COMMENT ON COLUMN ops.ingest_file_task.loader_exit_code IS
    'ODS Loader 进程退出码；成功通常为0，未执行或接口阶段失败时为空。';
COMMENT ON COLUMN ops.ingest_file_task.output_summary IS
    'ODS Loader 标准输出摘要，包含导入批次、行数和校验信息；超长内容由服务截断。';
