-- 经营选择与来源用途分开；兼容快照只用于复现原公式。
ALTER TABLE dim.dim_platform_fee_mapping
    ADD COLUMN IF NOT EXISTS treatment_origin VARCHAR(16) NOT NULL DEFAULT 'historical',
    ADD COLUMN IF NOT EXISTS suggested_operating_treatment VARCHAR(16),
    ADD COLUMN IF NOT EXISTS source_usage VARCHAR(24) NOT NULL DEFAULT 'independent',
    ADD COLUMN IF NOT EXISTS source_usage_note TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS policy_initialized BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS alias_of_mapping_id BIGINT,
    ADD COLUMN IF NOT EXISTS last_etl_run_id UUID;
ALTER TABLE dim.dim_platform_fee_mapping DROP CONSTRAINT IF EXISTS ck_platform_operating_policy;
ALTER TABLE dim.dim_platform_fee_mapping ADD CONSTRAINT ck_platform_operating_policy CHECK (
    treatment_origin IN ('historical','system','manual','pending')
    AND source_usage IN ('independent','accounted','duplicate')
    AND (suggested_operating_treatment IS NULL OR suggested_operating_treatment IN ('income','expense','excluded'))
    AND (alias_of_mapping_id IS NULL OR alias_of_mapping_id<>mapping_id));
COMMENT ON COLUMN dim.dim_platform_fee_mapping.treatment_origin IS '经营归属依据：historical迁移保留、system已确认规则、manual财务确认、pending性质待确认；分类变更不得修改。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.suggested_operating_treatment IS '已验证平台规则给出的默认建议income/expense/excluded，空为无可靠建议；人工选择优先，不根据分类或正负号推断。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.source_usage IS '独立来源用途：independent可由财务配置、accounted已在主来源统计、duplicate重复业务事实；文件覆盖和原生流水去重继续独立执行。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.source_usage_note IS '来源用途的中文依据；已统计来源说明对应主计算链路，不以历史RECONCILIATION角色值代替依据。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.policy_initialized IS '来源用途和归属依据已初始化标记，后续刷新不覆盖财务选择或更正。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.alias_of_mapping_id IS '同一业务的有效配置规则ID；原始别名保留匹配和追溯，页面只维护目标规则，避免公式组成项与原始场景两个开关。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.last_etl_run_id IS '最近配置变更触发的ETL运行UUID；用于展示已保存、重算中、生效或失败状态，不作为金额事实。';
CREATE OR REPLACE FUNCTION dim.effective_platform_operating_treatment(p_mapping_id BIGINT)
RETURNS VARCHAR LANGUAGE SQL STABLE AS $$
    SELECT CASE WHEN source_usage IN ('accounted','duplicate') THEN 'excluded'
        ELSE operating_treatment END
    FROM dim.dim_platform_fee_mapping WHERE mapping_id=p_mapping_id
$$;
COMMENT ON FUNCTION dim.effective_platform_operating_treatment(BIGINT) IS '最终经营归属：仅明确的已统计/重复来源排除；独立金额服从财务归属，未知为NULL，不由旧角色或旧快照锁定。';
