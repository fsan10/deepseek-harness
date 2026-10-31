CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_ks_order_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "订单号" TEXT,
    "赠品订单号" TEXT,
    "活动订单编号" TEXT,
    "订单创建时间" TEXT,
    "订单支付时间" TEXT,
    "预售定金支付时间" TEXT,
    "订单状态" TEXT,
    "实付款" TEXT,
    "快递费" TEXT,
    "店铺优惠" TEXT,
    "平台补贴" TEXT,
    "主播补贴" TEXT,
    "混资活动优惠" TEXT,
    "支付优惠" TEXT,
    "支付方式" TEXT,
    "成交数量" TEXT,
    "买家留言" TEXT,
    "账号类型" TEXT,
    "账号明细" TEXT,
    "订单备注" TEXT,
    "旗帜颜色" TEXT,
    "售后状态" TEXT,
    "活动订单" TEXT,
    "预售/承诺发货时间" TEXT,
    "订单载体" TEXT,
    "商品名称" TEXT,
    "商品ID" TEXT,
    "商品规格" TEXT,
    "SKU编码" TEXT,
    "商品单价" TEXT,
    "渠道" TEXT,
    "CPS达人ID" TEXT,
    "CPS达人昵称" TEXT,
    "预估推广佣金" TEXT,
    "预估推广者分佣比例" TEXT,
    "团长ID" TEXT,
    "团长昵称" TEXT,
    "快赚客ID" TEXT,
    "快赚客昵称" TEXT,
    "授权推广者ID" TEXT,
    "授权推广者昵称" TEXT,
    "收货人姓名" TEXT,
    "收货人电话" TEXT,
    "收货地址-省" TEXT,
    "收货地址-市" TEXT,
    "收货地址-区" TEXT,
    "收货地址-街道" TEXT,
    "收货地址" TEXT,
    "发货时间" TEXT,
    "快递公司" TEXT,
    "快递单号" TEXT,
    "物流信息" TEXT,
    "集运类型" TEXT,
    "直邮类型" TEXT,
    "仓库名称" TEXT,
    "仓库地址" TEXT,
    "发货类型" TEXT,
    "实名姓名" TEXT,
    "服务门店ID" TEXT,
    "服务门店名称" TEXT,
    "服务门店地址" TEXT,
    "国补/类国补/消费券" TEXT,

    CONSTRAINT uk_ods_ks_order_row_hash UNIQUE (row_hash)
);

CREATE INDEX IF NOT EXISTS idx_ods_ks_order_order_no ON ods.ods_ks_order_raw ("订单号");
CREATE INDEX IF NOT EXISTS idx_ods_ks_order_product_id ON ods.ods_ks_order_raw ("商品ID");
CREATE INDEX IF NOT EXISTS idx_ods_ks_order_sku_code ON ods.ods_ks_order_raw ("SKU编码");
CREATE INDEX IF NOT EXISTS idx_ods_ks_order_cps_daren_id ON ods.ods_ks_order_raw ("CPS达人ID");
CREATE INDEX IF NOT EXISTS idx_ods_ks_order_source_file ON ods.ods_ks_order_raw (source_file_name);
CREATE INDEX IF NOT EXISTS idx_ods_ks_order_batch_id ON ods.ods_ks_order_raw (batch_id);

COMMENT ON TABLE ods.ods_ks_order_raw IS 'ODS快手订单原始表，按平台导出订单文件表头原样保存。';
COMMENT ON COLUMN ods.ods_ks_order_raw.batch_id IS '导入批次ID，可关联ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_ks_order_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_ks_order_raw.source_sheet_name IS '来源Sheet名，CSV固定为CSV';
COMMENT ON COLUMN ods.ods_ks_order_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_ks_order_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_ks_order_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_ks_order_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_ks_order_raw."订单号" IS '来源文件字段“订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."赠品订单号" IS '来源文件字段“赠品订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."活动订单编号" IS '来源文件字段“活动订单编号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."订单创建时间" IS '来源文件字段“订单创建时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."订单支付时间" IS '来源文件字段“订单支付时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."预售定金支付时间" IS '来源文件字段“预售定金支付时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."订单状态" IS '来源文件字段“订单状态”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."实付款" IS '来源文件字段“实付款”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."快递费" IS '来源文件字段“快递费”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."店铺优惠" IS '来源文件字段“店铺优惠”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."平台补贴" IS '来源文件字段“平台补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."主播补贴" IS '来源文件字段“主播补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."混资活动优惠" IS '来源文件字段“混资活动优惠”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."支付优惠" IS '来源文件字段“支付优惠”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."支付方式" IS '来源文件字段“支付方式”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."成交数量" IS '来源文件字段“成交数量”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."买家留言" IS '来源文件字段“买家留言”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."账号类型" IS '来源文件字段“账号类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."账号明细" IS '来源文件字段“账号明细”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."订单备注" IS '来源文件字段“订单备注”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."旗帜颜色" IS '来源文件字段“旗帜颜色”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."售后状态" IS '来源文件字段“售后状态”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."活动订单" IS '来源文件字段“活动订单”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."预售/承诺发货时间" IS '来源文件字段“预售/承诺发货时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."订单载体" IS '来源文件字段“订单载体”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."商品名称" IS '来源文件字段“商品名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."商品ID" IS '来源文件字段“商品ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."商品规格" IS '来源文件字段“商品规格”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."SKU编码" IS '来源文件字段“SKU编码”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."商品单价" IS '来源文件字段“商品单价”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."渠道" IS '来源文件字段“渠道”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."CPS达人ID" IS '来源文件字段“CPS达人ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."CPS达人昵称" IS '来源文件字段“CPS达人昵称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."预估推广佣金" IS '来源文件字段“预估推广佣金”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."预估推广者分佣比例" IS '来源文件字段“预估推广者分佣比例”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."团长ID" IS '来源文件字段“团长ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."团长昵称" IS '来源文件字段“团长昵称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."快赚客ID" IS '来源文件字段“快赚客ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."快赚客昵称" IS '来源文件字段“快赚客昵称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."授权推广者ID" IS '来源文件字段“授权推广者ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."授权推广者昵称" IS '来源文件字段“授权推广者昵称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."收货人姓名" IS '来源文件字段“收货人姓名”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."收货人电话" IS '来源文件字段“收货人电话”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."收货地址-省" IS '来源文件字段“收货地址-省”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."收货地址-市" IS '来源文件字段“收货地址-市”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."收货地址-区" IS '来源文件字段“收货地址-区”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."收货地址-街道" IS '来源文件字段“收货地址-街道”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."收货地址" IS '来源文件字段“收货地址”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."发货时间" IS '来源文件字段“发货时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."快递公司" IS '来源文件字段“快递公司”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."快递单号" IS '来源文件字段“快递单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."物流信息" IS '来源文件字段“物流信息”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."集运类型" IS '来源文件字段“集运类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."直邮类型" IS '来源文件字段“直邮类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."仓库名称" IS '来源文件字段“仓库名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."仓库地址" IS '来源文件字段“仓库地址”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."发货类型" IS '来源文件字段“发货类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."实名姓名" IS '来源文件字段“实名姓名”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."服务门店ID" IS '来源文件字段“服务门店ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."服务门店名称" IS '来源文件字段“服务门店名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."服务门店地址" IS '来源文件字段“服务门店地址”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_order_raw."国补/类国补/消费券" IS '来源文件字段“国补/类国补/消费券”，保留平台导出的原始值。';
