CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_douyin_order_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "主订单编号" VARCHAR(128),
    "子订单编号" VARCHAR(128),
    "选购商品" TEXT,
    "商品规格" TEXT,
    "商品数量" VARCHAR(64),
    "商品ID" VARCHAR(128),
    "商家编码" VARCHAR(128),
    "商品单价" VARCHAR(64),
    "订单应付金额" VARCHAR(64),
    "运费" VARCHAR(64),
    "优惠总金额" VARCHAR(64),
    "平台优惠" VARCHAR(64),
    "商家优惠" VARCHAR(64),
    "达人优惠" VARCHAR(64),
    "商家改价" VARCHAR(64),
    "支付优惠" VARCHAR(64),
    "红包抵扣" VARCHAR(64),
    "支付方式" VARCHAR(128),
    "手续费" VARCHAR(64),
    "收件人" VARCHAR(255),
    "收件人手机号" TEXT,
    "省" VARCHAR(128),
    "市" VARCHAR(128),
    "区" VARCHAR(128),
    "街道" VARCHAR(255),
    "详细地址" TEXT,
    "是否修改过地址" VARCHAR(64),
    "地址修改时段" VARCHAR(128),
    "买家留言" TEXT,
    "订单提交时间" VARCHAR(64),
    "旗帜颜色" VARCHAR(64),
    "商家备注" TEXT,
    "订单完成时间" VARCHAR(64),
    "支付完成时间" VARCHAR(64),
    "APP渠道" VARCHAR(128),
    "流量来源" VARCHAR(128),
    "订单状态" VARCHAR(128),
    "承诺发货时间" VARCHAR(64),
    "订单类型" VARCHAR(128),
    "鲁班落地页ID" VARCHAR(128),
    "达人ID" VARCHAR(128),
    "达人昵称" VARCHAR(255),
    "所属门店ID" VARCHAR(128),
    "售后状态" VARCHAR(128),
    "取消原因" TEXT,
    "预约发货时间" VARCHAR(64),
    "仓库ID" VARCHAR(128),
    "仓库名称" VARCHAR(255),
    "是否安心购" VARCHAR(64),
    "广告渠道" VARCHAR(128),
    "流量类型" VARCHAR(128),
    "流量体裁" VARCHAR(128),
    "流量渠道" VARCHAR(128),
    "发货主体" VARCHAR(128),
    "发货主体明细" VARCHAR(255),
    "发货时间" VARCHAR(64),
    "降价类优惠" VARCHAR(64),
    "平台实际承担优惠金额" VARCHAR(64),
    "商家实际承担优惠金额" VARCHAR(64),
    "达人实际承担优惠金额" VARCHAR(64),
    "预计送达时间" VARCHAR(64),
    "是否平台仓自流转" VARCHAR(64),
    "车型" VARCHAR(128),
    "商品69码" VARCHAR(128),
    "发货SN码" VARCHAR(255),
    "发货IMEI码1" VARCHAR(255),
    "发货IMEI码2" VARCHAR(255),
    "是否福袋订单" VARCHAR(64),
    "福袋采购订单号" VARCHAR(128),
    "福袋采购订单状态" VARCHAR(128),
    "福袋采购订单采购方ID" VARCHAR(128),
    "福袋采购订单采购方名称" VARCHAR(255),
    "福袋采购订单创建时间" VARCHAR(64),
    "福袋采购订单支付时间" VARCHAR(64),
    "福袋采购订单订单应付金额" VARCHAR(64),
    "福袋采购订单订单实际付款金额" VARCHAR(64),
    "福袋采购订单订单优惠金额" VARCHAR(64),
    "福袋采购订单商品ID" VARCHAR(128),
    "福袋采购订单商品名称" TEXT,
    "福袋采购订单商品单价" VARCHAR(64),
    "福袋采购订单商品数量" VARCHAR(64),
    "福袋采购订单核销数量" VARCHAR(64),
    "福袋采购订单结算数量" VARCHAR(64),
    "预约送达时间" VARCHAR(64),
    "建议发货时间（起）" VARCHAR(64),
    "建议发货时间（止）" VARCHAR(64),
    "物流SN码" VARCHAR(255),
    "物流IMEI码1" VARCHAR(255),
    "物流IMEI码2" VARCHAR(255),

    CONSTRAINT uk_ods_douyin_order_row_hash UNIQUE (row_hash)
);

CREATE INDEX IF NOT EXISTS idx_ods_douyin_order_main_order_no
    ON ods.ods_douyin_order_raw ("主订单编号");

CREATE INDEX IF NOT EXISTS idx_ods_douyin_order_sub_order_no
    ON ods.ods_douyin_order_raw ("子订单编号");

CREATE INDEX IF NOT EXISTS idx_ods_douyin_order_product_id
    ON ods.ods_douyin_order_raw ("商品ID");

CREATE INDEX IF NOT EXISTS idx_ods_douyin_order_daren_id
    ON ods.ods_douyin_order_raw ("达人ID");

CREATE INDEX IF NOT EXISTS idx_ods_douyin_order_source_file
    ON ods.ods_douyin_order_raw (source_file_name);

CREATE INDEX IF NOT EXISTS idx_ods_douyin_order_batch_id
    ON ods.ods_douyin_order_raw (batch_id);

COMMENT ON TABLE ods.ods_douyin_order_raw IS 'ODS抖音订单原始表，按源文件表头保存；收件人、手机号和详细地址统一掩码。';
COMMENT ON COLUMN ods.ods_douyin_order_raw.batch_id IS '导入批次ID，可关联ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_douyin_order_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_douyin_order_raw.source_sheet_name IS '来源Sheet名，CSV固定为CSV';
COMMENT ON COLUMN ods.ods_douyin_order_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_douyin_order_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_douyin_order_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_douyin_order_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."主订单编号" IS '来源文件字段“主订单编号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."子订单编号" IS '来源文件字段“子订单编号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."选购商品" IS '来源文件字段“选购商品”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."商品规格" IS '来源文件字段“商品规格”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."商品数量" IS '来源文件字段“商品数量”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."商品ID" IS '来源文件字段“商品ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."商家编码" IS '来源文件字段“商家编码”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."商品单价" IS '来源文件字段“商品单价”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."订单应付金额" IS '来源文件字段“订单应付金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."运费" IS '来源文件字段“运费”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."优惠总金额" IS '来源文件字段“优惠总金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."平台优惠" IS '来源文件字段“平台优惠”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."商家优惠" IS '来源文件字段“商家优惠”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."达人优惠" IS '来源文件字段“达人优惠”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."商家改价" IS '来源文件字段“商家改价”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."支付优惠" IS '来源文件字段“支付优惠”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."红包抵扣" IS '来源文件字段“红包抵扣”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."支付方式" IS '来源文件字段“支付方式”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."手续费" IS '来源文件字段“手续费”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."收件人" IS '来源文件字段“收件人”，入ODS前统一掩码为***，不保存原始收件人信息。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."收件人手机号" IS '来源文件字段“收件人手机号”，入ODS前统一掩码为***，不保存原始手机号信息。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."省" IS '来源文件字段“省”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."市" IS '来源文件字段“市”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."区" IS '来源文件字段“区”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."街道" IS '来源文件字段“街道”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."详细地址" IS '来源文件字段“详细地址”，入ODS前统一掩码为***，不保存原始地址信息。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."是否修改过地址" IS '来源文件字段“是否修改过地址”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."地址修改时段" IS '来源文件字段“地址修改时段”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."买家留言" IS '来源文件字段“买家留言”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."订单提交时间" IS '来源文件字段“订单提交时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."旗帜颜色" IS '来源文件字段“旗帜颜色”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."商家备注" IS '来源文件字段“商家备注”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."订单完成时间" IS '来源文件字段“订单完成时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."支付完成时间" IS '来源文件字段“支付完成时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."APP渠道" IS '来源文件字段“APP渠道”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."流量来源" IS '来源文件字段“流量来源”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."订单状态" IS '来源文件字段“订单状态”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."承诺发货时间" IS '来源文件字段“承诺发货时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."订单类型" IS '来源文件字段“订单类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."鲁班落地页ID" IS '来源文件字段“鲁班落地页ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."达人ID" IS '来源文件字段“达人ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."达人昵称" IS '来源文件字段“达人昵称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."所属门店ID" IS '来源文件字段“所属门店ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."售后状态" IS '来源文件字段“售后状态”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."取消原因" IS '来源文件字段“取消原因”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."预约发货时间" IS '来源文件字段“预约发货时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."仓库ID" IS '来源文件字段“仓库ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."仓库名称" IS '来源文件字段“仓库名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."是否安心购" IS '来源文件字段“是否安心购”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."广告渠道" IS '来源文件字段“广告渠道”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."流量类型" IS '来源文件字段“流量类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."流量体裁" IS '来源文件字段“流量体裁”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."流量渠道" IS '来源文件字段“流量渠道”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."发货主体" IS '来源文件字段“发货主体”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."发货主体明细" IS '来源文件字段“发货主体明细”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."发货时间" IS '来源文件字段“发货时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."降价类优惠" IS '来源文件字段“降价类优惠”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."平台实际承担优惠金额" IS '来源文件字段“平台实际承担优惠金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."商家实际承担优惠金额" IS '来源文件字段“商家实际承担优惠金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."达人实际承担优惠金额" IS '来源文件字段“达人实际承担优惠金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."预计送达时间" IS '来源文件字段“预计送达时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."是否平台仓自流转" IS '来源文件字段“是否平台仓自流转”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."车型" IS '来源文件字段“车型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."商品69码" IS '来源文件字段“商品69码”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."发货SN码" IS '来源文件字段“发货SN码”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."发货IMEI码1" IS '来源文件字段“发货IMEI码1”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."发货IMEI码2" IS '来源文件字段“发货IMEI码2”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."是否福袋订单" IS '来源文件字段“是否福袋订单”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."福袋采购订单号" IS '来源文件字段“福袋采购订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."福袋采购订单状态" IS '来源文件字段“福袋采购订单状态”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."福袋采购订单采购方ID" IS '来源文件字段“福袋采购订单采购方ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."福袋采购订单采购方名称" IS '来源文件字段“福袋采购订单采购方名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."福袋采购订单创建时间" IS '来源文件字段“福袋采购订单创建时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."福袋采购订单支付时间" IS '来源文件字段“福袋采购订单支付时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."福袋采购订单订单应付金额" IS '来源文件字段“福袋采购订单订单应付金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."福袋采购订单订单实际付款金额" IS '来源文件字段“福袋采购订单订单实际付款金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."福袋采购订单订单优惠金额" IS '来源文件字段“福袋采购订单订单优惠金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."福袋采购订单商品ID" IS '来源文件字段“福袋采购订单商品ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."福袋采购订单商品名称" IS '来源文件字段“福袋采购订单商品名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."福袋采购订单商品单价" IS '来源文件字段“福袋采购订单商品单价”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."福袋采购订单商品数量" IS '来源文件字段“福袋采购订单商品数量”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."福袋采购订单核销数量" IS '来源文件字段“福袋采购订单核销数量”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."福袋采购订单结算数量" IS '来源文件字段“福袋采购订单结算数量”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."预约送达时间" IS '来源文件字段“预约送达时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."建议发货时间（起）" IS '来源文件字段“建议发货时间（起）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."建议发货时间（止）" IS '来源文件字段“建议发货时间（止）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."物流SN码" IS '来源文件字段“物流SN码”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."物流IMEI码1" IS '来源文件字段“物流IMEI码1”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."物流IMEI码2" IS '来源文件字段“物流IMEI码2”，保留平台导出的原始值。';
