CREATE SCHEMA IF NOT EXISTS common;
CREATE TABLE IF NOT EXISTS common.ingest_source_day_selection (
    selection_id BIGSERIAL PRIMARY KEY,
    platform_code TEXT NOT NULL CHECK (platform_code IN ('douyin','jd','wechat_channels')),
    shop_identity_key TEXT NOT NULL,
    target_table TEXT NOT NULL CHECK (target_table IN ('ods_douyin_settlement_raw','ods_douyin_fund_raw','ods_jd_settlement_raw','ods_jd_fund_raw','ods_wechat_channels_settlement_raw')),
    stat_date DATE NOT NULL,
    batch_ids BIGINT[] NOT NULL,
    ingest_run_id UUID NOT NULL,
    selection_mode TEXT NOT NULL CHECK (selection_mode IN ('fill_gaps','replace_range')),
    evidence JSONB NOT NULL,
    operator TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(ingest_run_id,shop_identity_key,target_table,stat_date)
);
COMMENT ON TABLE common.ingest_source_day_selection IS '文件采信的逐日追加记录；ODS不变；同店铺报表日期取最新决策，空批次数组表示人工确认的零交易日';
COMMENT ON COLUMN common.ingest_source_day_selection.selection_id IS '递增采信版本；刷新上下文冻结此上限；写入前持有全局采信事务锁以保证提交顺序';
COMMENT ON COLUMN common.ingest_source_day_selection.platform_code IS '标准平台编码，douyin抖音、jd京东、wechat_channels视频号';
COMMENT ON COLUMN common.ingest_source_day_selection.shop_identity_key IS 'DIM校验的标准平台店铺身份，来源批次上下文；不维护公司映射';
COMMENT ON COLUMN common.ingest_source_day_selection.target_table IS '独立ODS报表账户的表名，资金与结算分别选择';
COMMENT ON COLUMN common.ingest_source_day_selection.stat_date IS '来源字段确定的业务日期，单位日；包括明确确认的零交易日';
COMMENT ON COLUMN common.ingest_source_day_selection.batch_ids IS '当日被采信的完整成功ODS批次ID数组；空数组表示确认用零交易替换旧来源';
COMMENT ON COLUMN common.ingest_source_day_selection.ingest_run_id IS '作出此决定的导入会话UUID，供追溯及幂等，不改写原始批次';
COMMENT ON COLUMN common.ingest_source_day_selection.selection_mode IS 'fill_gaps仅补缺保留既有版本；replace_range人工确认指定范围以本次文件为准';
COMMENT ON COLUMN common.ingest_source_day_selection.evidence IS '完整查询区间、文件SHA256、空日确认、原因与预检摘要，不包含凭据';
COMMENT ON COLUMN common.ingest_source_day_selection.operator IS '执行采信决定的已认证操作人或自动化身份';
COMMENT ON COLUMN common.ingest_source_day_selection.created_at IS '采信决定写入时间，带时区';
CREATE INDEX IF NOT EXISTS ix_ingest_source_day_choice ON common.ingest_source_day_selection(shop_identity_key,target_table,stat_date,selection_id DESC);

CREATE OR REPLACE VIEW common.v_ingest_source_day_selection AS
SELECT DISTINCT ON(shop_identity_key,target_table,stat_date) *
FROM common.ingest_source_day_selection
WHERE selection_id <= COALESCE(NULLIF(current_setting('mock_coffice.source_selection_cutoff',TRUE),''),'9223372036854775807')::bigint
ORDER BY shop_identity_key,target_table,stat_date,selection_id DESC;
COMMENT ON VIEW common.v_ingest_source_day_selection IS '每个店铺报表业务日的最新采信决定；ETL通过事务设置冻结采信版本';

DO $selection$
DECLARE item RECORD;
BEGIN
    FOR item IN SELECT * FROM (VALUES
        ('douyin','ods_douyin_fund_raw','动账时间'),
        ('jd','ods_jd_fund_raw','入账时间'),
        ('jd','ods_jd_settlement_raw','账单日期'),
        ('wechat_channels','ods_wechat_channels_settlement_raw','记账时间')
    ) v(platform_code,raw_table,date_column)
    LOOP
        IF to_regclass('ods.'||item.raw_table) IS NULL THEN CONTINUE; END IF;
        EXECUTE format('CREATE OR REPLACE VIEW common.%I AS
            SELECT r.* FROM ods.%I r
            LEFT JOIN common.v_ingest_batch_shop_context c ON c.batch_id=r.batch_id
            LEFT JOIN common.v_ingest_source_day_selection s
              ON s.shop_identity_key=c.shop_identity_key AND s.target_table=%L
             AND s.stat_date=NULLIF(NULLIF(BTRIM(r.%I),''''),''-'')::timestamp::date
            WHERE s.selection_id IS NULL OR r.batch_id=ANY(s.batch_ids)',
            'v_selected_'||replace(item.raw_table,'ods_',''),item.raw_table,item.raw_table,item.date_column);
        EXECUTE format('COMMENT ON VIEW common.%I IS %L',
            'v_selected_'||replace(item.raw_table,'ods_',''),
            '保留全部原始字段和未映射批次；已裁决业务日仅读取被采信批次；未裁决日期沿用既有业务身份防重');
    END LOOP;
END $selection$;
