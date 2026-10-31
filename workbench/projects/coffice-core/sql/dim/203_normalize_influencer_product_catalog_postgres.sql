CREATE SCHEMA IF NOT EXISTS dim;

ALTER TABLE dim.dim_influencer_product_category
    ADD COLUMN IF NOT EXISTS category_level SMALLINT,
    ADD COLUMN IF NOT EXISTS parent_category_id BIGINT,
    ADD COLUMN IF NOT EXISTS category_code VARCHAR(128),
    ADD COLUMN IF NOT EXISTS maintenance_source VARCHAR(32) NOT NULL DEFAULT 'manual';

ALTER TABLE dim.dim_influencer_product
    ADD COLUMN IF NOT EXISTS maintenance_source VARCHAR(32) NOT NULL DEFAULT 'manual';

ALTER TABLE dim.dim_company_product_code_mapping
    ADD COLUMN IF NOT EXISTS product_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS source_code_pattern VARCHAR(128);

DROP INDEX IF EXISTS dim.uq_influencer_product_category_name;

DO $migration$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'dim'
          AND table_name = 'dim_company_product_code_mapping'
          AND column_name = 'large_product_category'
    ) THEN
        EXECUTE $sql$
            INSERT INTO dim.dim_influencer_product_category (
                category_name,
                category_level,
                category_code,
                maintenance_source
            )
            SELECT DISTINCT
                BTRIM(m.large_product_category),
                1,
                'CAT-L1-' || UPPER(SUBSTRING(MD5(LOWER(BTRIM(m.large_product_category))) FROM 1 FOR 16)),
                'file'
            FROM dim.dim_company_product_code_mapping m
            WHERE NULLIF(BTRIM(m.large_product_category), '') IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM dim.dim_influencer_product_category c
                  WHERE c.category_level = 1
                    AND LOWER(BTRIM(c.category_name)) = LOWER(BTRIM(m.large_product_category))
              )
        $sql$;

        EXECUTE $sql$
            WITH unique_parent AS (
                SELECT
                    LOWER(BTRIM(COALESCE(NULLIF(m.product_category_l2, ''), m.large_product_category))) AS l2_key,
                    MIN(BTRIM(m.large_product_category)) AS l1_name
                FROM dim.dim_company_product_code_mapping m
                GROUP BY LOWER(BTRIM(COALESCE(NULLIF(m.product_category_l2, ''), m.large_product_category)))
                HAVING COUNT(DISTINCT LOWER(BTRIM(m.large_product_category))) = 1
            )
            UPDATE dim.dim_influencer_product_category c
            SET category_level = 2,
                parent_category_id = parent.category_id,
                category_code = COALESCE(
                    c.category_code,
                    'CAT-LEGACY-L2-' || LPAD(c.category_id::TEXT, 8, '0')
                ),
                maintenance_source = COALESCE(c.maintenance_source, 'manual'),
                updated_at = NOW()
            FROM unique_parent relation
            JOIN dim.dim_influencer_product_category parent
              ON parent.category_level = 1
             AND LOWER(BTRIM(parent.category_name)) = LOWER(BTRIM(relation.l1_name))
            WHERE c.category_level IS NULL
              AND LOWER(BTRIM(c.category_name)) = relation.l2_key
        $sql$;

        UPDATE dim.dim_influencer_product_category
        SET category_level = 1,
            category_code = COALESCE(
                category_code,
                'CAT-LEGACY-L1-' || LPAD(category_id::TEXT, 8, '0')
            ),
            maintenance_source = COALESCE(maintenance_source, 'manual'),
            updated_at = NOW()
        WHERE category_level IS NULL;

        EXECUTE $sql$
            INSERT INTO dim.dim_influencer_product_category (
                category_name,
                category_level,
                parent_category_id,
                category_code,
                maintenance_source
            )
            SELECT DISTINCT
                BTRIM(COALESCE(NULLIF(m.product_category_l2, ''), m.large_product_category)),
                2,
                parent.category_id,
                'CAT-L2-' || UPPER(SUBSTRING(MD5(
                    LOWER(BTRIM(m.large_product_category)) || '|' ||
                    LOWER(BTRIM(COALESCE(NULLIF(m.product_category_l2, ''), m.large_product_category)))
                ) FROM 1 FOR 16)),
                'file'
            FROM dim.dim_company_product_code_mapping m
            JOIN dim.dim_influencer_product_category parent
              ON parent.category_level = 1
             AND LOWER(BTRIM(parent.category_name)) = LOWER(BTRIM(m.large_product_category))
            WHERE NOT EXISTS (
                SELECT 1
                FROM dim.dim_influencer_product_category child
                WHERE child.category_level = 2
                  AND child.parent_category_id = parent.category_id
                  AND LOWER(BTRIM(child.category_name)) =
                      LOWER(BTRIM(COALESCE(NULLIF(m.product_category_l2, ''), m.large_product_category)))
            )
        $sql$;

        INSERT INTO dim.dim_influencer_product_category (
            category_name,
            category_level,
            parent_category_id,
            category_code,
            maintenance_source
        )
        SELECT
            parent.category_name,
            2,
            parent.category_id,
            'CAT-LEGACY-CHILD-' || LPAD(parent.category_id::TEXT, 8, '0'),
            'manual'
        FROM dim.dim_influencer_product_category parent
        WHERE parent.category_level = 1
          AND EXISTS (
              SELECT 1
              FROM dim.dim_influencer_product p
              WHERE p.category_id = parent.category_id
          )
          AND NOT EXISTS (
              SELECT 1
              FROM dim.dim_influencer_product_category child
              WHERE child.parent_category_id = parent.category_id
                AND child.category_level = 2
                AND LOWER(BTRIM(child.category_name)) = LOWER(BTRIM(parent.category_name))
          );

        UPDATE dim.dim_influencer_product p
        SET category_id = child.category_id,
            updated_at = NOW()
        FROM dim.dim_influencer_product_category parent
        JOIN dim.dim_influencer_product_category child
          ON child.parent_category_id = parent.category_id
         AND child.category_level = 2
         AND LOWER(BTRIM(child.category_name)) = LOWER(BTRIM(parent.category_name))
        WHERE p.category_id = parent.category_id
          AND parent.category_level = 1;

        EXECUTE $sql$
            INSERT INTO dim.dim_influencer_product (
                product_id,
                category_id,
                product_name,
                maintenance_source
            )
            SELECT DISTINCT
                'PRD-' || UPPER(SUBSTRING(MD5(
                    LOWER(BTRIM(m.large_product_category)) || '|' ||
                    LOWER(BTRIM(COALESCE(NULLIF(m.product_category_l2, ''), m.large_product_category))) || '|' ||
                    LOWER(BTRIM(m.product_name))
                ) FROM 1 FOR 16)),
                child.category_id,
                BTRIM(m.product_name),
                'file'
            FROM dim.dim_company_product_code_mapping m
            JOIN dim.dim_influencer_product_category parent
              ON parent.category_level = 1
             AND LOWER(BTRIM(parent.category_name)) = LOWER(BTRIM(m.large_product_category))
            JOIN dim.dim_influencer_product_category child
              ON child.category_level = 2
             AND child.parent_category_id = parent.category_id
             AND LOWER(BTRIM(child.category_name)) =
                 LOWER(BTRIM(COALESCE(NULLIF(m.product_category_l2, ''), m.large_product_category)))
            ON CONFLICT (product_id) DO NOTHING
        $sql$;

        EXECUTE $sql$
            UPDATE dim.dim_company_product_code_mapping m
            SET product_id = p.product_id,
                updated_at = NOW()
            FROM dim.dim_influencer_product p
            JOIN dim.dim_influencer_product_category child
              ON child.category_id = p.category_id
             AND child.category_level = 2
            JOIN dim.dim_influencer_product_category parent
              ON parent.category_id = child.parent_category_id
             AND parent.category_level = 1
            WHERE LOWER(BTRIM(parent.category_name)) = LOWER(BTRIM(m.large_product_category))
              AND LOWER(BTRIM(child.category_name)) =
                  LOWER(BTRIM(COALESCE(NULLIF(m.product_category_l2, ''), m.large_product_category)))
              AND LOWER(BTRIM(p.product_name)) = LOWER(BTRIM(m.product_name))
        $sql$;

        EXECUTE 'ALTER TABLE dim.dim_company_product_code_mapping ALTER COLUMN large_product_category DROP NOT NULL';
        EXECUTE 'ALTER TABLE dim.dim_company_product_code_mapping ALTER COLUMN product_name DROP NOT NULL';
        EXECUTE 'ALTER TABLE dim.dim_company_product_code_mapping RENAME COLUMN large_product_category TO legacy_large_product_category';
        EXECUTE 'ALTER TABLE dim.dim_company_product_code_mapping RENAME COLUMN product_category_l2 TO legacy_product_category_l2';
        EXECUTE 'ALTER TABLE dim.dim_company_product_code_mapping RENAME COLUMN product_name TO legacy_product_name';
    END IF;
END
$migration$;

ALTER TABLE dim.dim_influencer_product_category
    ALTER COLUMN category_level SET NOT NULL,
    ALTER COLUMN category_code SET NOT NULL;

ALTER TABLE dim.dim_company_product_code_mapping
    ALTER COLUMN product_id SET NOT NULL;

UPDATE dim.dim_company_product_code_mapping
SET source_code_pattern = code_pattern
WHERE mapping_source = 'file'
  AND source_code_pattern IS NULL;

DO $constraints$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_influencer_product_category_parent') THEN
        ALTER TABLE dim.dim_influencer_product_category
            ADD CONSTRAINT fk_influencer_product_category_parent
            FOREIGN KEY (parent_category_id)
            REFERENCES dim.dim_influencer_product_category (category_id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_influencer_product_category_level') THEN
        ALTER TABLE dim.dim_influencer_product_category
            ADD CONSTRAINT ck_influencer_product_category_level
            CHECK (
                (category_level = 1 AND parent_category_id IS NULL)
                OR (category_level = 2 AND parent_category_id IS NOT NULL)
            );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_influencer_product_category_source') THEN
        ALTER TABLE dim.dim_influencer_product_category
            ADD CONSTRAINT ck_influencer_product_category_source
            CHECK (maintenance_source IN ('file', 'manual'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_influencer_product_source') THEN
        ALTER TABLE dim.dim_influencer_product
            ADD CONSTRAINT ck_influencer_product_source
            CHECK (maintenance_source IN ('file', 'manual'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_company_product_code_mapping_product') THEN
        ALTER TABLE dim.dim_company_product_code_mapping
            ADD CONSTRAINT fk_company_product_code_mapping_product
            FOREIGN KEY (product_id)
            REFERENCES dim.dim_influencer_product (product_id)
            ON DELETE RESTRICT;
    END IF;
END
$constraints$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_influencer_product_category_code
    ON dim.dim_influencer_product_category (category_code);

CREATE UNIQUE INDEX IF NOT EXISTS uq_influencer_product_category_l1_name
    ON dim.dim_influencer_product_category (LOWER(BTRIM(category_name)))
    WHERE category_level = 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_influencer_product_category_l2_parent_name
    ON dim.dim_influencer_product_category (parent_category_id, LOWER(BTRIM(category_name)))
    WHERE category_level = 2;

CREATE INDEX IF NOT EXISTS idx_influencer_product_category_tree
    ON dim.dim_influencer_product_category (category_level, parent_category_id, is_active);

DROP INDEX IF EXISTS dim.idx_company_product_code_mapping_product;

CREATE INDEX IF NOT EXISTS idx_company_product_code_mapping_product
    ON dim.dim_company_product_code_mapping (product_id, is_active);

CREATE INDEX IF NOT EXISTS idx_company_product_code_mapping_active
    ON dim.dim_company_product_code_mapping (is_active, match_rule, code_prefix);

COMMENT ON TABLE dim.dim_influencer_product_category IS '达播运营公司统一商品分类DIM；一级分类通过父子关系包含多个二级分类，网页修改后用于产品GMV占比。';
COMMENT ON COLUMN dim.dim_influencer_product_category.category_id IS '商品分类代理主键。';
COMMENT ON COLUMN dim.dim_influencer_product_category.category_name IS '分类展示名称；一级分类全局唯一，二级分类在同一一级分类内唯一。';
COMMENT ON COLUMN dim.dim_influencer_product_category.category_level IS '分类层级：1为一级分类，2为二级分类。';
COMMENT ON COLUMN dim.dim_influencer_product_category.parent_category_id IS '父分类ID；一级分类为空，二级分类必须指向一级分类。';
COMMENT ON COLUMN dim.dim_influencer_product_category.category_code IS '分类稳定编码；网页改名时保持不变，避免Excel再次导入后重复建类。';
COMMENT ON COLUMN dim.dim_influencer_product_category.maintenance_source IS '最近维护来源：file为产品编码Excel，manual为网页人工维护；人工维护不被文件覆盖。';
COMMENT ON COLUMN dim.dim_influencer_product_category.is_active IS '分类是否启用；停用后其产品映射不进入当前看板分类。';
COMMENT ON COLUMN dim.dim_influencer_product_category.created_at IS '分类首次创建时间。';
COMMENT ON COLUMN dim.dim_influencer_product_category.updated_at IS '分类最后修改时间。';

COMMENT ON TABLE dim.dim_influencer_product IS '公司统一商品主数据；每个商品归属一个二级分类，一个商品可关联多个平台原始编码。';
COMMENT ON COLUMN dim.dim_influencer_product.product_id IS '产品稳定业务主键；文件产品按原分类路径生成，网页产品自动生成。';
COMMENT ON COLUMN dim.dim_influencer_product.category_id IS '产品所属二级分类ID，关联dim_influencer_product_category。';
COMMENT ON COLUMN dim.dim_influencer_product.product_name IS '公司统一产品名称；看板按该名称跨平台、店铺和链接汇总。';
COMMENT ON COLUMN dim.dim_influencer_product.maintenance_source IS '最近维护来源：file或manual；网页修改后的归属和名称不被文件覆盖。';
COMMENT ON COLUMN dim.dim_influencer_product.is_active IS '产品是否启用；停用产品的商家编码不会命中当前看板分类。';
COMMENT ON COLUMN dim.dim_influencer_product.created_at IS '产品首次创建时间。';
COMMENT ON COLUMN dim.dim_influencer_product.updated_at IS '产品最后修改时间。';

COMMENT ON TABLE dim.dim_company_product_code_mapping IS '平台原始商品编码到公司统一商品的映射DIM；同一商品允许关联多条编码。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.mapping_id IS '商家编码映射代理主键。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.product_id IS '统一产品ID，关联dim.dim_influencer_product；分类与产品名称必须沿该外键获取。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.source_product_category IS '产品编码Excel首列原值，仅用于来源审计。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.legacy_large_product_category IS '迁移前一级分类快照，仅审计使用，不参与看板计算。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.legacy_product_category_l2 IS '迁移前二级分类快照，仅审计使用，不参与看板计算。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.legacy_product_name IS '迁移前产品名称快照，仅审计使用，不参与看板计算。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.code_pattern IS '标准化商家编码；数量后缀规则用X占位，例如M-NXSY-X。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.source_code_pattern IS '文件来源编码稳定键；网页修改文件记录的编码后保留原值，防止后续Excel导入把原记录重复新增。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.code_prefix IS '数量后缀匹配前缀；exact规则为空。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.match_rule IS '匹配规则：exact完整匹配，suffix_quantity匹配编码前缀加正整数数量。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.code_role IS '包装角色：box常规商品，sachet小袋；不直接决定赠品。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.mapping_source IS '最近维护来源：file或manual；网页修改后的编码归属不被文件覆盖。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.source_file_name IS '最近文件导入来源文件名；人工新增可为空。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.source_sheet_name IS '最近文件导入来源Sheet。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.source_row_no IS '最近文件导入来源行号。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.is_active IS '编码映射是否启用；停用后不参与订单产品匹配。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.created_at IS '编码映射首次创建时间。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.updated_at IS '编码映射最后修改时间。';
