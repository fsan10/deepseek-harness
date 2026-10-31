-- 已存在的候选DWD同步采用店铺内业务身份，避免不同店铺复用单号时相互覆盖。
DO $$
DECLARE item RECORD; current_key RECORD; relation REGCLASS;
BEGIN
    FOR item IN SELECT * FROM (VALUES
        ('dwd_jd_main_business_income_source_detail','source_document_type'),
        ('dwd_jd_platform_expense_source_detail','source_document_type'),
        ('dwd_tmall_main_business_income_source_detail','source_account_type'),
        ('dwd_tmall_platform_expense_source_detail','source_account_type')
    ) v(table_name,document_column)
    LOOP
        relation:=TO_REGCLASS('dwd.'||item.table_name);
        IF relation IS NULL THEN CONTINUE; END IF;
        SELECT conname,pg_get_constraintdef(oid) definition INTO current_key
          FROM pg_constraint WHERE conrelid=relation AND contype='p';
        IF current_key.definition LIKE '%shop_identity_key%' THEN CONTINUE; END IF;
        IF current_key.conname IS NOT NULL THEN
            EXECUTE FORMAT('ALTER TABLE dwd.%I DROP CONSTRAINT %I',item.table_name,current_key.conname);
        END IF;
        EXECUTE FORMAT('ALTER TABLE dwd.%I ADD PRIMARY KEY (shop_identity_key,%I,source_event_key)',
                       item.table_name,item.document_column);
    END LOOP;
END $$;
