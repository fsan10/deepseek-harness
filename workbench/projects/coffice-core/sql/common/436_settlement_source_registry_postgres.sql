-- 结算来源覆盖元数据；ODS原始事实保持不变，账户由target_table区分。
CREATE SCHEMA IF NOT EXISTS common;
CREATE TABLE IF NOT EXISTS common.settlement_source_registry (
    batch_id BIGINT PRIMARY KEY REFERENCES ods.ods_file_ingest_log(batch_id),
    source_group_key TEXT NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    file_hash TEXT NOT NULL,
    evidence_type TEXT NOT NULL CHECK (evidence_type IN ('user_confirmed', 'automation_receipt', 'report_header')),
    evidence JSONB NOT NULL CHECK (jsonb_typeof(evidence) = 'object'),
    rule_version TEXT NOT NULL DEFAULT 'settlement-coverage-v1',
    registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (period_end >= period_start)
);
COMMENT ON TABLE common.settlement_source_registry IS '结算批次查询范围与证据登记；引用导入日志，不修改或去重ODS流水；不同账户独立选择';
COMMENT ON COLUMN common.settlement_source_registry.batch_id IS '原始ODS导入批次，关联ods.ods_file_ingest_log.batch_id';
COMMENT ON COLUMN common.settlement_source_registry.source_group_key IS '同一次完整导出的分片或配套文件组标识；默认一个批次一组，显式分片允许同时保留';
COMMENT ON COLUMN common.settlement_source_registry.period_start IS '经查询参数、报表声明或人工确认的完整查询开始日期，包含零交易日，不能由文件名或首笔日期猜测';
COMMENT ON COLUMN common.settlement_source_registry.period_end IS '完整查询结束日期，包含当日全部流水和零交易日；不能以最后一笔交易日替代';
COMMENT ON COLUMN common.settlement_source_registry.file_hash IS '登记时核验的SHA256文件摘要，必须等于导入日志摘要以绑定原始版本';
COMMENT ON COLUMN common.settlement_source_registry.evidence_type IS '覆盖证据类型：user_confirmed人工确认、automation_receipt可信下载回执、report_header文件内查询声明';
COMMENT ON COLUMN common.settlement_source_registry.evidence IS 'JSON覆盖证据，包含确认说明或回执标识，禁止包含密码或令牌';
COMMENT ON COLUMN common.settlement_source_registry.rule_version IS '覆盖选择规则版本，当前settlement-coverage-v1，收入支出公式不属于本规则';
COMMENT ON COLUMN common.settlement_source_registry.registered_at IS '来源覆盖登记时间，带时区，用于追溯证据登记';

CREATE OR REPLACE VIEW common.v_settlement_source_batch AS
SELECT l.batch_id, l.platform_code, l.target_table, c.shop_identity_key,
       l.source_file_name, l.source_sheet_name, l.file_hash, l.started_at,
       COALESCE(r.source_group_key, 'batch:' || l.batch_id::text) AS source_group_key,
       r.period_start, r.period_end, r.evidence_type,
       COALESCE(r.rule_version, 'settlement-coverage-v1') AS rule_version
FROM ods.ods_file_ingest_log l
JOIN common.v_ingest_batch_shop_context c ON c.batch_id=l.batch_id
LEFT JOIN common.settlement_source_registry r ON r.batch_id=l.batch_id
WHERE l.ingest_status='success' AND c.shop_mapping_status='mapped'
  AND c.company_code IS NOT NULL AND c.shop_identity_key IS NOT NULL
  AND l.target_table IN ('ods_douyin_settlement_raw','ods_ks_settlement_raw',
      'ods_xhs_settlement_income_raw','ods_xhs_settlement_expense_raw',
      'ods_tmall_aggregate_fund_raw','ods_tmall_alipay_fund_raw');
COMMENT ON VIEW common.v_settlement_source_batch IS '按导入批次提供标准店铺、独立账户、已证明的范围和版本信息；未知范围保留NULL';

CREATE OR REPLACE VIEW common.v_settlement_source_days AS
SELECT 'ods_douyin_settlement_raw'::text target_table,batch_id,
       NULLIF(NULLIF(BTRIM("结算时间"),''),'-')::timestamp::date stat_date,COUNT(*) source_rows
FROM ods.ods_douyin_settlement_raw GROUP BY 1,2,3
UNION ALL SELECT 'ods_ks_settlement_raw',batch_id,
       NULLIF(NULLIF(BTRIM("实际结算时间"),''),'-')::timestamp::date,COUNT(*)
FROM ods.ods_ks_settlement_raw GROUP BY 1,2,3
UNION ALL SELECT 'ods_xhs_settlement_income_raw',batch_id,
       NULLIF(NULLIF(BTRIM("结算时间"),''),'-')::timestamp::date,COUNT(*)
FROM ods.ods_xhs_settlement_income_raw GROUP BY 1,2,3
UNION ALL SELECT 'ods_xhs_settlement_expense_raw',batch_id,
       NULLIF(NULLIF(BTRIM("结算时间"),''),'-')::timestamp::date,COUNT(*)
FROM ods.ods_xhs_settlement_expense_raw GROUP BY 1,2,3
UNION ALL SELECT 'ods_tmall_aggregate_fund_raw',batch_id,
       TO_DATE(BTRIM("入帐日期"),'YYYYMMDD'),COUNT(*)
FROM ods.ods_tmall_aggregate_fund_raw GROUP BY 1,2,3
UNION ALL SELECT 'ods_tmall_alipay_fund_raw',batch_id,
       NULLIF(NULLIF(BTRIM("发生时间"),''),'-')::timestamp::date,COUNT(*)
FROM ods.ods_tmall_alipay_fund_raw GROUP BY 1,2,3;
COMMENT ON VIEW common.v_settlement_source_days IS '原始结算按批次和业务日期计数，无业务状态、金额或订单去重';

CREATE OR REPLACE VIEW common.v_settlement_source_group AS
SELECT shop_identity_key,target_table,source_group_key,
       MAX(started_at) version_started_at,MAX(batch_id) version_batch_id
FROM common.v_settlement_source_batch GROUP BY 1,2,3;
COMMENT ON VIEW common.v_settlement_source_group IS '同一显式分片组整体比较版本，避免逐片比较导致同一完整导出只剩部分分片';

CREATE OR REPLACE VIEW common.v_settlement_source_decision AS
SELECT b.*, d.stat_date,d.source_rows,
       CASE WHEN choice.selection_id IS NOT NULL AND b.batch_id=ANY(choice.batch_ids) THEN NULL::bigint
            WHEN choice.selection_id IS NOT NULL THEN choice.batch_ids[1] ELSE winner.batch_id END AS covered_by_batch_id,
       CASE WHEN choice.selection_id IS NOT NULL THEN b.batch_id=ANY(choice.batch_ids)
            ELSE winner.batch_id IS NULL END AS is_effective,
       CASE WHEN choice.selection_id IS NOT NULL THEN 'explicit_day_selection'
            WHEN winner.batch_id IS NOT NULL THEN 'covered_by_verified_source'
            WHEN b.period_start IS NULL THEN 'unverified_single_source'
            ELSE 'verified_source' END AS decision_reason
FROM common.v_settlement_source_batch b
JOIN common.v_settlement_source_days d USING (batch_id,target_table)
JOIN common.v_settlement_source_group bg
  ON bg.shop_identity_key=b.shop_identity_key AND bg.target_table=b.target_table
 AND bg.source_group_key=b.source_group_key
LEFT JOIN LATERAL (
    SELECT n.batch_id
    FROM common.v_settlement_source_batch n
    JOIN common.v_settlement_source_group ng
      ON ng.shop_identity_key=n.shop_identity_key AND ng.target_table=n.target_table
     AND ng.source_group_key=n.source_group_key
    WHERE n.shop_identity_key=b.shop_identity_key AND n.target_table=b.target_table
      AND n.source_group_key<>b.source_group_key
      AND d.stat_date BETWEEN n.period_start AND n.period_end
      AND (
          (b.period_start IS NULL AND (ng.version_started_at,ng.version_batch_id)>(bg.version_started_at,bg.version_batch_id))
          OR (n.period_start<=b.period_start AND n.period_end>=b.period_end
              AND ((n.period_start,n.period_end)<>(b.period_start,b.period_end)
                   OR (ng.version_started_at,ng.version_batch_id)>(bg.version_started_at,bg.version_batch_id)))
      )
    ORDER BY (n.period_end-n.period_start) DESC,ng.version_started_at DESC,ng.version_batch_id DESC,n.batch_id DESC
    LIMIT 1
) winner ON TRUE
LEFT JOIN common.v_ingest_source_day_selection choice
  ON choice.shop_identity_key=b.shop_identity_key AND choice.target_table=b.target_table
 AND choice.stat_date=d.stat_date;
COMMENT ON VIEW common.v_settlement_source_decision IS '逐批次逐日解释有效/覆盖原因和覆盖者；同账户完整宽范围优先，同范围取最新成功版本，未知冲突由ETL停止';

CREATE OR REPLACE VIEW common.v_effective_settlement_source AS
SELECT * FROM common.v_settlement_source_decision WHERE is_effective;
COMMENT ON VIEW common.v_effective_settlement_source IS '供平台DWD使用的有效批次日期；只能在prepare_settlement_sources完成完整性和歧义校验后刷新';

CREATE OR REPLACE VIEW common.v_current_douyin_settlement_raw AS
SELECT r.* FROM ods.ods_douyin_settlement_raw r
JOIN common.v_effective_settlement_source s ON s.batch_id=r.batch_id
 AND s.target_table='ods_douyin_settlement_raw'
 AND s.stat_date=NULLIF(NULLIF(BTRIM(r."结算时间"),''),'-')::timestamp::date;
CREATE OR REPLACE VIEW common.v_current_ks_settlement_raw AS
SELECT r.* FROM ods.ods_ks_settlement_raw r
JOIN common.v_effective_settlement_source s ON s.batch_id=r.batch_id
 AND s.target_table='ods_ks_settlement_raw'
 AND s.stat_date=NULLIF(NULLIF(BTRIM(r."实际结算时间"),''),'-')::timestamp::date;
CREATE OR REPLACE VIEW common.v_current_xhs_settlement_income_raw AS
SELECT r.* FROM ods.ods_xhs_settlement_income_raw r
JOIN common.v_effective_settlement_source s ON s.batch_id=r.batch_id
 AND s.target_table='ods_xhs_settlement_income_raw'
 AND s.stat_date=NULLIF(NULLIF(BTRIM(r."结算时间"),''),'-')::timestamp::date;
CREATE OR REPLACE VIEW common.v_current_xhs_settlement_expense_raw AS
SELECT r.* FROM ods.ods_xhs_settlement_expense_raw r
JOIN common.v_effective_settlement_source s ON s.batch_id=r.batch_id
 AND s.target_table='ods_xhs_settlement_expense_raw'
 AND s.stat_date=NULLIF(NULLIF(BTRIM(r."结算时间"),''),'-')::timestamp::date;
CREATE OR REPLACE VIEW common.v_current_tmall_aggregate_fund_raw AS
SELECT r.* FROM ods.ods_tmall_aggregate_fund_raw r
JOIN common.v_effective_settlement_source s ON s.batch_id=r.batch_id
 AND s.target_table='ods_tmall_aggregate_fund_raw'
 AND s.stat_date=TO_DATE(BTRIM(r."入帐日期"),'YYYYMMDD');
CREATE OR REPLACE VIEW common.v_current_tmall_alipay_fund_raw AS
SELECT r.* FROM ods.ods_tmall_alipay_fund_raw r
JOIN common.v_effective_settlement_source s ON s.batch_id=r.batch_id
 AND s.target_table='ods_tmall_alipay_fund_raw'
 AND s.stat_date=NULLIF(NULLIF(BTRIM(r."发生时间"),''),'-')::timestamp::date;
