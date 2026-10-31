CREATE TEMP TABLE _tmall_settlement_expense_legacy ON COMMIT DROP AS
WITH fund_months AS (
    SELECT DISTINCT DATE_TRUNC('month', stat_date)::date AS month_start
    FROM dwd.dwd_tmall_settlement_fund_event_detail
)
SELECT legacy.*
FROM dws.dws_tmall_settlement_expense_shop_daily_type legacy
WHERE NOT EXISTS (
    SELECT 1
    FROM fund_months
    WHERE fund_months.month_start = DATE_TRUNC('month', legacy.stat_date)::date
);

TRUNCATE TABLE dws.dws_tmall_settlement_expense_shop_daily_type;

INSERT INTO dws.dws_tmall_settlement_expense_shop_daily_type (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    expense_type_code, expense_type_name, expense_amount, included_event_count,
    source_updated_at, updated_at
)
SELECT
    stat_date, platform_code, platform_name, shop_code, shop_name,
    expense_type_code, expense_type_name, expense_amount, included_event_count,
    source_updated_at, NOW()
FROM _tmall_settlement_expense_legacy
UNION ALL
SELECT
    stat_date, platform_code, platform_name, shop_code, shop_name,
    expense_type_code, expense_type_name, expense_amount, included_event_count,
    source_updated_at, NOW()
FROM dws.dws_tmall_settlement_fund_expense_shop_daily_type;
