CREATE SCHEMA IF NOT EXISTS dim;

WITH alias_seed(alias_code, company_product_code, quantity_position, code_role, source_note) AS (
    VALUES
        ('HB', 'M-MHB', 'prefix', 'box', '历史快手/视频号缩写'),
        ('TZ', 'M-TZ', 'prefix', 'box', '历史快手/视频号缩写'),
        ('FB', 'M-MFB', 'prefix', 'box', '历史快手/视频号缩写'),
        ('LH', 'LH', 'prefix', 'box', '历史快手/视频号缩写'),
        ('BXTD', 'M-BXT-D', 'prefix', 'box', '历史快手/视频号缩写'),
        ('BXTF', 'M-BXT-F', 'prefix', 'box', '历史快手/视频号缩写'),
        ('SY', 'M-NXSY', 'prefix', 'box', '历史快手/视频号缩写'),
        ('SYD', 'M-NXSY-XD', 'prefix', 'sachet', '历史快手/视频号缩写'),
        ('MG', 'M-MGNT', 'prefix', 'box', '历史快手/视频号缩写'),
        ('MGD', 'M-MGNT-XD', 'prefix', 'sachet', '历史快手/视频号缩写'),
        ('ML', 'M-MLXY', 'prefix', 'box', '历史快手/视频号缩写'),
        ('MLXYD', 'M-MLXY-XD', 'prefix', 'sachet', '历史快手/视频号缩写'),
        ('MGNT', 'M-MGNT', 'suffix', 'box', '订单实际出现的省略M前缀表达'),
        ('M-KKNT', 'Y-SRKK', 'suffix', 'box', '历史订单实际使用的丝绒可可编码族')
), resolved AS (
    SELECT
        seed.*,
        product.product_id
    FROM alias_seed seed
    JOIN dim.dim_influencer_product product
      ON UPPER(BTRIM(product.company_product_code)) = seed.company_product_code
)
INSERT INTO dim.dim_company_product_code_mapping (
    product_id,
    platform_code,
    shop_code,
    source_product_code,
    code_pattern,
    source_code_pattern,
    code_prefix,
    match_rule,
    code_role,
    mapping_source,
    source_file_name,
    source_sheet_name,
    is_active,
    alias_code,
    quantity_position,
    mapping_kind,
    legacy_platform_codes
)
SELECT
    product_id,
    '*',
    NULL,
    alias_code,
    CASE
        WHEN quantity_position = 'prefix' THEN 'X' || alias_code
        WHEN quantity_position = 'suffix' THEN alias_code || '-X'
        ELSE alias_code
    END,
    alias_code,
    CASE WHEN quantity_position = 'suffix' THEN alias_code || '-' ELSE NULL END,
    CASE
        WHEN quantity_position = 'prefix' THEN 'prefix_quantity'
        WHEN quantity_position = 'suffix' THEN 'suffix_quantity'
        ELSE 'exact'
    END,
    code_role,
    'manual',
    source_note,
    'company_alias',
    TRUE,
    alias_code,
    quantity_position,
    'alias',
    ARRAY['ks', 'wechat_channels']::TEXT[]
FROM resolved
ON CONFLICT ((UPPER(BTRIM(alias_code))), quantity_position) DO UPDATE
SET product_id = EXCLUDED.product_id,
    source_product_code = EXCLUDED.source_product_code,
    code_pattern = EXCLUDED.code_pattern,
    code_prefix = EXCLUDED.code_prefix,
    match_rule = EXCLUDED.match_rule,
    code_role = EXCLUDED.code_role,
    mapping_kind = 'alias',
    is_active = TRUE,
    updated_at = NOW();

COMMENT ON TABLE dim.dim_company_product_code_mapping IS
    '公司级商品编码表达规则；包含公司商品编码本身、跨平台缩写别名和特殊精确编码。';
