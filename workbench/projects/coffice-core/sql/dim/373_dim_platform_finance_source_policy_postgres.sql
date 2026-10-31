ALTER TABLE dim.dim_platform_fee_mapping
    ADD COLUMN IF NOT EXISTS source_role VARCHAR(32)
        NOT NULL DEFAULT 'UNMAPPED',
    ADD COLUMN IF NOT EXISTS metric_role VARCHAR(32)
        NOT NULL DEFAULT 'EXCLUDE',
    ADD COLUMN IF NOT EXISTS dedup_rule_code VARCHAR(64)
        NOT NULL DEFAULT 'SOURCE_PRIMARY_KEY',
    ADD COLUMN IF NOT EXISTS source_treatment_initialized BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS canonical_operating_treatment VARCHAR(16);

ALTER TABLE dim.dim_platform_fee_mapping
    DROP CONSTRAINT IF EXISTS ck_dim_platform_fee_mapping_source_role,
    DROP CONSTRAINT IF EXISTS ck_dim_platform_fee_mapping_metric_role,
    DROP CONSTRAINT IF EXISTS ck_dim_platform_fee_mapping_dedup_rule;

ALTER TABLE dim.dim_platform_fee_mapping
    ADD CONSTRAINT ck_dim_platform_fee_mapping_source_role
        CHECK (
            source_role IN (
                'PRIMARY',
                'SUPPLEMENT',
                'EXPENSE_OFFSET',
                'REFUND_SUPPLEMENT',
                'RECONCILIATION',
                'ACCOUNT_TRANSFER',
                'DUPLICATE',
                'UNMAPPED'
            )
        ),
    ADD CONSTRAINT ck_dim_platform_fee_mapping_metric_role
        CHECK (
            metric_role IN (
                'MAIN_REVENUE',
                'MAIN_REFUND',
                'PLATFORM_EXPENSE',
                'EXPENSE_OFFSET',
                'RECONCILIATION',
                'ACCOUNT_TRANSFER',
                'EXCLUDE'
            )
        ),
    ADD CONSTRAINT ck_dim_platform_fee_mapping_dedup_rule
        CHECK (
            dedup_rule_code IN (
                'SOURCE_PRIMARY_KEY',
                'DOCUMENT_NO_LATEST',
                'WALLET_EVENT_HASH_LATEST',
                'ACCOUNT_FLOW_NO_LATEST',
                'RELATED_ORDER_REFUND_GUARD',
                'MERCHANT_ORDER_RECONCILIATION',
                'CANONICAL_SINGLE_SOURCE'
            )
        );

COMMENT ON COLUMN dim.dim_platform_fee_mapping.source_role IS
    '系统维护的来源职责；PRIMARY主计算、SUPPLEMENT结算单外补充、EXPENSE_OFFSET费用冲减、REFUND_SUPPLEMENT跨表查重后的补充退款、RECONCILIATION勾稽、ACCOUNT_TRANSFER账户划转、DUPLICATE重复事实、UNMAPPED待确认。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.metric_role IS
    '系统计算角色；MAIN_REVENUE主营收入、MAIN_REFUND主营退款、PLATFORM_EXPENSE平台费用、EXPENSE_OFFSET费用冲减、RECONCILIATION勾稽、ACCOUNT_TRANSFER账户划转、EXCLUDE排除。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.dedup_rule_code IS
    '系统去重或互斥规则编码；说明该平台原始场景使用的业务唯一键或跨表防重策略。';

-- 来源角色只初始化一次；后续分类合并不得重写已经确认的来源契约。
WITH roles AS (
    SELECT
        mapping_id,
        platform_code,source_document_type,secondary_category_code,
        primary_category_code,include_in_platform_expense,
        CASE
        WHEN secondary_category_code IN (
            'returned_platform_service_fee',
            'returned_talent_commission',
            'returned_leader_commission',
            'consolidated_shipping_temporary_unfreeze',
            'consolidated_shipping_unfreeze',
            'retention_compensation_insurance_claim',
            'jd_union_supplement',
            'tmall_fund_brand_new_refund_aggregate',
            'tmall_fund_union_commission_other',
            'tmall_fund_red_packet_refund_aggregate',
            'pdd_technology_fee_return',
            'pdd_appeal_recovery',
            'pdd_multi_order_discount'
        ) THEN 'EXPENSE_OFFSET'
        WHEN secondary_category_code IN (
            'post_settlement_refund',
            'after_sales_refund_deduction'
        ) THEN 'REFUND_SUPPLEMENT'
        WHEN secondary_category_code IN (
            'refund_after_settlement_to_user',
            'post_settlement_cash_refund'
        ) THEN 'DUPLICATE'
        WHEN secondary_category_code IN (
            'withdrawal',
            'balance_withdrawal',
            'pdd_withdrawal',
            'pdd_ad_account_transfer',
            'tmall_fund_withdrawal',
            'wechat_withdrawal'
        ) THEN 'ACCOUNT_TRANSFER'
        WHEN primary_category_code='account_transfer' THEN 'ACCOUNT_TRANSFER'
        WHEN include_in_platform_expense
             AND source_document_type = 'fund'
             AND platform_code = 'tmall'
            THEN 'PRIMARY'
        WHEN include_in_platform_expense
             AND source_document_type = 'fund'
            THEN 'SUPPLEMENT'
        WHEN include_in_platform_expense
            THEN 'PRIMARY'
        WHEN primary_category_code IN (
            'sales_income',
            'sales_refund',
            'platform_subsidy',
            'merchant_subsidy',
            'collected_delivery_income',
            'other_operating_income',
            'non_expense_goods_payment',
            'non_expense_collected_delivery_fee'
        ) THEN 'PRIMARY'
            ELSE 'RECONCILIATION'
        END AS source_role
    FROM dim.dim_platform_fee_mapping
), desired AS (
    SELECT
        mapping_id,source_role,
        CASE
        WHEN source_role = 'EXPENSE_OFFSET' THEN 'EXPENSE_OFFSET'
        WHEN include_in_platform_expense THEN 'PLATFORM_EXPENSE'
        WHEN source_role = 'REFUND_SUPPLEMENT'
             OR primary_category_code IN (
                 'sales_refund',
                 'non_expense_sales_refund'
             ) THEN 'MAIN_REFUND'
        WHEN primary_category_code IN (
            'sales_income',
            'platform_subsidy',
            'merchant_subsidy',
            'collected_delivery_income',
            'other_operating_income'
        ) THEN 'MAIN_REVENUE'
        WHEN source_role IN ('RECONCILIATION', 'DUPLICATE')
            THEN 'RECONCILIATION'
        WHEN source_role = 'ACCOUNT_TRANSFER' THEN 'ACCOUNT_TRANSFER'
            ELSE 'EXCLUDE'
        END AS metric_role,
        CASE
        WHEN source_role IN ('REFUND_SUPPLEMENT', 'DUPLICATE')
            THEN 'RELATED_ORDER_REFUND_GUARD'
        WHEN platform_code = 'jd'
             AND source_document_type = 'settlement'
            THEN 'DOCUMENT_NO_LATEST'
        WHEN platform_code = 'jd'
             AND source_document_type = 'fund'
             AND secondary_category_code = 'merchant_settlement'
            THEN 'MERCHANT_ORDER_RECONCILIATION'
        WHEN platform_code = 'jd'
             AND source_document_type = 'fund'
            THEN 'WALLET_EVENT_HASH_LATEST'
        WHEN platform_code = 'tmall'
            THEN 'ACCOUNT_FLOW_NO_LATEST'
        WHEN platform_code IN ('pdd', 'wechat_channels')
            THEN 'CANONICAL_SINGLE_SOURCE'
        WHEN primary_category_code IN (
            'non_expense_goods_settlement',
            'non_expense_merchant_settlement',
            'non_expense_refund_reconciliation',
            'settlement_reconciliation'
        ) THEN 'MERCHANT_ORDER_RECONCILIATION'
            ELSE 'SOURCE_PRIMARY_KEY'
        END AS dedup_rule_code
    FROM roles
)
UPDATE dim.dim_platform_fee_mapping mapping
SET source_role = desired.source_role,
    metric_role = desired.metric_role,
    dedup_rule_code = desired.dedup_rule_code
FROM desired
WHERE desired.mapping_id = mapping.mapping_id
  AND (NOT mapping.source_treatment_initialized OR mapping.source_role='UNMAPPED')
  AND (
      mapping.source_role IS DISTINCT FROM desired.source_role
      OR mapping.metric_role IS DISTINCT FROM desired.metric_role
      OR mapping.dedup_rule_code IS DISTINCT FROM desired.dedup_rule_code
  );

CREATE INDEX IF NOT EXISTS idx_dim_platform_fee_mapping_source_role
    ON dim.dim_platform_fee_mapping (
        platform_code,
        source_role,
        metric_role,
        include_in_platform_expense
    )
    WHERE is_active;

DO $$
DECLARE
    unmapped_count BIGINT;
    invalid_expense_role_count BIGINT;
    invalid_metric_role_count BIGINT;
BEGIN
    SELECT COUNT(*)
    INTO unmapped_count
    FROM dim.dim_platform_fee_mapping
    WHERE is_active
      AND source_role = 'UNMAPPED';

    SELECT COUNT(*)
    INTO invalid_expense_role_count
    FROM dim.dim_platform_fee_mapping
    WHERE is_active
      AND include_in_platform_expense
      AND source_role NOT IN (
          'PRIMARY', 'SUPPLEMENT', 'EXPENSE_OFFSET'
      );

    SELECT COUNT(*)
    INTO invalid_metric_role_count
    FROM dim.dim_platform_fee_mapping
    WHERE is_active
      AND (
          (
              include_in_platform_expense
              AND metric_role NOT IN (
                  'PLATFORM_EXPENSE', 'EXPENSE_OFFSET'
              )
          )
          OR (
              NOT include_in_platform_expense
              AND canonical_operating_treatment IS NOT NULL
              AND metric_role IN (
                  'PLATFORM_EXPENSE', 'EXPENSE_OFFSET'
              )
          )
      );

    IF unmapped_count > 0 THEN
        RAISE EXCEPTION
            '平台费用映射仍有%条来源职责为UNMAPPED，禁止刷新',
            unmapped_count;
    END IF;

    IF invalid_expense_role_count > 0 THEN
        RAISE EXCEPTION
            '平台费用映射有%条计费规则使用了不允许进入费用的来源职责',
            invalid_expense_role_count;
    END IF;

    IF invalid_metric_role_count > 0 THEN
        RAISE EXCEPTION
            '平台费用映射有%条计费开关与计算角色冲突',
            invalid_metric_role_count;
    END IF;
END
$$;
