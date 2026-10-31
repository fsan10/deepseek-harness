CREATE SCHEMA IF NOT EXISTS dim;

CREATE TABLE IF NOT EXISTS dim.dim_expense_type (
    id BIGSERIAL PRIMARY KEY,
    code VARCHAR(20) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL UNIQUE,
    description VARCHAR(500) NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dim.dim_account_entry (
    id BIGSERIAL PRIMARY KEY,
    code VARCHAR(20) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL UNIQUE,
    description VARCHAR(500) NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dim.dim_account_entry_expense_type (
    account_entry_id BIGINT NOT NULL REFERENCES dim.dim_account_entry(id) ON DELETE CASCADE,
    expense_type_id BIGINT NOT NULL REFERENCES dim.dim_expense_type(id) ON DELETE RESTRICT,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account_entry_id, expense_type_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_dim_account_entry_one_default
    ON dim.dim_account_entry_expense_type (account_entry_id) WHERE is_default;

COMMENT ON TABLE dim.dim_expense_type IS 'DIM层-银行资金流水费用类型维度。';
COMMENT ON COLUMN dim.dim_expense_type.id IS '费用类型代理主键。';
COMMENT ON COLUMN dim.dim_expense_type.code IS '费用类型编码，格式EXP加三位递增序号。';
COMMENT ON COLUMN dim.dim_expense_type.name IS '费用类型名称，全局唯一。';
COMMENT ON COLUMN dim.dim_expense_type.description IS '费用类型业务说明。';
COMMENT ON COLUMN dim.dim_expense_type.sort_order IS '展示排序，数值越小越靠前。';
COMMENT ON COLUMN dim.dim_expense_type.is_active IS '是否启用；停用后不可用于新分配。';
COMMENT ON COLUMN dim.dim_expense_type.created_at IS '创建时间，带时区。';
COMMENT ON COLUMN dim.dim_expense_type.updated_at IS '最后更新时间，带时区。';
COMMENT ON TABLE dim.dim_account_entry IS 'DIM层-银行资金流水入账科目维度；一个科目可通过桥接表允许多个费用类型。';
COMMENT ON COLUMN dim.dim_account_entry.id IS '入账科目代理主键。';
COMMENT ON COLUMN dim.dim_account_entry.code IS '入账科目编码，格式ACC加三位递增序号。';
COMMENT ON COLUMN dim.dim_account_entry.name IS '入账科目名称，全局唯一。';
COMMENT ON COLUMN dim.dim_account_entry.description IS '入账科目业务说明。';
COMMENT ON COLUMN dim.dim_account_entry.sort_order IS '展示排序，数值越小越靠前。';
COMMENT ON COLUMN dim.dim_account_entry.is_active IS '是否启用；停用后不可用于新分配。';
COMMENT ON COLUMN dim.dim_account_entry.created_at IS '创建时间，带时区。';
COMMENT ON COLUMN dim.dim_account_entry.updated_at IS '最后更新时间，带时区。';
COMMENT ON TABLE dim.dim_account_entry_expense_type IS 'DIM层-入账科目与允许费用类型的多对多关系，解决同名科目跨费用类型归属。';
COMMENT ON COLUMN dim.dim_account_entry_expense_type.account_entry_id IS '入账科目ID，来源dim.dim_account_entry。';
COMMENT ON COLUMN dim.dim_account_entry_expense_type.expense_type_id IS '允许归属的费用类型ID，来源dim.dim_expense_type。';
COMMENT ON COLUMN dim.dim_account_entry_expense_type.is_default IS '是否为该入账科目的默认费用类型；每科目最多一个。';
COMMENT ON COLUMN dim.dim_account_entry_expense_type.created_at IS '关系创建时间，带时区。';

