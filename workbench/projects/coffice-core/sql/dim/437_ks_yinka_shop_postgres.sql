-- 用户确认的快手音咖归属；不覆盖任何其他店铺或公司。
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM dim.dim_platform_shop_company
               WHERE company_code='company_013' AND company_name<>'漯河音咖商贸有限公司') THEN
        RAISE EXCEPTION 'company_013已被其他公司使用，停止音咖映射';
    END IF;
    IF EXISTS (SELECT 1 FROM dim.dim_platform_shop_company
               WHERE platform_code='ks' AND shop_code='2376318498' AND is_active
                 AND (company_name<>'漯河音咖商贸有限公司' OR account_id<>'2376318498')) THEN
        RAISE EXCEPTION '音咖现有映射与用户确认冲突，停止';
    END IF;
END $$;
INSERT INTO dim.dim_platform_shop_company
    (platform_code,platform_name,company_code,company_name,shop_code,shop_name,shop_type,account_id)
VALUES ('ks','快手','company_013','漯河音咖商贸有限公司','2376318498','MOCK音咖专卖店','专卖店','2376318498')
ON CONFLICT (platform_code,shop_code,valid_from) DO NOTHING;
