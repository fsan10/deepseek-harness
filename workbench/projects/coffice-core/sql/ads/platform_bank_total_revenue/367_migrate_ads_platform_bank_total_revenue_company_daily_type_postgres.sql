DO $$
BEGIN
    IF TO_REGCLASS('ads.ads_platform_bank_total_revenue_company_daily_type') IS NOT NULL
       AND (
           EXISTS (
               SELECT 1
               FROM information_schema.columns
               WHERE table_schema = 'ads'
                 AND table_name = 'ads_platform_bank_total_revenue_company_daily_type'
                 AND column_name = 'revenue_amount'
           )
           OR NOT EXISTS (
               SELECT 1
               FROM information_schema.columns
               WHERE table_schema = 'ads'
                 AND table_name = 'ads_platform_bank_total_revenue_company_daily_type'
                 AND column_name = 'financial_direction_code'
           )
       ) THEN
        DROP TABLE ads.ads_platform_bank_total_revenue_company_daily_type;
    END IF;
END $$;
