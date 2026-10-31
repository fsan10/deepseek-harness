CREATE TABLE IF NOT EXISTS dim.dim_platform_scene_normalization_rule (
    rule_id BIGSERIAL PRIMARY KEY,
    rule_code VARCHAR(96) NOT NULL UNIQUE,
    rule_name VARCHAR(128) NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    source_document_type VARCHAR(16) NOT NULL CHECK (source_document_type IN ('fund','settlement')),
    source_business_type TEXT,
    pattern TEXT NOT NULL,
    replacement TEXT NOT NULL DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 100,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    note TEXT NOT NULL DEFAULT '',
    last_etl_run_id UUID,
    created_by VARCHAR(128) NOT NULL DEFAULT 'scene_migration',
    updated_by VARCHAR(128) NOT NULL DEFAULT 'scene_migration',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE dim.dim_platform_scene_normalization_rule ADD COLUMN IF NOT EXISTS last_etl_run_id UUID;
COMMENT ON TABLE dim.dim_platform_scene_normalization_rule IS '财务后台可维护的原始收支场景命名清洗规则；使用PostgreSQL正则顺序替换，不修改原始描述、金额、经营归属或流水防重身份。';
COMMENT ON COLUMN dim.dim_platform_scene_normalization_rule.rule_id IS '规则代理主键，无业务单位。';
COMMENT ON COLUMN dim.dim_platform_scene_normalization_rule.rule_code IS '规则稳定编码；用于种子幂等，不在业务列表展示。';
COMMENT ON COLUMN dim.dim_platform_scene_normalization_rule.rule_name IS '后台展示的规则名称。';
COMMENT ON COLUMN dim.dim_platform_scene_normalization_rule.platform_code IS '平台编码，与财务平台编码一致。';
COMMENT ON COLUMN dim.dim_platform_scene_normalization_rule.source_document_type IS '适用报表来源：fund资金、settlement结算。';
COMMENT ON COLUMN dim.dim_platform_scene_normalization_rule.source_business_type IS '精确限定的原始业务类型；NULL表示此平台及来源的全部业务类型。';
COMMENT ON COLUMN dim.dim_platform_scene_normalization_rule.pattern IS 'PostgreSQL正则表达式，作用于完整场景名称；保存前须通过样本预览和冲突检查。';
COMMENT ON COLUMN dim.dim_platform_scene_normalization_rule.replacement IS '正则替换内容，允许PostgreSQL捕获组引用；空字符串表示删除匹配部分。';
COMMENT ON COLUMN dim.dim_platform_scene_normalization_rule.priority IS '执行顺序，数值小的先执行，同顺序按规则主键；无金额单位。';
COMMENT ON COLUMN dim.dim_platform_scene_normalization_rule.is_active IS '规则启用状态；停用后重新计算恢复原始名称，保留规则及操作审计。';
COMMENT ON COLUMN dim.dim_platform_scene_normalization_rule.note IS '财务维护的适用说明，不参与经营归属或分类计算。';
COMMENT ON COLUMN dim.dim_platform_scene_normalization_rule.last_etl_run_id IS '最近一次规则保存所创建的异步ETL任务标识，用于展示等待、运行、成功或失败状态；无金额单位。';
COMMENT ON COLUMN dim.dim_platform_scene_normalization_rule.created_by IS '规则创建操作人。';
COMMENT ON COLUMN dim.dim_platform_scene_normalization_rule.updated_by IS '最近修改操作人。';
COMMENT ON COLUMN dim.dim_platform_scene_normalization_rule.created_at IS '规则创建时间，带时区。';
COMMENT ON COLUMN dim.dim_platform_scene_normalization_rule.updated_at IS '最近修改时间，带时区，用于并发保存检查。';

INSERT INTO dim.dim_platform_scene_normalization_rule(rule_code,rule_name,platform_code,source_document_type,source_business_type,pattern,replacement,priority,note)
VALUES
 ('ks_refund_leader_suffix','团长佣金返还去除退款单尾缀','ks','fund','佣金/技术服务费返还','-cps团长三方分佣户-退款单号[：:]?.*$','',10,'团长返还使用稳定场景名；平台服务费、推广者及MCN等其他业务标识保留。'),
 ('ks_refund_order_channel','退款冻结解冻去除电商订单尾缀','ks','fund',NULL,'-快手电商-订单(编号|号)[：:]?.*$','',20,'删除订单渠道与单号尾缀，业务类型及退款业务含义保留。'),
 ('ks_order_number_suffix','资金场景去除订单单号尾缀','ks','fund',NULL,'-订单(编号|号)[：:]?.*$','',30,'同时兼容只有字段标签、尚未附加单号的配置名称。'),
 ('ks_refund_number_suffix','资金场景去除退款单号尾缀','ks','fund',NULL,'-退款单(编号|号)[：:]?.*$','',40,'保留退款来源及佣金对象等业务区别，只去除单号标签及值。'),
 ('jd_post_settlement_refund_scene','结算后售后退款去除服务单与订单单号','jd','fund',NULL,
  '^售后服务单号[0-9]+，对应订单号[0-9]+，因该订单已结算，从钱包可用余额中扣收该笔费用用于处理消费者售后退款问题',
  '结算后售后退款',30,'仅匹配已识别的售后退款固定文案，原生服务单与订单身份保留在来源。'),
 ('tmall_guarantee_order_label','保证金管控扣款去除订单标签','tmall','fund','保证金扣款','订单编号[：:](<ID>|[0-9]+)[，,][[:space:]]*','',30,'保留保证金管控用途，去除逐笔订单标签。'),
 ('tmall_commission_rebate_scene','百补订单激励佣金保留稳定费用名称','tmall','fund','转账',
  '^转账 [+] 代扣款（扣款用途：天猫佣金-百补订单激励前返.*$',
  '转账 + 天猫佣金-百补订单激励前返',40,'仅匹配此佣金项目；付款方、邮箱与订单号保留在原始备注，不作为费用类型维度。')
ON CONFLICT (rule_code) DO NOTHING;

CREATE OR REPLACE FUNCTION dim.normalize_platform_scene(
    p_platform TEXT,p_document TEXT,p_scene TEXT,p_business TEXT DEFAULT NULL
) RETURNS TEXT LANGUAGE plpgsql STABLE AS $$
DECLARE value TEXT := BTRIM(COALESCE(p_scene,'')); r RECORD;
BEGIN
    FOR r IN SELECT pattern,replacement FROM dim.dim_platform_scene_normalization_rule
        WHERE is_active AND platform_code=p_platform AND source_document_type=p_document
          AND (source_business_type IS NULL OR source_business_type=COALESCE(p_business,SPLIT_PART(p_scene,' + ',1)))
        ORDER BY priority,rule_id
    LOOP
        value := BTRIM(REGEXP_REPLACE(value,r.pattern,r.replacement,'g'));
    END LOOP;
    IF value='' OR LENGTH(value)>768 THEN
        RAISE EXCEPTION '场景清洗后为空或超长，请检查场景清洗规则';
    END IF;
    RETURN value;
END $$;
COMMENT ON FUNCTION dim.normalize_platform_scene(TEXT,TEXT,TEXT,TEXT) IS '按平台、来源及可选业务类型顺序执行可配置PostgreSQL正则；清洗名称不改变原始描述、金额符号、分类或来源身份。';

ALTER TABLE dim.dim_platform_fee_mapping ADD COLUMN IF NOT EXISTS normalized_scene_name VARCHAR(768);
COMMENT ON COLUMN dim.dim_platform_fee_mapping.normalized_scene_name IS '由当前场景清洗规则生成的匹配缓存；规则保存和ETL准备时重建，避免逐笔明细反复执行映射正则，不改变原始场景与公式编码。';
UPDATE dim.dim_platform_fee_mapping SET normalized_scene_name=
    dim.normalize_platform_scene(platform_code,source_document_type,secondary_category_name,source_business_type)
WHERE normalized_scene_name IS DISTINCT FROM
    dim.normalize_platform_scene(platform_code,source_document_type,secondary_category_name,source_business_type);
