CREATE SCHEMA IF NOT EXISTS dws;

DROP VIEW IF EXISTS common.v_operating_sales_product_code_observation;
DROP TABLE IF EXISTS dws.dws_tmall_operating_sales_product_allocation;
DROP TABLE IF EXISTS dws.dws_pdd_operating_sales_product_allocation;
DROP TABLE IF EXISTS dws.dws_xhs_operating_sales_product_allocation;
DROP TABLE IF EXISTS dws.dws_ks_operating_sales_product_allocation;
DROP TABLE IF EXISTS dws.dws_jd_operating_sales_product_allocation;
DROP TABLE IF EXISTS dws.dws_wechat_channels_operating_sales_product_allocation;
DROP TABLE IF EXISTS dws.dws_douyin_operating_sales_product_allocation;

CREATE TABLE dws.dws_douyin_operating_sales_product_allocation (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    main_order_no VARCHAR(128) NOT NULL,
    sub_order_no VARCHAR(128) NOT NULL,
    merchant_code VARCHAR(512) NOT NULL,
    source_product_name TEXT,
    product_spec TEXT,
    source_component_count SMALLINT NOT NULL,
    paid_component_count SMALLINT NOT NULL,
    component_index SMALLINT NOT NULL,
    raw_merchant_code_component VARCHAR(512) NOT NULL,
    normalization_rule_id BIGINT,
    merchant_code_component VARCHAR(128) NOT NULL,
    code_expression VARCHAR(128) NOT NULL,
    quantity_position VARCHAR(16) NOT NULL,
    product_mapping_id BIGINT,
    company_product_id VARCHAR(128),
    company_product_code VARCHAR(128),
    product_type VARCHAR(32),
    large_product_category VARCHAR(128) NOT NULL,
    product_category_l2 VARCHAR(128) NOT NULL,
    product_name VARCHAR(255) NOT NULL,
    code_role VARCHAR(32) NOT NULL,
    mapping_pattern VARCHAR(128),
    component_quantity NUMERIC(18,2) NOT NULL,
    paid_quantity NUMERIC(18,2) NOT NULL,
    gift_quantity NUMERIC(18,2) NOT NULL,
    is_gift BOOLEAN NOT NULL,
    allocation_weight NUMERIC(18,10) NOT NULL,
    source_line_gmv_amount NUMERIC(18,2) NOT NULL,
    allocated_gmv_amount NUMERIC(18,2) NOT NULL,
    is_mapped BOOLEAN NOT NULL,
    source_id BIGINT NOT NULL,
    source_batch_id BIGINT NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (platform_code, shop_code, sub_order_no, component_index),
    CONSTRAINT ck_product_allocation_component_counts CHECK (
        source_component_count > 0
        AND paid_component_count >= 0
        AND paid_component_count <= source_component_count
        AND component_index > 0
        AND component_index <= source_component_count
    ),
    CONSTRAINT ck_product_allocation_quantity CHECK (
        component_quantity > 0
        AND paid_quantity >= 0
        AND gift_quantity >= 0
        AND paid_quantity + gift_quantity = component_quantity
    ),
    CONSTRAINT ck_product_allocation_weight CHECK (
        allocation_weight >= 0 AND allocation_weight <= 1
    ),
    CONSTRAINT ck_product_allocation_gift_gmv CHECK (
        NOT is_gift OR (paid_quantity = 0 AND allocated_gmv_amount = 0)
    )
);

COMMENT ON TABLE dws.dws_douyin_operating_sales_product_allocation IS '七平台共用结构的商品组件分摊DWS基表；组合装全部组件均保留，赠品可识别可映射但GMV为0。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.stat_date IS '成交统计日期。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.platform_code IS '订单来源平台编码，仅用于追溯和统计，不参与商品映射。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.platform_name IS '订单来源平台名称。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.shop_code IS '订单来源标准店铺编码，仅用于追溯和统计。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.shop_name IS '订单来源标准店铺名称。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.main_order_no IS '来源主订单编号。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.sub_order_no IS '来源子订单编号。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.merchant_code IS '订单行完整原始商家编码，统一全角加号后保留。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.source_product_name IS '来源平台商品名称，用于赠品审计。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.product_spec IS '来源商品规格，用于识别赠字前后的付费与赠品组件。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.source_component_count IS '完整编码按加号拆出的全部组件数。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.paid_component_count IS '本订单行paid_quantity大于0的组件数。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.component_index IS '组件在完整编码中的1起始顺序。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.raw_merchant_code_component IS '按原始加号首次拆分得到的组件；即使后续修正规则再次拆分也保持原值。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.normalization_rule_id IS '命中的公司级编码组件修正规则ID；未修正为空。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.merchant_code_component IS '应用编码修正规则后、进入商品身份与数量解析的标准组件。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.code_expression IS '从组件剥离数量后的公司编码或别名表达。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.quantity_position IS '解析到的数量位置：suffix、prefix或none。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.product_mapping_id IS '命中的公司级编码规则ID，未映射为空。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.company_product_id IS '公司商品稳定ID，未映射为空。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.company_product_code IS '公司统一业务商品编码，未映射为空。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.product_type IS '公司商品类型，未映射为空。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.large_product_category IS '公司商品一级分类，未映射显示未配置。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.product_category_l2 IS '公司商品二级分类，未映射显示未配置。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.product_name IS '公司商品名称，未映射显示未配置。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.code_role IS '历史包装角色，仅用于兼容审计，不决定商品身份。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.mapping_pattern IS '命中的公司级编码表达规则。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.component_quantity IS '由原始组件数字解析的总数量。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.paid_quantity IS '参与GMV权重分母的实际付费数量。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.gift_quantity IS '不参与GMV权重的赠品数量；可与付费数量同属一个原始组件。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.is_gift IS '该组件是否为纯赠品组件；混合付费和赠品组件以gift_quantity保留赠品数量。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.allocation_weight IS 'paid_quantity除以同一订单行总付费数量；赠品为0。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.source_line_gmv_amount IS '来源订单行商品GMV，组件间重复，仅供逐行核验。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.allocated_gmv_amount IS '按付费数量分摊的GMV；赠品严格为0，最后一个付费组件吸收分币差。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.is_mapped IS '编码表达是否命中启用的公司商品规则和启用商品。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.source_id IS '来源运营成交DWD记录ID。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.source_batch_id IS '来源订单导入批次ID。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.source_updated_at IS '来源记录更新时间。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_product_allocation.updated_at IS 'DWS记录刷新时间。';

CREATE INDEX idx_dws_douyin_product_allocation_date_shop
    ON dws.dws_douyin_operating_sales_product_allocation (stat_date, shop_code);
CREATE INDEX idx_dws_douyin_product_allocation_product
    ON dws.dws_douyin_operating_sales_product_allocation (company_product_id, stat_date);
CREATE INDEX idx_dws_douyin_product_allocation_observation
    ON dws.dws_douyin_operating_sales_product_allocation (
        code_expression, quantity_position, is_mapped
    );
