CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_jd_order_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "订单号" TEXT,
    "商品ID" TEXT,
    "商品名称" TEXT,
    "订购数量" TEXT,
    "支付方式" TEXT,
    "下单时间" TEXT,
    "京东价" TEXT,
    "订单金额" TEXT,
    "商家应收" TEXT,
    "余额支付" TEXT,
    "应付金额" TEXT,
    "订单状态" TEXT,
    "订单类型" TEXT,
    "订单标签" TEXT,
    "下单帐号" TEXT,
    "订单备注" TEXT,
    "发票类型" TEXT,
    "发票抬头" TEXT,
    "发票内容" TEXT,
    "纳税人识别号" TEXT,
    "名称（个人）" TEXT,
    "单位地址" TEXT,
    "单位电话" TEXT,
    "开户银行" TEXT,
    "银行账号" TEXT,
    "商家备注" TEXT,
    "商家备注等级（等级1-5为由高到低）" TEXT,
    "运费金额" TEXT,
    "付款确认时间" TEXT,
    "货号" TEXT,
    "订单完成时间" TEXT,
    "订单来源" TEXT,
    "订单渠道" TEXT,
    "送装服务" TEXT,
    "服务费" TEXT,
    "仓库id" TEXT,
    "仓库名称" TEXT,
    "商家SKUID" TEXT,
    "邮箱地址" TEXT,
    "邮政编码" TEXT,
    "是否为品牌商订单" TEXT,
    "是否为toplife订单" TEXT,
    "业务类型" TEXT,
    "履约门店ID" TEXT,
    "下单门店Id" TEXT,
    "门店名称" TEXT,
    "门店联系人" TEXT,
    "门店联系电话" TEXT,
    "门店地址" TEXT,
    "导购员账号" TEXT,
    "延迟报备类型" TEXT,
    "订单出库时间" TEXT,
    "客户类型" TEXT,
    "KA订单发货需提供单据" TEXT,
    "KA订单客户收货要求" TEXT,
    "正品鉴定校验结果" TEXT,
    "正品鉴定补充说明" TEXT,
    "正品鉴定不合格原因" TEXT,
    "正品鉴定图片链接" TEXT,
    "企配订单" TEXT,
    "需上传SN码" TEXT,
    "SN码" TEXT,
    "SN码有效状态" TEXT,
    "SN码激活状态" TEXT,
    "SN码补贴状态" TEXT,
    "百补满赠" TEXT,
    "买一试三" TEXT,
    "最晚/承诺发货时间（仅当日发/明日达为承诺时间）" TEXT,
    "款项名称" TEXT,
    "项目ID" TEXT,
    "指数订单编号" TEXT,
    "是否为以旧换新订单" TEXT,
    "主体ID" TEXT,
    "主体名称" TEXT,
    "采购价" TEXT,
    "采购订单号" TEXT,
    "敏感信息超额" TEXT,

    CONSTRAINT uk_ods_jd_order_row_hash UNIQUE (row_hash)
);

CREATE INDEX IF NOT EXISTS idx_ods_jd_order_order_no ON ods.ods_jd_order_raw ("订单号");
CREATE INDEX IF NOT EXISTS idx_ods_jd_order_product_id ON ods.ods_jd_order_raw ("商品ID");
CREATE INDEX IF NOT EXISTS idx_ods_jd_order_sku_id ON ods.ods_jd_order_raw ("商家SKUID");
CREATE INDEX IF NOT EXISTS idx_ods_jd_order_source_file ON ods.ods_jd_order_raw (source_file_name);
CREATE INDEX IF NOT EXISTS idx_ods_jd_order_batch_id ON ods.ods_jd_order_raw (batch_id);

COMMENT ON TABLE ods.ods_jd_order_raw IS 'ODS京东订单原始表，按平台导出订单文件表头原样保存。';
COMMENT ON COLUMN ods.ods_jd_order_raw.batch_id IS '导入批次ID，可关联ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_jd_order_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_jd_order_raw.source_sheet_name IS '来源Sheet名，CSV固定为CSV';
COMMENT ON COLUMN ods.ods_jd_order_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_jd_order_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_jd_order_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_jd_order_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_jd_order_raw."订单号" IS '来源文件字段“订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."商品ID" IS '来源文件字段“商品ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."商品名称" IS '来源文件字段“商品名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."订购数量" IS '来源文件字段“订购数量”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."支付方式" IS '来源文件字段“支付方式”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."下单时间" IS '来源文件字段“下单时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."京东价" IS '来源文件字段“京东价”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."订单金额" IS '来源文件字段“订单金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."商家应收" IS '来源文件字段“商家应收”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."余额支付" IS '来源文件字段“余额支付”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."应付金额" IS '来源文件字段“应付金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."订单状态" IS '来源文件字段“订单状态”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."订单类型" IS '来源文件字段“订单类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."订单标签" IS '来源文件字段“订单标签”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."下单帐号" IS '来源文件字段“下单帐号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."订单备注" IS '来源文件字段“订单备注”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."发票类型" IS '来源文件字段“发票类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."发票抬头" IS '来源文件字段“发票抬头”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."发票内容" IS '来源文件字段“发票内容”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."纳税人识别号" IS '来源文件字段“纳税人识别号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."名称（个人）" IS '来源文件字段“名称（个人）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."单位地址" IS '来源文件字段“单位地址”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."单位电话" IS '来源文件字段“单位电话”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."开户银行" IS '来源文件字段“开户银行”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."银行账号" IS '来源文件字段“银行账号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."商家备注" IS '来源文件字段“商家备注”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."商家备注等级（等级1-5为由高到低）" IS '来源文件字段“商家备注等级（等级1-5为由高到低）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."运费金额" IS '来源文件字段“运费金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."付款确认时间" IS '来源文件字段“付款确认时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."货号" IS '来源文件字段“货号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."订单完成时间" IS '来源文件字段“订单完成时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."订单来源" IS '来源文件字段“订单来源”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."订单渠道" IS '来源文件字段“订单渠道”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."送装服务" IS '来源文件字段“送装服务”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."服务费" IS '来源文件字段“服务费”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."仓库id" IS '来源文件字段“仓库id”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."仓库名称" IS '来源文件字段“仓库名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."商家SKUID" IS '来源文件字段“商家SKUID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."邮箱地址" IS '来源文件字段“邮箱地址”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."邮政编码" IS '来源文件字段“邮政编码”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."是否为品牌商订单" IS '来源文件字段“是否为品牌商订单”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."是否为toplife订单" IS '来源文件字段“是否为toplife订单”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."业务类型" IS '来源文件字段“业务类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."履约门店ID" IS '来源文件字段“履约门店ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."下单门店Id" IS '来源文件字段“下单门店Id”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."门店名称" IS '来源文件字段“门店名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."门店联系人" IS '来源文件字段“门店联系人”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."门店联系电话" IS '来源文件字段“门店联系电话”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."门店地址" IS '来源文件字段“门店地址”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."导购员账号" IS '来源文件字段“导购员账号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."延迟报备类型" IS '来源文件字段“延迟报备类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."订单出库时间" IS '来源文件字段“订单出库时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."客户类型" IS '来源文件字段“客户类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."KA订单发货需提供单据" IS '来源文件字段“KA订单发货需提供单据”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."KA订单客户收货要求" IS '来源文件字段“KA订单客户收货要求”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."正品鉴定校验结果" IS '来源文件字段“正品鉴定校验结果”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."正品鉴定补充说明" IS '来源文件字段“正品鉴定补充说明”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."正品鉴定不合格原因" IS '来源文件字段“正品鉴定不合格原因”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."正品鉴定图片链接" IS '来源文件字段“正品鉴定图片链接”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."企配订单" IS '来源文件字段“企配订单”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."需上传SN码" IS '来源文件字段“需上传SN码”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."SN码" IS '来源文件字段“SN码”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."SN码有效状态" IS '来源文件字段“SN码有效状态”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."SN码激活状态" IS '来源文件字段“SN码激活状态”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."SN码补贴状态" IS '来源文件字段“SN码补贴状态”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."百补满赠" IS '来源文件字段“百补满赠”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."买一试三" IS '来源文件字段“买一试三”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."最晚/承诺发货时间（仅当日发/明日达为承诺时间）" IS '来源文件字段“最晚/承诺发货时间（仅当日发/明日达为承诺时间）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."款项名称" IS '来源文件字段“款项名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."项目ID" IS '来源文件字段“项目ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."指数订单编号" IS '来源文件字段“指数订单编号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."是否为以旧换新订单" IS '来源文件字段“是否为以旧换新订单”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."主体ID" IS '来源文件字段“主体ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."主体名称" IS '来源文件字段“主体名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."采购价" IS '来源文件字段“采购价”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."采购订单号" IS '来源文件字段“采购订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_order_raw."敏感信息超额" IS '来源文件字段“敏感信息超额”，保留平台导出的原始值。';
