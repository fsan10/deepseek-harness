CREATE SCHEMA IF NOT EXISTS dim;

CREATE TABLE IF NOT EXISTS dim.dim_company_product_code_mapping (
    mapping_id BIGSERIAL PRIMARY KEY,
    product_id VARCHAR(128) NOT NULL,
    source_product_category VARCHAR(128),
    legacy_large_product_category VARCHAR(128),
    legacy_product_category_l2 VARCHAR(128),
    legacy_product_name VARCHAR(255),
    code_pattern VARCHAR(128) NOT NULL,
    source_code_pattern VARCHAR(128),
    code_prefix VARCHAR(128),
    match_rule VARCHAR(32) NOT NULL,
    code_role VARCHAR(32) NOT NULL,
    mapping_source VARCHAR(32) NOT NULL DEFAULT 'file',
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128),
    source_row_no INTEGER,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_company_product_code_pattern UNIQUE (code_pattern),
    CONSTRAINT ck_company_product_code_pattern_not_blank
        CHECK (BTRIM(code_pattern) <> ''),
    CONSTRAINT fk_company_product_code_mapping_product
        FOREIGN KEY (product_id)
        REFERENCES dim.dim_influencer_product (product_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_company_product_match_rule
        CHECK (match_rule IN ('exact', 'suffix_quantity')),
    CONSTRAINT ck_company_product_code_role
        CHECK (code_role IN ('box', 'sachet')),
    CONSTRAINT ck_company_product_mapping_source
        CHECK (mapping_source IN ('file', 'manual')),
    CONSTRAINT ck_company_product_code_prefix
        CHECK (
            (match_rule = 'suffix_quantity' AND code_prefix IS NOT NULL AND BTRIM(code_prefix) <> '')
            OR (match_rule = 'exact' AND code_prefix IS NULL)
        )
);

COMMENT ON TABLE dim.dim_company_product_code_mapping IS '公司统一产品商家编码映射基础表；最终关系和全部字段注释由203号SQL统一补齐。';
