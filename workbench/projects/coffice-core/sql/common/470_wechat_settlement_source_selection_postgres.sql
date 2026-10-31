-- 扩展既有逐日采信，不修改ODS事实或财务公式。
DO $migration$
DECLARE item RECORD;
BEGIN
    FOR item IN
        SELECT c.conname FROM pg_constraint c
        WHERE c.conrelid='common.ingest_source_day_selection'::regclass AND c.contype='c'
          AND (c.conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid AND attname='platform_code')]
            OR c.conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid AND attname='target_table')])
          AND pg_get_constraintdef(c.oid) NOT LIKE '%wechat_channels%'
    LOOP
        EXECUTE format('ALTER TABLE common.ingest_source_day_selection DROP CONSTRAINT %I',item.conname);
    END LOOP;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='common.ingest_source_day_selection'::regclass
        AND conname='ingest_source_day_selection_platform_code_check') THEN
        ALTER TABLE common.ingest_source_day_selection ADD CONSTRAINT ingest_source_day_selection_platform_code_check
            CHECK(platform_code IN ('douyin','jd','wechat_channels'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='common.ingest_source_day_selection'::regclass
        AND conname='ingest_source_day_selection_target_table_check') THEN
        ALTER TABLE common.ingest_source_day_selection ADD CONSTRAINT ingest_source_day_selection_target_table_check
            CHECK(target_table IN ('ods_douyin_settlement_raw','ods_douyin_fund_raw',
                'ods_jd_settlement_raw','ods_jd_fund_raw','ods_wechat_channels_settlement_raw'));
    END IF;
END $migration$;
COMMENT ON COLUMN common.ingest_source_day_selection.platform_code IS '标准平台编码，douyin抖音、jd京东、wechat_channels视频号';

CREATE OR REPLACE VIEW common.v_selected_wechat_channels_settlement_raw AS
SELECT r.* FROM ods.ods_wechat_channels_settlement_raw r
LEFT JOIN common.v_ingest_batch_shop_context c ON c.batch_id=r.batch_id
LEFT JOIN common.v_ingest_source_day_selection s
  ON s.shop_identity_key=c.shop_identity_key AND s.target_table='ods_wechat_channels_settlement_raw'
 AND s.stat_date=NULLIF(NULLIF(BTRIM(r."记账时间"),''),'-')::timestamp::date
WHERE s.selection_id IS NULL OR r.batch_id=ANY(s.batch_ids);
COMMENT ON VIEW common.v_selected_wechat_channels_settlement_raw IS '视频号按标准店铺、报表和记账日应用冻结采信；未裁决日保留候选，平台流水号防重在有效来源层完成；原始ODS不变';
