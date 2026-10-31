-- 采集范围只在店铺配置中维护；历史任务保留各自的实际执行店铺清单。
ALTER TABLE metric_profiles ADD COLUMN collect_reviews INTEGER NOT NULL DEFAULT 1 CHECK(collect_reviews IN(0,1));
ALTER TABLE metric_profiles ADD COLUMN collect_reception INTEGER NOT NULL DEFAULT 1 CHECK(collect_reception IN(0,1));
ALTER TABLE metric_profiles ADD COLUMN collect_score INTEGER NOT NULL DEFAULT 1 CHECK(collect_score IN(0,1));

UPDATE metric_profiles SET collect_reception=CASE WHEN profile_id IN(SELECT profile_id FROM collection_scope_migration WHERE kind='reception') THEN 1 ELSE 0 END
WHERE EXISTS(SELECT 1 FROM collection_scope_migration_kinds WHERE kind='reception');
UPDATE metric_profiles SET collect_score=CASE WHEN profile_id IN(SELECT profile_id FROM collection_scope_migration WHERE kind='score') THEN 1 ELSE 0 END
WHERE EXISTS(SELECT 1 FROM collection_scope_migration_kinds WHERE kind='score');

CREATE TABLE metric_collection_settings_next (
  kind TEXT PRIMARY KEY CHECK(kind IN('reception','score')),
  enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN(0,1)),
  frequency_days INTEGER NOT NULL DEFAULT 1 CHECK(frequency_days BETWEEN 1 AND 365),
  lookback_days INTEGER NOT NULL DEFAULT 1 CHECK(lookback_days BETWEEN 1 AND 31),
  run_at TEXT NOT NULL DEFAULT '09:00',
  next_run_at TEXT,
  updated_at TEXT NOT NULL DEFAULT ''
);
INSERT INTO metric_collection_settings_next SELECT kind,enabled,frequency_days,lookback_days,run_at,next_run_at,updated_at FROM metric_collection_settings;
DROP TABLE metric_collection_settings;
ALTER TABLE metric_collection_settings_next RENAME TO metric_collection_settings;

DROP VIEW review_profiles;
CREATE VIEW review_profiles AS
SELECT profile_id,profile_name,'抖音' AS platform,company,expected_shop_name AS shop_name,
  CASE WHEN excluded=1 OR disabled=1 OR collect_reviews=0 THEN 1 ELSE 0 END AS excluded,
  CASE WHEN excluded=1 THEN exclusion_reason WHEN disabled=1 THEN '已停用' WHEN collect_reviews=0 THEN '未启用评论采集' ELSE '' END AS exclusion_reason,
  last_seen_at FROM metric_profiles WHERE review_enabled=1;
CREATE TRIGGER review_profile_identity_update INSTEAD OF UPDATE OF shop_name ON review_profiles BEGIN
  UPDATE metric_profiles SET expected_shop_name=NEW.shop_name WHERE profile_id=OLD.profile_id;
END;
DROP TABLE collection_scope_migration;
DROP TABLE collection_scope_migration_kinds;
INSERT INTO collection_schema(version) VALUES(2);
