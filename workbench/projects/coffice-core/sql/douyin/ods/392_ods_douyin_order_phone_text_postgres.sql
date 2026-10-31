-- 重启时不重复执行同类型ALTER，避免与直接投影ODS的来源视图产生依赖冲突。
DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='ods' AND table_name='ods_douyin_order_raw'
          AND column_name='收件人手机号' AND data_type<>'text'
    ) THEN
        ALTER TABLE ods.ods_douyin_order_raw ALTER COLUMN "收件人手机号" TYPE TEXT;
    END IF;
END $$;

COMMENT ON COLUMN ods.ods_douyin_order_raw."收件人手机号" IS
    '来源文件字段“收件人手机号”，入ODS前统一掩码为***，不保存原始手机号信息。';
