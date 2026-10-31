DO $$
DECLARE
    has_legacy_discount BOOLEAN;
    has_merchant_discount BOOLEAN;
BEGIN
    -- 导入中心可能在来源表尚未初始化时先执行迁移；此时留给正式建表SQL处理。
    IF to_regclass('ods.ods_wechat_channels_order_raw') IS NULL THEN
        RETURN;
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'ods'
          AND table_name = 'ods_wechat_channels_order_raw'
          AND column_name = '商品优惠'
    ) INTO has_legacy_discount;

    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'ods'
          AND table_name = 'ods_wechat_channels_order_raw'
          AND column_name = '商家优惠'
    ) INTO has_merchant_discount;

    IF has_legacy_discount AND has_merchant_discount THEN
        RAISE EXCEPTION '视频号订单ODS同时存在旧字段“商品优惠”和新字段“商家优惠”，拒绝静默选择字段';
    ELSIF has_legacy_discount THEN
        ALTER TABLE ods.ods_wechat_channels_order_raw
            RENAME COLUMN "商品优惠" TO "商家优惠";
    ELSIF NOT has_merchant_discount THEN
        ALTER TABLE ods.ods_wechat_channels_order_raw
            ADD COLUMN "商家优惠" TEXT;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'ods'
          AND table_name = 'ods_wechat_channels_order_raw'
          AND column_name = '平台优惠'
    ) THEN
        ALTER TABLE ods.ods_wechat_channels_order_raw
            ADD COLUMN "平台优惠" TEXT;
    END IF;

    COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."商家优惠"
        IS '来源文件字段“商家优惠”，保留平台导出的原始值；旧版“商品优惠”表头由Loader兼容映射到本列。';
    COMMENT ON COLUMN ods.ods_wechat_channels_order_raw."平台优惠"
        IS '来源文件字段“平台优惠”，保留平台导出的原始值；旧版未拆分文件为空。';
END $$;
