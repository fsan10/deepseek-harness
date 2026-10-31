CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_tmall_taobao_union_promotion_expense_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    "日期" VARCHAR(64),
    "点击量(即进店量)" VARCHAR(64),
    "点击人数(即进店人数)" VARCHAR(64),
    "推广商品数" VARCHAR(64),
    "优惠券领取量" VARCHAR(64),
    "付款金额(元)" VARCHAR(64),
    "付款笔数" VARCHAR(64),
    "付款人数" VARCHAR(64),
    "付款件数" VARCHAR(64),
    "结算人数" VARCHAR(64),
    "点击转化率(即付款转化率)" VARCHAR(64),
    "确认收货人数" VARCHAR(64),
    "确认收货金额" VARCHAR(64),
    "确认收货笔数" VARCHAR(64),
    "添加购物车量" VARCHAR(64),
    "收藏宝贝量" VARCHAR(64),
    "结算金额(元)" VARCHAR(64),
    "结算笔数" VARCHAR(64),
    "付款佣金支出(元)" VARCHAR(64),
    "付款服务费支出(元)" VARCHAR(64),
    "付款支出费用(元)" VARCHAR(64),
    "付款佣金率" VARCHAR(64),
    "付款服务费率" VARCHAR(64),
    "单件商品付款支出费用(元)" VARCHAR(64),
    "结算佣金支出(元)" VARCHAR(64),
    "结算服务费支出(元)" VARCHAR(64),
    "结算支出费用(元)" VARCHAR(64),
    "结算佣金率" VARCHAR(64),
    "结算服务费率" VARCHAR(64),
    "预估预售整单佣金(元)" VARCHAR(64),
    "预估预售整单佣金率" VARCHAR(64),
    "预售定金笔数" VARCHAR(64),
    "预售定金金额(元)" VARCHAR(64),
    "预估预售尾款金额(元)" VARCHAR(64),
    "预估预售整单金额(元)" VARCHAR(64),
    "付款营销服务费支出(元)" VARCHAR(64),
    "结算营销服务费支出(元)" VARCHAR(64),
    CONSTRAINT uk_ods_tmall_taobao_union_promotion_row_hash UNIQUE (row_hash)
);

COMMENT ON TABLE ods.ods_tmall_taobao_union_promotion_expense_raw IS '天猫淘宝联盟推广费日数据ODS原始表，完整保留来源导出的37个字段。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw.batch_id IS '文件导入批次ID，关联ods.ods_file_ingest_log获取标准店铺。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw.source_file_name IS '来源文件名。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw.source_sheet_name IS '来源工作表名，CSV固定为CSV。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw.row_hash IS '原始行SHA256摘要，用于幂等去重。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw.ingest_time IS 'ODS入库时间。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."日期" IS '淘宝联盟日统计日期，格式YYYYMMDD。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."点击量(即进店量)" IS '来源点击量。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."点击人数(即进店人数)" IS '来源点击人数。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."推广商品数" IS '来源推广商品数。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."优惠券领取量" IS '来源优惠券领取量。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."付款金额(元)" IS '来源付款金额，单位元。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."付款笔数" IS '来源付款笔数。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."付款人数" IS '来源付款人数。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."付款件数" IS '来源付款件数。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."结算人数" IS '来源结算人数。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."点击转化率(即付款转化率)" IS '来源点击转化率。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."确认收货人数" IS '来源确认收货人数。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."确认收货金额" IS '来源确认收货金额，单位元。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."确认收货笔数" IS '来源确认收货笔数。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."添加购物车量" IS '来源添加购物车量。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."收藏宝贝量" IS '来源收藏宝贝量。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."结算金额(元)" IS '来源结算金额，单位元。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."结算笔数" IS '来源结算笔数。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."付款佣金支出(元)" IS '来源付款佣金支出，单位元。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."付款服务费支出(元)" IS '来源付款服务费支出，单位元。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."付款支出费用(元)" IS '来源付款支出费用合计，单位元。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."付款佣金率" IS '来源付款佣金率。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."付款服务费率" IS '来源付款服务费率。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."单件商品付款支出费用(元)" IS '来源单件商品付款支出费用，单位元。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."结算佣金支出(元)" IS '来源结算佣金支出，单位元。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."结算服务费支出(元)" IS '来源结算服务费支出，单位元。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."结算支出费用(元)" IS '淘宝联盟推广费金额来源，等于来源结算支出费用，单位元。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."结算佣金率" IS '来源结算佣金率。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."结算服务费率" IS '来源结算服务费率。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."预估预售整单佣金(元)" IS '来源预估预售整单佣金，单位元。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."预估预售整单佣金率" IS '来源预估预售整单佣金率。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."预售定金笔数" IS '来源预售定金笔数。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."预售定金金额(元)" IS '来源预售定金金额，单位元。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."预估预售尾款金额(元)" IS '来源预估预售尾款金额，单位元。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."预估预售整单金额(元)" IS '来源预估预售整单金额，单位元。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."付款营销服务费支出(元)" IS '来源付款营销服务费支出，单位元。';
COMMENT ON COLUMN ods.ods_tmall_taobao_union_promotion_expense_raw."结算营销服务费支出(元)" IS '来源结算营销服务费支出，单位元。';

CREATE INDEX IF NOT EXISTS idx_ods_tmall_taobao_union_promotion_batch
    ON ods.ods_tmall_taobao_union_promotion_expense_raw (batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_tmall_taobao_union_promotion_date
    ON ods.ods_tmall_taobao_union_promotion_expense_raw ("日期");
