-- 小红书“申诉调账”是平台补偿收入，不是平台费用。
-- 该迁移保留现有人工映射记录，避免删除历史配置；若新库没有该场景则补建一条非费用映射。
INSERT INTO dim.dim_platform_fee_mapping (
    platform_code,
    platform_name,
    source_document_type,
    secondary_category_code,
    secondary_category_name,
    source_business_type,
    source_description_match_type,
    source_description_match_value,
    mapping_priority,
    primary_category_code,
    primary_category_name,
    include_in_platform_expense,
    classification_note,
    display_order,
    is_active,
    created_by,
    updated_by
)
SELECT
    'xhs',
    '小红书',
    'settlement',
    'xhs_settlement_0dd9edcc6f4ff9e3',
    '申诉调账',
    '申诉调账',
    'none',
    NULL,
    100,
    'platform_subsidy',
    '平台补贴',
    FALSE,
    '申诉调账按平台补偿收入进入收入链路并保留正负号；属于应税收入，不计入平台费用。',
    41,
    TRUE,
    'system_xhs_income_policy',
    'system_xhs_income_policy'
WHERE NOT EXISTS (
    SELECT 1
    FROM dim.dim_platform_fee_mapping
    WHERE platform_code='xhs'
      AND source_document_type='settlement'
      AND secondary_category_name='申诉调账'
)
ON CONFLICT (platform_code, source_document_type, secondary_category_code)
DO NOTHING;

UPDATE dim.dim_platform_fee_mapping
SET source_business_type='申诉调账',
    primary_category_code='platform_subsidy',
    primary_category_name='平台补贴',
    include_in_platform_expense=FALSE,
    classification_note='申诉调账按平台补偿收入进入收入链路并保留正负号；属于应税收入，不计入平台费用。',
    updated_by='system_xhs_income_policy'
WHERE platform_code='xhs'
  AND source_document_type='settlement'
  AND secondary_category_name='申诉调账';
