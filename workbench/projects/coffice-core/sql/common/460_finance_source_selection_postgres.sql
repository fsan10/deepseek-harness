-- 平台资金流水按标准店铺、账户及平台流水身份选择来源版本；ODS不变。
CREATE OR REPLACE VIEW common.v_current_douyin_fund_raw AS
SELECT r.* FROM common.v_selected_douyin_fund_raw r
JOIN (
    SELECT DISTINCT ON (c.shop_identity_key, BTRIM(s."动账账户"), BTRIM(s."动帐流水号")) s.id
    FROM common.v_selected_douyin_fund_raw s
    JOIN common.v_ingest_batch_shop_context c ON c.batch_id=s.batch_id
      AND c.platform_code='douyin' AND c.target_table='ods_douyin_fund_raw'
      AND c.shop_mapping_status='mapped' AND c.ingest_status='success'
    ORDER BY c.shop_identity_key, BTRIM(s."动账账户"), BTRIM(s."动帐流水号"),
             s.ingest_time DESC, s.id DESC
) chosen ON chosen.id=r.id;
COMMENT ON VIEW common.v_current_douyin_fund_raw IS
    '抖音资金有效来源：标准店铺、动账账户、平台动帐流水号相同的来源选最新导入版本；必须先通过finance_sources的完整性、流水粒度及全业务字段一致校验；不按订单或金额去重。';

CREATE OR REPLACE VIEW common.v_current_ks_fund_raw AS
SELECT r.* FROM ods.ods_ks_fund_raw r
JOIN (
    SELECT DISTINCT ON (c.shop_identity_key, BTRIM(s."账务流水号")) s.id
    FROM ods.ods_ks_fund_raw s
    JOIN common.v_ingest_batch_shop_context c ON c.batch_id=s.batch_id
      AND c.platform_code='ks' AND c.target_table='ods_ks_fund_raw'
      AND c.shop_mapping_status='mapped' AND c.ingest_status='success'
    ORDER BY c.shop_identity_key, BTRIM(s."账务流水号"), s.ingest_time DESC, s.id DESC
) chosen ON chosen.id=r.id;
COMMENT ON VIEW common.v_current_ks_fund_raw IS
    '快手资金有效来源：同标准店铺、平台账务流水号选择最新导入版本；必须先校验完整批次和重复身份的全部业务字段；退款冻结、解冻、扣减有不同流水号，均保留。';

CREATE OR REPLACE VIEW common.v_current_wechat_channels_settlement_raw AS
SELECT r.* FROM common.v_selected_wechat_channels_settlement_raw r
JOIN (
    SELECT DISTINCT ON (c.shop_identity_key, BTRIM(s."流水单号")) s.id
    FROM common.v_selected_wechat_channels_settlement_raw s
    JOIN common.v_ingest_batch_shop_context c ON c.batch_id=s.batch_id
      AND c.platform_code='wechat_channels' AND c.target_table='ods_wechat_channels_settlement_raw'
      AND c.shop_mapping_status='mapped' AND c.ingest_status='success'
    ORDER BY c.shop_identity_key, BTRIM(s."流水单号"), s.ingest_time DESC, s.id DESC
) chosen ON chosen.id=r.id;
COMMENT ON VIEW common.v_current_wechat_channels_settlement_raw IS
    '视频号经营有效来源：标准店铺、平台流水单号相同的完整来源版本只取一次；先校验流水身份和全部业务字段；不推断未知月份覆盖，不删除ODS。';

DO $$
DECLARE item RECORD; col RECORD;
BEGIN
    FOR item IN SELECT * FROM (VALUES
        ('v_current_douyin_fund_raw','ods_douyin_fund_raw'),
        ('v_current_ks_fund_raw','ods_ks_fund_raw'),
        ('v_current_wechat_channels_settlement_raw','ods_wechat_channels_settlement_raw')
    ) v(view_name,raw_name)
    LOOP
        FOR col IN SELECT a.attname,COALESCE(col_description(c.oid,a.attnum),'来源ODS原始字段，业务含义、单位和枚举沿用源表。') note
            FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='ods' AND c.relname=item.raw_name AND a.attnum>0 AND NOT a.attisdropped
        LOOP
            EXECUTE FORMAT('COMMENT ON COLUMN common.%I.%I IS %L',item.view_name,col.attname,col.note);
        END LOOP;
    END LOOP;
END $$;
