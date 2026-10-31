CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_wechat_channels_order_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "订单号" TEXT,
    "订单下单时间" TEXT,
    "订单发货时间" TEXT,
    "订单确认收货时间" TEXT,
    "订单完成结算时间" TEXT,
    "订单状态" TEXT,
    "发货方式" TEXT,
    "收件人姓名" TEXT,
    "收件人地址" TEXT,
    "省" TEXT,
    "市" TEXT,
    "区" TEXT,
    "收件人手机" TEXT,
    "买家备注" TEXT,
    "商家备注" TEXT,
    "打标颜色" TEXT,
    "商品总价" TEXT,
    "订单实际支付金额" TEXT,
    "订单实际收款金额" TEXT,
    "订单运费" TEXT,
    "商家优惠" TEXT,
    "平台优惠" TEXT,
    "跨店优惠" TEXT,
    "商品改价" TEXT,
    "积分抵扣" TEXT,
    "支付方式" TEXT,
    "支付时间" TEXT,
    "交易单号" TEXT,
    "物流公司" TEXT,
    "快递单号" TEXT,
    "技术服务费" TEXT,
    "技术服务费（将以人气卡形式返还）" TEXT,
    "运费险预计投保费用" TEXT,
    "带货方式" TEXT,
    "带货账号类型" TEXT,
    "带货账号昵称" TEXT,
    "带货ID" TEXT,
    "带货费用渠道" TEXT,
    "带货费用类型" TEXT,
    "带货费用" TEXT,
    "带货佣金率" TEXT,
    "企微企业ID" TEXT,
    "企微工号" TEXT,
    "导购最近分享时间" TEXT,
    "企业微信加密id" TEXT,
    "企微备注" TEXT,
    "礼物单号" TEXT,
    "商品名称" TEXT,
    "商品编码(平台)" TEXT,
    "商品编码(自定义)" TEXT,
    "SKU编码(自定义)" TEXT,
    "商品属性" TEXT,
    "商品价格(单件)" TEXT,
    "商品实际价格(单件)" TEXT,
    "商品实际价格(总共)" TEXT,
    "是否预售" TEXT,
    "商品数量" TEXT,
    "商品平台券优惠" TEXT,
    "商品平均运费" TEXT,
    "活动商家补贴" TEXT,
    "定制信息" TEXT,
    "定制预览图" TEXT,
    "商品发货" TEXT,
    "商品售后" TEXT,
    "商品已退款金额" TEXT,

    CONSTRAINT uk_ods_wechat_channels_order_row_hash UNIQUE (row_hash)
);

CREATE INDEX IF NOT EXISTS idx_ods_wechat_channels_order_order_no ON ods.ods_wechat_channels_order_raw ("订单号");
CREATE INDEX IF NOT EXISTS idx_ods_wechat_channels_order_product_code ON ods.ods_wechat_channels_order_raw ("商品编码(平台)");
CREATE INDEX IF NOT EXISTS idx_ods_wechat_channels_order_daren_id ON ods.ods_wechat_channels_order_raw ("带货ID");
CREATE INDEX IF NOT EXISTS idx_ods_wechat_channels_order_source_file ON ods.ods_wechat_channels_order_raw (source_file_name);
CREATE INDEX IF NOT EXISTS idx_ods_wechat_channels_order_batch_id ON ods.ods_wechat_channels_order_raw (batch_id);

COMMENT ON TABLE ods.ods_wechat_channels_order_raw IS 'ODS视频号订单原始表，按平台导出订单文件表头原样保存。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw.batch_id IS '导入批次ID，可关联ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw.source_sheet_name IS '来源Sheet名，CSV固定为CSV';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_wechat_channels_order_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."订单号" IS '来源文件字段“订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."订单下单时间" IS '来源文件字段“订单下单时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."订单发货时间" IS '来源文件字段“订单发货时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."订单确认收货时间" IS '来源文件字段“订单确认收货时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."订单完成结算时间" IS '来源文件字段“订单完成结算时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."订单状态" IS '来源文件字段“订单状态”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."发货方式" IS '来源文件字段“发货方式”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."收件人姓名" IS '来源文件字段“收件人姓名”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."收件人地址" IS '来源文件字段“收件人地址”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."省" IS '来源文件字段“省”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."市" IS '来源文件字段“市”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."区" IS '来源文件字段“区”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."收件人手机" IS '来源文件字段“收件人手机”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."买家备注" IS '来源文件字段“买家备注”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商家备注" IS '来源文件字段“商家备注”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."打标颜色" IS '来源文件字段“打标颜色”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商品总价" IS '来源文件字段“商品总价”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."订单实际支付金额" IS '来源文件字段“订单实际支付金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."订单实际收款金额" IS '来源文件字段“订单实际收款金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."订单运费" IS '来源文件字段“订单运费”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商家优惠" IS '来源文件字段“商家优惠”，保留平台导出的原始值；旧版“商品优惠”表头由Loader兼容映射到本列。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."平台优惠" IS '来源文件字段“平台优惠”，保留平台导出的原始值；旧版未拆分文件为空。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."跨店优惠" IS '来源文件字段“跨店优惠”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商品改价" IS '来源文件字段“商品改价”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."积分抵扣" IS '来源文件字段“积分抵扣”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."支付方式" IS '来源文件字段“支付方式”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."支付时间" IS '来源文件字段“支付时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."交易单号" IS '来源文件字段“交易单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."物流公司" IS '来源文件字段“物流公司”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."快递单号" IS '来源文件字段“快递单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."技术服务费" IS '来源文件字段“技术服务费”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."技术服务费（将以人气卡形式返还）" IS '来源文件字段“技术服务费（将以人气卡形式返还）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."运费险预计投保费用" IS '来源文件字段“运费险预计投保费用”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."带货方式" IS '来源文件字段“带货方式”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."带货账号类型" IS '来源文件字段“带货账号类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."带货账号昵称" IS '来源文件字段“带货账号昵称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."带货ID" IS '来源文件字段“带货ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."带货费用渠道" IS '来源文件字段“带货费用渠道”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."带货费用类型" IS '来源文件字段“带货费用类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."带货费用" IS '来源文件字段“带货费用”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."带货佣金率" IS '来源文件字段“带货佣金率”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."企微企业ID" IS '来源文件字段“企微企业ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."企微工号" IS '来源文件字段“企微工号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."导购最近分享时间" IS '来源文件字段“导购最近分享时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."企业微信加密id" IS '来源文件字段“企业微信加密id”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."企微备注" IS '来源文件字段“企微备注”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."礼物单号" IS '来源文件字段“礼物单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商品名称" IS '来源文件字段“商品名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商品编码(平台)" IS '来源文件字段“商品编码(平台)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商品编码(自定义)" IS '来源文件字段“商品编码(自定义)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."SKU编码(自定义)" IS '来源文件字段“SKU编码(自定义)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商品属性" IS '来源文件字段“商品属性”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商品价格(单件)" IS '来源文件字段“商品价格(单件)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商品实际价格(单件)" IS '来源文件字段“商品实际价格(单件)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商品实际价格(总共)" IS '来源文件字段“商品实际价格(总共)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."是否预售" IS '来源文件字段“是否预售”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商品数量" IS '来源文件字段“商品数量”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商品平台券优惠" IS '来源文件字段“商品平台券优惠”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商品平均运费" IS '来源文件字段“商品平均运费”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."活动商家补贴" IS '来源文件字段“活动商家补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."定制信息" IS '来源文件字段“定制信息”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."定制预览图" IS '来源文件字段“定制预览图”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商品发货" IS '来源文件字段“商品发货”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商品售后" IS '来源文件字段“商品售后”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商品已退款金额" IS '来源文件字段“商品已退款金额”，保留平台导出的原始值。';
