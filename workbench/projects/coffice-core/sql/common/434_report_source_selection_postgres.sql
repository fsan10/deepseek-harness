-- ODS保留全部原始记录；这里只选择报表版本，不执行指标状态/金额筛选。
ALTER TABLE ods.ods_file_ingest_log
    ADD COLUMN IF NOT EXISTS report_period_start DATE,
    ADD COLUMN IF NOT EXISTS report_period_end DATE;
COMMENT ON COLUMN ods.ods_file_ingest_log.report_period_start IS '原始报表声明的完整查询起始自然日；仅经明细范围核验后登记，未知为空。';
COMMENT ON COLUMN ods.ods_file_ingest_log.report_period_end IS '原始报表声明的完整查询结束自然日；用于选择覆盖来源，不按金额或订单号去重流水。';

CREATE OR REPLACE FUNCTION common.report_snapshot_date(file_name TEXT)
RETURNS DATE LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE token TEXT;
BEGIN
    token := (REGEXP_MATCH(file_name, '(?:^|_)([0-9]{8}|[0-9]{6})_'))[1];
    IF LENGTH(token)=8 THEN
        RETURN MAKE_DATE(SUBSTRING(token,1,4)::int,SUBSTRING(token,5,2)::int,SUBSTRING(token,7,2)::int);
    ELSIF LENGTH(token)=6 THEN
        RETURN (MAKE_DATE(SUBSTRING(token,1,4)::int,SUBSTRING(token,5,2)::int,1) + INTERVAL '1 month - 1 day')::date;
    END IF;
    RETURN NULL;
EXCEPTION WHEN datetime_field_overflow OR invalid_datetime_format THEN RETURN NULL;
END $$;
COMMENT ON FUNCTION common.report_snapshot_date(TEXT) IS '从标准报表名解析业务快照日期；YYYYMM取月末。无法识别时返回空，由调用方使用采集时间。店铺身份始终来自批次上下文。';


DO $$ BEGIN
IF TO_REGCLASS('ods.ods_douyin_order_raw') IS NOT NULL THEN
    EXECUTE $report_view$CREATE OR REPLACE VIEW common.v_current_douyin_order_raw AS
WITH batches AS MATERIALIZED (
    SELECT c.batch_id,c.shop_identity_key,
           COALESCE(common.report_snapshot_date(l.source_file_name),
                    (l.started_at AT TIME ZONE 'Asia/Shanghai')::date) snapshot_date,
           COALESCE(l.ingest_run_id::text,l.batch_id::text) snapshot_key,
           MIN(l.started_at) OVER (PARTITION BY COALESCE(l.ingest_run_id::text,l.batch_id::text)) snapshot_at
    FROM common.v_ingest_batch_shop_context c
    JOIN ods.ods_file_ingest_log l ON l.batch_id=c.batch_id
    WHERE c.platform_code='douyin' AND c.target_table='ods_douyin_order_raw'
      AND c.shop_mapping_status='mapped' AND c.ingest_status='success'
), reports AS (
    SELECT r.id,b.shop_identity_key,BTRIM(r."主订单编号", E' \t\r\n') order_no,
           b.snapshot_date,b.snapshot_key,b.snapshot_at
    FROM ods.ods_douyin_order_raw r JOIN batches b ON b.batch_id=r.batch_id
), latest AS (
    SELECT DISTINCT ON (shop_identity_key,order_no)
           shop_identity_key,order_no,snapshot_date,snapshot_key
    FROM reports
    ORDER BY shop_identity_key,order_no,snapshot_date DESC,snapshot_at DESC,snapshot_key DESC
), chosen AS (
    SELECT reports.* FROM reports JOIN latest ON reports.shop_identity_key=latest.shop_identity_key
      AND COALESCE(reports.order_no,'')=COALESCE(latest.order_no,'')
      AND reports.snapshot_date=latest.snapshot_date AND reports.snapshot_key=latest.snapshot_key
)
SELECT r.*, BTRIM(r."子订单编号") AS business_detail_key
FROM ods.ods_douyin_order_raw r JOIN chosen ON chosen.id=r.id;
$report_view$;
COMMENT ON VIEW common.v_current_douyin_order_raw IS '直接投影douyin订单ODS的最新整单快照；同一次提交的分片共同保留商品明细，旧版本不参与指标，不改变任何状态筛选条件。';
END IF;
END $$;


DO $$ BEGIN
IF TO_REGCLASS('ods.ods_tmall_order_raw') IS NOT NULL THEN
    EXECUTE $report_view$CREATE OR REPLACE VIEW common.v_current_tmall_order_raw AS
WITH batches AS MATERIALIZED (
    SELECT c.batch_id,c.shop_identity_key,
           COALESCE(common.report_snapshot_date(l.source_file_name),
                    (l.started_at AT TIME ZONE 'Asia/Shanghai')::date) snapshot_date,
           COALESCE(l.ingest_run_id::text,l.batch_id::text) snapshot_key,
           MIN(l.started_at) OVER (PARTITION BY COALESCE(l.ingest_run_id::text,l.batch_id::text)) snapshot_at
    FROM common.v_ingest_batch_shop_context c
    JOIN ods.ods_file_ingest_log l ON l.batch_id=c.batch_id
    WHERE c.platform_code='tmall' AND c.target_table='ods_tmall_order_raw'
      AND c.shop_mapping_status='mapped' AND c.ingest_status='success'
), reports AS (
    SELECT r.id,b.shop_identity_key,BTRIM(r."主订单编号", E' \t\r\n') order_no,
           b.snapshot_date,b.snapshot_key,b.snapshot_at
    FROM ods.ods_tmall_order_raw r JOIN batches b ON b.batch_id=r.batch_id
), latest AS (
    SELECT DISTINCT ON (shop_identity_key,order_no)
           shop_identity_key,order_no,snapshot_date,snapshot_key
    FROM reports
    ORDER BY shop_identity_key,order_no,snapshot_date DESC,snapshot_at DESC,snapshot_key DESC
), chosen AS (
    SELECT reports.* FROM reports JOIN latest ON reports.shop_identity_key=latest.shop_identity_key
      AND COALESCE(reports.order_no,'')=COALESCE(latest.order_no,'')
      AND reports.snapshot_date=latest.snapshot_date AND reports.snapshot_key=latest.snapshot_key
)
SELECT r.*, BTRIM(r."子订单编号") AS business_detail_key
FROM ods.ods_tmall_order_raw r JOIN chosen ON chosen.id=r.id;
$report_view$;
COMMENT ON VIEW common.v_current_tmall_order_raw IS '直接投影tmall订单ODS的最新整单快照；同一次提交的分片共同保留商品明细，旧版本不参与指标，不改变任何状态筛选条件。';
END IF;
END $$;


DO $$ BEGIN
IF TO_REGCLASS('ods.ods_jd_order_raw') IS NOT NULL THEN
    EXECUTE $report_view$CREATE OR REPLACE VIEW common.v_current_jd_order_raw AS
WITH batches AS MATERIALIZED (
    SELECT c.batch_id,c.shop_identity_key,
           COALESCE(common.report_snapshot_date(l.source_file_name),
                    (l.started_at AT TIME ZONE 'Asia/Shanghai')::date) snapshot_date,
           COALESCE(l.ingest_run_id::text,l.batch_id::text) snapshot_key,
           MIN(l.started_at) OVER (PARTITION BY COALESCE(l.ingest_run_id::text,l.batch_id::text)) snapshot_at
    FROM common.v_ingest_batch_shop_context c
    JOIN ods.ods_file_ingest_log l ON l.batch_id=c.batch_id
    WHERE c.platform_code='jd' AND c.target_table='ods_jd_order_raw'
      AND c.shop_mapping_status='mapped' AND c.ingest_status='success'
), reports AS (
    SELECT r.id,b.shop_identity_key,BTRIM(r."订单号", E' \t\r\n') order_no,
           b.snapshot_date,b.snapshot_key,b.snapshot_at
    FROM ods.ods_jd_order_raw r JOIN batches b ON b.batch_id=r.batch_id
), latest AS (
    SELECT DISTINCT ON (shop_identity_key,order_no)
           shop_identity_key,order_no,snapshot_date,snapshot_key
    FROM reports
    ORDER BY shop_identity_key,order_no,snapshot_date DESC,snapshot_at DESC,snapshot_key DESC
), chosen AS (
    SELECT reports.* FROM reports JOIN latest ON reports.shop_identity_key=latest.shop_identity_key
      AND COALESCE(reports.order_no,'')=COALESCE(latest.order_no,'')
      AND reports.snapshot_date=latest.snapshot_date AND reports.snapshot_key=latest.snapshot_key
)
SELECT r.*, BTRIM(r."订单号", E' \t\r\n') || '#' || MD5(CONCAT_WS(E'\x1f',BTRIM(COALESCE(r."商品ID",'')),BTRIM(COALESCE(r."商家SKUID",'')))) || '#' ||
        ROW_NUMBER() OVER (PARTITION BY chosen.shop_identity_key,BTRIM(r."订单号", E' \t\r\n'),CONCAT_WS(E'\x1f',BTRIM(COALESCE(r."商品ID",'')),BTRIM(COALESCE(r."商家SKUID",'')))
                           ORDER BY r.source_file_name,r.source_row_no,r.id)::text AS business_detail_key
FROM ods.ods_jd_order_raw r JOIN chosen ON chosen.id=r.id;
$report_view$;
COMMENT ON VIEW common.v_current_jd_order_raw IS '直接投影jd订单ODS的最新整单快照；同一次提交的分片共同保留商品明细，旧版本不参与指标，不改变任何状态筛选条件。';
END IF;
END $$;


DO $$ BEGIN
IF TO_REGCLASS('ods.ods_ks_order_raw') IS NOT NULL THEN
    EXECUTE $report_view$CREATE OR REPLACE VIEW common.v_current_ks_order_raw AS
WITH batches AS MATERIALIZED (
    SELECT c.batch_id,c.shop_identity_key,
           COALESCE(common.report_snapshot_date(l.source_file_name),
                    (l.started_at AT TIME ZONE 'Asia/Shanghai')::date) snapshot_date,
           COALESCE(l.ingest_run_id::text,l.batch_id::text) snapshot_key,
           MIN(l.started_at) OVER (PARTITION BY COALESCE(l.ingest_run_id::text,l.batch_id::text)) snapshot_at
    FROM common.v_ingest_batch_shop_context c
    JOIN ods.ods_file_ingest_log l ON l.batch_id=c.batch_id
    WHERE c.platform_code='ks' AND c.target_table='ods_ks_order_raw'
      AND c.shop_mapping_status='mapped' AND c.ingest_status='success'
), reports AS (
    SELECT r.id,b.shop_identity_key,BTRIM(r."订单号", E' \t\r\n') order_no,
           b.snapshot_date,b.snapshot_key,b.snapshot_at
    FROM ods.ods_ks_order_raw r JOIN batches b ON b.batch_id=r.batch_id
), latest AS (
    SELECT DISTINCT ON (shop_identity_key,order_no)
           shop_identity_key,order_no,snapshot_date,snapshot_key
    FROM reports
    ORDER BY shop_identity_key,order_no,snapshot_date DESC,snapshot_at DESC,snapshot_key DESC
), chosen AS (
    SELECT reports.* FROM reports JOIN latest ON reports.shop_identity_key=latest.shop_identity_key
      AND COALESCE(reports.order_no,'')=COALESCE(latest.order_no,'')
      AND reports.snapshot_date=latest.snapshot_date AND reports.snapshot_key=latest.snapshot_key
)
SELECT r.*, BTRIM(r."订单号", E' \t\r\n') || '#' || MD5(CONCAT_WS(E'\x1f',BTRIM(COALESCE(r."商品ID",'')),BTRIM(COALESCE(r."SKU编码",'')),BTRIM(COALESCE(r."商品规格",'')))) || '#' ||
        ROW_NUMBER() OVER (PARTITION BY chosen.shop_identity_key,BTRIM(r."订单号", E' \t\r\n'),CONCAT_WS(E'\x1f',BTRIM(COALESCE(r."商品ID",'')),BTRIM(COALESCE(r."SKU编码",'')),BTRIM(COALESCE(r."商品规格",'')))
                           ORDER BY r.source_file_name,r.source_row_no,r.id)::text AS business_detail_key
FROM ods.ods_ks_order_raw r JOIN chosen ON chosen.id=r.id;
$report_view$;
COMMENT ON VIEW common.v_current_ks_order_raw IS '直接投影ks订单ODS的最新整单快照；同一次提交的分片共同保留商品明细，旧版本不参与指标，不改变任何状态筛选条件。';
END IF;
END $$;


DO $$ BEGIN
IF TO_REGCLASS('ods.ods_pdd_order_raw') IS NOT NULL THEN
    EXECUTE $report_view$CREATE OR REPLACE VIEW common.v_current_pdd_order_raw AS
WITH batches AS MATERIALIZED (
    SELECT c.batch_id,c.shop_identity_key,
           COALESCE(common.report_snapshot_date(l.source_file_name),
                    (l.started_at AT TIME ZONE 'Asia/Shanghai')::date) snapshot_date,
           COALESCE(l.ingest_run_id::text,l.batch_id::text) snapshot_key,
           MIN(l.started_at) OVER (PARTITION BY COALESCE(l.ingest_run_id::text,l.batch_id::text)) snapshot_at
    FROM common.v_ingest_batch_shop_context c
    JOIN ods.ods_file_ingest_log l ON l.batch_id=c.batch_id
    WHERE c.platform_code='pdd' AND c.target_table='ods_pdd_order_raw'
      AND c.shop_mapping_status='mapped' AND c.ingest_status='success'
), reports AS (
    SELECT r.id,b.shop_identity_key,BTRIM(r."订单号", E' \t\r\n') order_no,
           b.snapshot_date,b.snapshot_key,b.snapshot_at
    FROM ods.ods_pdd_order_raw r JOIN batches b ON b.batch_id=r.batch_id
), latest AS (
    SELECT DISTINCT ON (shop_identity_key,order_no)
           shop_identity_key,order_no,snapshot_date,snapshot_key
    FROM reports
    ORDER BY shop_identity_key,order_no,snapshot_date DESC,snapshot_at DESC,snapshot_key DESC
), chosen AS (
    SELECT reports.* FROM reports JOIN latest ON reports.shop_identity_key=latest.shop_identity_key
      AND COALESCE(reports.order_no,'')=COALESCE(latest.order_no,'')
      AND reports.snapshot_date=latest.snapshot_date AND reports.snapshot_key=latest.snapshot_key
)
SELECT r.*, BTRIM(r."订单号", E' \t\r\n') || '#' || MD5(CONCAT_WS(E'\x1f',BTRIM(COALESCE(r."商品id",'')),BTRIM(COALESCE(r."样式ID",'')),BTRIM(COALESCE(r."商品规格",'')))) || '#' ||
        ROW_NUMBER() OVER (PARTITION BY chosen.shop_identity_key,BTRIM(r."订单号", E' \t\r\n'),CONCAT_WS(E'\x1f',BTRIM(COALESCE(r."商品id",'')),BTRIM(COALESCE(r."样式ID",'')),BTRIM(COALESCE(r."商品规格",'')))
                           ORDER BY r.source_file_name,r.source_row_no,r.id)::text AS business_detail_key
FROM ods.ods_pdd_order_raw r JOIN chosen ON chosen.id=r.id;
$report_view$;
COMMENT ON VIEW common.v_current_pdd_order_raw IS '直接投影pdd订单ODS的最新整单快照；同一次提交的分片共同保留商品明细，旧版本不参与指标，不改变任何状态筛选条件。';
END IF;
END $$;


DO $$ BEGIN
IF TO_REGCLASS('ods.ods_xhs_order_raw') IS NOT NULL THEN
    EXECUTE $report_view$CREATE OR REPLACE VIEW common.v_current_xhs_order_raw AS
WITH batches AS MATERIALIZED (
    SELECT c.batch_id,c.shop_identity_key,
           COALESCE(common.report_snapshot_date(l.source_file_name),
                    (l.started_at AT TIME ZONE 'Asia/Shanghai')::date) snapshot_date,
           COALESCE(l.ingest_run_id::text,l.batch_id::text) snapshot_key,
           MIN(l.started_at) OVER (PARTITION BY COALESCE(l.ingest_run_id::text,l.batch_id::text)) snapshot_at
    FROM common.v_ingest_batch_shop_context c
    JOIN ods.ods_file_ingest_log l ON l.batch_id=c.batch_id
    WHERE c.platform_code='xhs' AND c.target_table='ods_xhs_order_raw'
      AND c.shop_mapping_status='mapped' AND c.ingest_status='success'
), reports AS (
    SELECT r.id,b.shop_identity_key,BTRIM(r."订单号", E' \t\r\n') order_no,
           b.snapshot_date,b.snapshot_key,b.snapshot_at
    FROM ods.ods_xhs_order_raw r JOIN batches b ON b.batch_id=r.batch_id
), latest AS (
    SELECT DISTINCT ON (shop_identity_key,order_no)
           shop_identity_key,order_no,snapshot_date,snapshot_key
    FROM reports
    ORDER BY shop_identity_key,order_no,snapshot_date DESC,snapshot_at DESC,snapshot_key DESC
), chosen AS (
    SELECT reports.* FROM reports JOIN latest ON reports.shop_identity_key=latest.shop_identity_key
      AND COALESCE(reports.order_no,'')=COALESCE(latest.order_no,'')
      AND reports.snapshot_date=latest.snapshot_date AND reports.snapshot_key=latest.snapshot_key
)
SELECT r.*, BTRIM(r."订单号", E' \t\r\n') || '#' || MD5(CONCAT_WS(E'\x1f',BTRIM(COALESCE(r."商品ID",'')),BTRIM(COALESCE(r."规格ID",'')),BTRIM(COALESCE(r."SKU规格",'')))) || '#' ||
        ROW_NUMBER() OVER (PARTITION BY chosen.shop_identity_key,BTRIM(r."订单号", E' \t\r\n'),CONCAT_WS(E'\x1f',BTRIM(COALESCE(r."商品ID",'')),BTRIM(COALESCE(r."规格ID",'')),BTRIM(COALESCE(r."SKU规格",'')))
                           ORDER BY r.source_file_name,r.source_row_no,r.id)::text AS business_detail_key
FROM ods.ods_xhs_order_raw r JOIN chosen ON chosen.id=r.id;
$report_view$;
COMMENT ON VIEW common.v_current_xhs_order_raw IS '直接投影xhs订单ODS的最新整单快照；同一次提交的分片共同保留商品明细，旧版本不参与指标，不改变任何状态筛选条件。';
END IF;
END $$;


DO $$ BEGIN
IF TO_REGCLASS('ods.ods_wechat_channels_order_raw') IS NOT NULL THEN
    EXECUTE $report_view$CREATE OR REPLACE VIEW common.v_current_wechat_channels_order_raw AS
WITH batches AS MATERIALIZED (
    SELECT c.batch_id,c.shop_identity_key,
           COALESCE(common.report_snapshot_date(l.source_file_name),
                    (l.started_at AT TIME ZONE 'Asia/Shanghai')::date) snapshot_date,
           COALESCE(l.ingest_run_id::text,l.batch_id::text) snapshot_key,
           MIN(l.started_at) OVER (PARTITION BY COALESCE(l.ingest_run_id::text,l.batch_id::text)) snapshot_at
    FROM common.v_ingest_batch_shop_context c
    JOIN ods.ods_file_ingest_log l ON l.batch_id=c.batch_id
    WHERE c.platform_code='wechat_channels' AND c.target_table='ods_wechat_channels_order_raw'
      AND c.shop_mapping_status='mapped' AND c.ingest_status='success'
), reports AS (
    SELECT r.id,b.shop_identity_key,BTRIM(r."订单号", E' \t\r\n') order_no,
           b.snapshot_date,b.snapshot_key,b.snapshot_at
    FROM ods.ods_wechat_channels_order_raw r JOIN batches b ON b.batch_id=r.batch_id
), latest AS (
    SELECT DISTINCT ON (shop_identity_key,order_no)
           shop_identity_key,order_no,snapshot_date,snapshot_key
    FROM reports
    ORDER BY shop_identity_key,order_no,snapshot_date DESC,snapshot_at DESC,snapshot_key DESC
), chosen AS (
    SELECT reports.* FROM reports JOIN latest ON reports.shop_identity_key=latest.shop_identity_key
      AND COALESCE(reports.order_no,'')=COALESCE(latest.order_no,'')
      AND reports.snapshot_date=latest.snapshot_date AND reports.snapshot_key=latest.snapshot_key
)
SELECT r.*, BTRIM(r."订单号", E' \t\r\n') || '#' || MD5(CONCAT_WS(E'\x1f',BTRIM(COALESCE(r."商品编码(平台)",'')),BTRIM(COALESCE(r."SKU编码(自定义)",'')),BTRIM(COALESCE(r."商品属性",'')))) || '#' ||
        ROW_NUMBER() OVER (PARTITION BY chosen.shop_identity_key,BTRIM(r."订单号", E' \t\r\n'),CONCAT_WS(E'\x1f',BTRIM(COALESCE(r."商品编码(平台)",'')),BTRIM(COALESCE(r."SKU编码(自定义)",'')),BTRIM(COALESCE(r."商品属性",'')))
                           ORDER BY r.source_file_name,r.source_row_no,r.id)::text AS business_detail_key
FROM ods.ods_wechat_channels_order_raw r JOIN chosen ON chosen.id=r.id;
$report_view$;
COMMENT ON VIEW common.v_current_wechat_channels_order_raw IS '直接投影wechat_channels订单ODS的最新整单快照；同一次提交的分片共同保留商品明细，旧版本不参与指标，不改变任何状态筛选条件。';
END IF;
END $$;


DO $$ BEGIN
IF TO_REGCLASS('ods.ods_pdd_settlement_raw') IS NOT NULL THEN
    EXECUTE $report_view$CREATE OR REPLACE VIEW common.v_current_pdd_settlement_raw AS
SELECT r.*
FROM ods.ods_pdd_settlement_raw r
JOIN common.v_ingest_batch_shop_context c ON c.batch_id=r.batch_id
   AND c.platform_code='pdd' AND c.target_table='ods_pdd_settlement_raw'
   AND c.shop_mapping_status='mapped' AND c.ingest_status='success'
JOIN ods.ods_file_ingest_log l ON l.batch_id=r.batch_id
WHERE NOT EXISTS (
    SELECT 1 FROM ods.ods_file_ingest_log n
    WHERE n.platform_code='pdd' AND n.target_table='ods_pdd_settlement_raw'
      AND n.shop_identity_key=c.shop_identity_key AND n.shop_mapping_status='mapped'
      AND n.ingest_status='success' AND n.batch_id<>l.batch_id
      AND n.report_period_start IS NOT NULL AND n.report_period_end IS NOT NULL
      AND BTRIM(r."发生时间")::timestamp::date BETWEEN n.report_period_start AND n.report_period_end
      AND (l.report_period_start IS NULL OR l.report_period_end IS NULL
           OR n.report_period_start<=l.report_period_start AND n.report_period_end>=l.report_period_end)
      AND (
          l.report_period_start IS NULL OR l.report_period_end IS NULL
          OR n.report_period_end-n.report_period_start>l.report_period_end-l.report_period_start
          OR n.report_period_end-n.report_period_start=l.report_period_end-l.report_period_start
             AND COALESCE(n.ingest_run_id::text,n.batch_id::text)
                 <>COALESCE(l.ingest_run_id::text,l.batch_id::text)
             AND (n.started_at,n.batch_id)>(l.started_at,l.batch_id)
      )
);
$report_view$;
COMMENT ON VIEW common.v_current_pdd_settlement_raw IS '拼多多结算ODS的有效查询覆盖来源：较完整范围覆盖旧窄范围；同范围取最新文件；范围未知只排除已由可信范围覆盖的自然日，范围外全部保留。文件内部所有流水均保留，不按订单号、金额或业务字段去重。';
END IF;
END $$;

DO $$
DECLARE item RECORD; col RECORD;
BEGIN
    FOR item IN SELECT p, 'v_current_' || p || '_order_raw' view_name, 'ods_' || p || '_order_raw' raw_name
                FROM UNNEST(ARRAY['douyin','tmall','jd','ks','pdd','xhs','wechat_channels']) p
                UNION ALL SELECT 'pdd','v_current_pdd_settlement_raw','ods_pdd_settlement_raw'
    LOOP
        IF TO_REGCLASS('common.' || item.view_name) IS NULL THEN CONTINUE; END IF;
        FOR col IN SELECT a.attname,COALESCE(col_description(c.oid,a.attnum),'原始ODS字段；保留源值、单位和枚举。') note
                   FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
                   JOIN pg_namespace n ON n.oid=c.relnamespace
                   WHERE n.nspname='ods' AND c.relname=item.raw_name AND a.attnum>0 AND NOT a.attisdropped
        LOOP
            EXECUTE FORMAT('COMMENT ON COLUMN common.%I.%I IS %L',item.view_name,col.attname,col.note);
        END LOOP;
        IF item.view_name<>'v_current_pdd_settlement_raw' THEN
            EXECUTE FORMAT('COMMENT ON COLUMN common.%I.business_detail_key IS %L',item.view_name,
                           '稳定订单商品明细键：子订单号或订单号加源商品规格字段和同商品行序号；不使用批次ID作为业务身份。');
        END IF;
    END LOOP;
END $$;
