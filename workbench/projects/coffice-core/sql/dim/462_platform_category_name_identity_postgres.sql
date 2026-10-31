CREATE OR REPLACE FUNCTION dim.platform_category_name_key(value TEXT)
RETURNS TEXT LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT CASE normalized
        WHEN '售后费用' THEN '售后赔付'
        WHEN '退货物流费用' THEN '退货物流费'
        WHEN '推广费' THEN '推广费用'
        WHEN '支付服务费' THEN '支付手续费'
        WHEN '履约保险费' THEN '履约保障费'
        WHEN '物流费用' THEN '物流服务费'
        WHEN '天猫-百亿补贴' THEN '百亿补贴服务费'
        WHEN '营销优惠费' THEN '营销活动费用'
        ELSE normalized END
    FROM (SELECT LOWER(REGEXP_REPLACE(BTRIM(value),'[[:space:]　]+','','g')) normalized) n
$$;
COMMENT ON FUNCTION dim.platform_category_name_key(TEXT) IS
    '一级分类名称身份：去除空白、统一字母大小写及已确认的历史同义名称；同业务分类跨平台共用。';

CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_primary_category_name_key
    ON dim.dim_platform_fee_primary_category(dim.platform_category_name_key(primary_category_name));
COMMENT ON INDEX dim.uq_platform_primary_category_name_key IS
    '一级分类规范名称全局唯一；历史别名须先迁移映射引用后删除，不允许重复名称在不同平台重新创建。';
