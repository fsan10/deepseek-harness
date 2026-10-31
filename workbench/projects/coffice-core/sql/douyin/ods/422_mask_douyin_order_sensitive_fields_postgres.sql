-- 收件人信息不参与任何指标计算，历史ODS数据与后续新导入数据统一掩码。
-- row_hash 由导入器按掩码后的字段计算。pgcrypto 用于让历史记录与新记录
-- 使用同一 SHA256 算法，避免首次脱敏后再次导入产生重复行。
CREATE EXTENSION IF NOT EXISTS pgcrypto;

UPDATE ods.ods_douyin_order_raw
SET
    "收件人" = CASE WHEN "收件人" IS NULL THEN NULL ELSE '***' END,
    "收件人手机号" = CASE WHEN "收件人手机号" IS NULL THEN NULL ELSE '***' END,
    "详细地址" = CASE WHEN "详细地址" IS NULL THEN NULL ELSE '***' END
WHERE ("收件人" IS NOT NULL AND "收件人" <> '***')
   OR ("收件人手机号" IS NOT NULL AND "收件人手机号" <> '***')
   OR ("详细地址" IS NOT NULL AND "详细地址" <> '***');

WITH recalculated AS (
    SELECT
        id,
        encode(
            digest(
                convert_to(
                    concat_ws(
                    E'\x1f',
                    COALESCE(source_file_name, ''),
                    CASE
                        WHEN COALESCE(source_sheet_name, '') IN ('', 'CSV') THEN ''
                        ELSE source_sheet_name
                    END,
                    COALESCE(source_row_no::text, ''),
                    COALESCE("主订单编号", ''),
                    COALESCE("子订单编号", ''),
                    COALESCE("选购商品", ''),
                    COALESCE("商品规格", ''),
                    COALESCE("商品数量", ''),
                    COALESCE("商品ID", ''),
                    COALESCE("商家编码", ''),
                    COALESCE("商品单价", ''),
                    COALESCE("订单应付金额", ''),
                    COALESCE("运费", ''),
                    COALESCE("优惠总金额", ''),
                    COALESCE("平台优惠", ''),
                    COALESCE("商家优惠", ''),
                    COALESCE("达人优惠", ''),
                    COALESCE("商家改价", ''),
                    COALESCE("支付优惠", ''),
                    COALESCE("红包抵扣", ''),
                    COALESCE("支付方式", ''),
                    COALESCE("手续费", ''),
                    COALESCE("收件人", ''),
                    COALESCE("收件人手机号", ''),
                    COALESCE("省", ''),
                    COALESCE("市", ''),
                    COALESCE("区", ''),
                    COALESCE("街道", ''),
                    COALESCE("详细地址", ''),
                    COALESCE("是否修改过地址", ''),
                    COALESCE("地址修改时段", ''),
                    COALESCE("买家留言", ''),
                    COALESCE("订单提交时间", ''),
                    COALESCE("旗帜颜色", ''),
                    COALESCE("商家备注", ''),
                    COALESCE("订单完成时间", ''),
                    COALESCE("支付完成时间", ''),
                    COALESCE("APP渠道", ''),
                    COALESCE("流量来源", ''),
                    COALESCE("订单状态", ''),
                    COALESCE("承诺发货时间", ''),
                    COALESCE("订单类型", ''),
                    COALESCE("鲁班落地页ID", ''),
                    COALESCE("达人ID", ''),
                    COALESCE("达人昵称", ''),
                    COALESCE("所属门店ID", ''),
                    COALESCE("售后状态", ''),
                    COALESCE("取消原因", ''),
                    COALESCE("预约发货时间", ''),
                    COALESCE("仓库ID", ''),
                    COALESCE("仓库名称", ''),
                    COALESCE("是否安心购", ''),
                    COALESCE("广告渠道", ''),
                    COALESCE("流量类型", ''),
                    COALESCE("流量体裁", ''),
                    COALESCE("流量渠道", ''),
                    COALESCE("发货主体", ''),
                    COALESCE("发货主体明细", ''),
                    COALESCE("发货时间", ''),
                    COALESCE("降价类优惠", ''),
                    COALESCE("平台实际承担优惠金额", ''),
                    COALESCE("商家实际承担优惠金额", ''),
                    COALESCE("达人实际承担优惠金额", ''),
                    COALESCE("预计送达时间", ''),
                    COALESCE("是否平台仓自流转", ''),
                    COALESCE("车型", ''),
                    COALESCE("商品69码", ''),
                    COALESCE("发货SN码", ''),
                    COALESCE("发货IMEI码1", ''),
                    COALESCE("发货IMEI码2", ''),
                    COALESCE("是否福袋订单", ''),
                    COALESCE("福袋采购订单号", ''),
                    COALESCE("福袋采购订单状态", ''),
                    COALESCE("福袋采购订单采购方ID", ''),
                    COALESCE("福袋采购订单采购方名称", ''),
                    COALESCE("福袋采购订单创建时间", ''),
                    COALESCE("福袋采购订单支付时间", ''),
                    COALESCE("福袋采购订单订单应付金额", ''),
                    COALESCE("福袋采购订单订单实际付款金额", ''),
                    COALESCE("福袋采购订单订单优惠金额", ''),
                    COALESCE("福袋采购订单商品ID", ''),
                    COALESCE("福袋采购订单商品名称", ''),
                    COALESCE("福袋采购订单商品单价", ''),
                    COALESCE("福袋采购订单商品数量", ''),
                    COALESCE("福袋采购订单核销数量", ''),
                    COALESCE("福袋采购订单结算数量", ''),
                    COALESCE("预约送达时间", ''),
                    COALESCE("建议发货时间（起）", ''),
                    COALESCE("建议发货时间（止）", ''),
                    COALESCE("物流SN码", ''),
                    COALESCE("物流IMEI码1", ''),
                    COALESCE("物流IMEI码2", '')
                    ),
                    'UTF8'
                ),
                'sha256'
            ),
            'hex'
        ) AS row_hash
    FROM ods.ods_douyin_order_raw
)
UPDATE ods.ods_douyin_order_raw AS target
SET row_hash = recalculated.row_hash
FROM recalculated
WHERE target.id = recalculated.id
  AND target.row_hash IS DISTINCT FROM recalculated.row_hash;

COMMENT ON COLUMN ods.ods_douyin_order_raw."收件人" IS
    '来源文件字段“收件人”，入ODS前统一掩码为***，不保存原始收件人信息。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."收件人手机号" IS
    '来源文件字段“收件人手机号”，入ODS前统一掩码为***，不保存原始手机号信息。';
COMMENT ON COLUMN ods.ods_douyin_order_raw."详细地址" IS
    '来源文件字段“详细地址”，入ODS前统一掩码为***，不保存原始地址信息。';
