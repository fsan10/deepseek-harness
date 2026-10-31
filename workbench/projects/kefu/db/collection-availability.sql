-- 关店作为可恢复的停用状态；只有显式启用才能恢复，普通同步不覆盖人工选择。
ALTER TABLE metric_profiles ADD COLUMN availability_configured INTEGER NOT NULL DEFAULT 0 CHECK(availability_configured IN(0,1));
UPDATE metric_profiles SET availability_configured=1 WHERE disabled=1;
UPDATE metric_profiles SET disabled=1,availability_configured=1,excluded=0,exclusion_reason=''
WHERE excluded=1 AND exclusion_reason='已关店';
INSERT INTO collection_schema(version) VALUES(3);
