-- 分类与经营归属独立；旧布尔值仅保留原始来源计算兼容语义。
ALTER TABLE dim.dim_platform_fee_mapping
    ALTER COLUMN secondary_category_name TYPE VARCHAR(768),
    ALTER COLUMN source_description_match_value TYPE TEXT;
ALTER TABLE dim.dim_platform_fee_mapping
    ADD COLUMN IF NOT EXISTS operating_treatment VARCHAR(16),
    ADD COLUMN IF NOT EXISTS source_component_code VARCHAR(128),
    ADD COLUMN IF NOT EXISTS canonical_operating_treatment VARCHAR(16),
    ADD COLUMN IF NOT EXISTS source_treatment_initialized BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE dim.dim_platform_fee_mapping
SET operating_treatment = CASE
    WHEN include_in_platform_expense THEN 'expense'
    WHEN metric_role IN ('MAIN_REVENUE','MAIN_REFUND')
      OR secondary_category_code IN ('goods_payment') THEN 'income'
    ELSE 'excluded' END
WHERE operating_treatment IS NULL AND NOT source_treatment_initialized AND created_by<>'operating_discovery';

UPDATE dim.dim_platform_fee_mapping
SET canonical_operating_treatment=CASE WHEN include_in_platform_expense THEN 'expense'
    WHEN metric_role IN ('MAIN_REVENUE','MAIN_REFUND') OR secondary_category_code IN ('goods_payment') THEN 'income' ELSE 'excluded' END
WHERE canonical_operating_treatment IS NULL AND NOT source_treatment_initialized AND created_by<>'operating_discovery';
UPDATE dim.dim_platform_fee_mapping SET source_treatment_initialized=TRUE WHERE NOT source_treatment_initialized;

ALTER TABLE dim.dim_platform_fee_mapping
    DROP CONSTRAINT IF EXISTS ck_dim_platform_fee_mapping_operating_treatment;
ALTER TABLE dim.dim_platform_fee_mapping
    ADD CONSTRAINT ck_dim_platform_fee_mapping_operating_treatment
    CHECK (operating_treatment IN ('income','expense','excluded'));

COMMENT ON COLUMN dim.dim_platform_fee_mapping.operating_treatment IS
    '财务维护的经营收支归属：income计入或冲减经营收入，expense计入或冲减经营支出，excluded不计入经营收支但保留全部明细；分类缺失不改变本字段。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.source_component_code IS
    '收入公式金额项目的稳定编码；与原始单据业务场景分开匹配，空值表示普通账务场景。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.include_in_platform_expense IS
    '历史来源公式兼容标记，由既有来源规则维护；不再作为财务可编辑经营归属，最终统计仅使用operating_treatment。';

CREATE OR REPLACE FUNCTION dim.match_platform_operating_scene(
    p_platform TEXT, p_document TEXT, p_scene TEXT,
    p_business TEXT DEFAULT NULL, p_description TEXT DEFAULT NULL
) RETURNS SETOF dim.dim_platform_fee_mapping
LANGUAGE SQL STABLE AS $$
    SELECT m.* FROM dim.dim_platform_fee_mapping m
    WHERE m.platform_code=p_platform AND m.source_document_type=p_document
      AND m.source_component_code IS NULL
      AND (
        (m.source_description_match_type='none' AND (m.secondary_category_name=p_scene
          OR m.normalized_scene_name=p_scene))
        OR (m.source_description_match_type<>'none'
          AND (m.source_business_type IS NULL OR m.source_business_type=p_business)
          AND (m.source_description_match_type='any'
            OR (m.source_description_match_type='exact' AND m.source_description_match_value=p_description)
            OR (m.source_description_match_type='prefix' AND LEFT(COALESCE(p_description,''),LENGTH(m.source_description_match_value))=m.source_description_match_value)
            OR (m.source_description_match_type='contains' AND POSITION(m.source_description_match_value IN COALESCE(p_description,''))>0))))
    ORDER BY m.mapping_priority DESC,m.mapping_id LIMIT 1
$$;
COMMENT ON FUNCTION dim.match_platform_operating_scene(TEXT,TEXT,TEXT,TEXT,TEXT) IS
    '经营场景统一匹配器，候选页面、DWS使用相同的精确/前缀/包含优先规则；停用分类不丢失经营归属。';

COMMENT ON COLUMN dim.dim_platform_fee_mapping.canonical_operating_treatment IS '原来源公式归属快照，仅用于来源完整性及防重，不随经营归属或分类修改；空值表示来源性质待确认。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.source_treatment_initialized IS '原来源归属快照初始化标记，防止反复刷新覆盖新场景的独立经营归属。';

CREATE OR REPLACE FUNCTION dim.guard_platform_operating_source()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.source_treatment_initialized
       AND NEW.include_in_platform_expense IS DISTINCT FROM OLD.include_in_platform_expense THEN
        RAISE EXCEPTION '历史费用开关已只读，请修改经营收支归属（收入、支出、不计入）';
    END IF;
    RETURN NEW;
END $$;
COMMENT ON FUNCTION dim.guard_platform_operating_source() IS
    '阻止旧界面或旧接口写入历史布尔开关，保护原来源公式，经营归属只由新三态字段控制。';
DROP TRIGGER IF EXISTS trg_guard_platform_operating_source ON dim.dim_platform_fee_mapping;
CREATE TRIGGER trg_guard_platform_operating_source
    BEFORE UPDATE OF include_in_platform_expense ON dim.dim_platform_fee_mapping
    FOR EACH ROW EXECUTE FUNCTION dim.guard_platform_operating_source();
