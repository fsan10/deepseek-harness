-- 用户确认的抖音音咖店铺；沿用漯河音咖商贸有限公司已有公司编码。
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM dim.dim_platform_shop_company
        WHERE (company_code = 'company_013' AND company_name <> '漯河音咖商贸有限公司')
           OR (company_name = '漯河音咖商贸有限公司' AND company_code <> 'company_013')
    ) THEN
        RAISE EXCEPTION '音咖公司编码与现有映射冲突，停止新增抖音店铺';
    END IF;

    IF EXISTS (
        SELECT 1 FROM dim.dim_platform_shop_company
        WHERE platform_code = 'douyin'
          AND (
              (shop_name = 'MOCK音咖专卖店' AND shop_code <> '294686533')
              OR (account_id = '294686533' AND shop_code <> '294686533')
              OR (shop_code = '294686533' AND (
                  platform_name <> '抖音'
                  OR company_code <> 'company_013'
                  OR company_name <> '漯河音咖商贸有限公司'
                  OR shop_name <> 'MOCK音咖专卖店'
                  OR shop_type <> '专卖店'
                  OR account_id <> '294686533'
                  OR is_default OR NOT is_active OR valid_to IS NOT NULL
              ))
          )
    ) THEN
        RAISE EXCEPTION '抖音音咖店铺现有映射与用户确认冲突，停止';
    END IF;

    INSERT INTO dim.dim_platform_shop_company (
        platform_code, platform_name, company_code, company_name,
        shop_code, shop_name, shop_type, account_id, is_default, is_active
    )
    SELECT 'douyin', '抖音', 'company_013', '漯河音咖商贸有限公司',
           '294686533', 'MOCK音咖专卖店', '专卖店', '294686533', FALSE, TRUE
    WHERE NOT EXISTS (
        SELECT 1 FROM dim.dim_platform_shop_company
        WHERE platform_code = 'douyin' AND shop_code = '294686533'
    );
END $$;
