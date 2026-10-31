-- 一次性合并账号与认证状态。旧表只留作迁移档案；兼容入口读取同一份账号。
ALTER TABLE metric_profiles ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0 CHECK(disabled IN(0,1));
ALTER TABLE metric_profiles ADD COLUMN review_enabled INTEGER NOT NULL DEFAULT 0 CHECK(review_enabled IN(0,1));

UPDATE metric_service_settings SET auth_poll_minutes=(SELECT check_interval_minutes FROM review_auth_settings WHERE id=1)
WHERE id=1 AND NOT EXISTS(SELECT 1 FROM metric_profiles);

INSERT INTO metric_profiles(profile_id,profile_name,platform,company,expected_shop_name,excluded,exclusion_reason,last_seen_at,review_enabled)
SELECT profile_id,profile_name,'douyin',company,shop_name,excluded,exclusion_reason,last_seen_at,1 FROM review_profiles WHERE 1
ON CONFLICT(profile_id) DO UPDATE SET
  company=CASE WHEN metric_profiles.company='' THEN excluded.company ELSE metric_profiles.company END,
  expected_shop_name=CASE WHEN metric_profiles.expected_shop_name='' THEN excluded.expected_shop_name ELSE metric_profiles.expected_shop_name END;
UPDATE metric_profiles SET review_enabled=1 WHERE platform='douyin' AND profile_name LIKE 'DY-抖音%';

INSERT INTO metric_auth_status(profile_id,state,message,error_code,actual_shop_name,checked_at,captured_at)
SELECT profile_id,state,message,error_code,actual_shop_name,checked_at,captured_at FROM review_auth_status WHERE 1
ON CONFLICT(profile_id) DO UPDATE SET
  state=excluded.state,message=excluded.message,error_code=excluded.error_code,
  actual_shop_name=CASE WHEN excluded.actual_shop_name='' THEN metric_auth_status.actual_shop_name ELSE excluded.actual_shop_name END,
  checked_at=excluded.checked_at,captured_at=COALESCE(excluded.captured_at,metric_auth_status.captured_at)
WHERE julianday(excluded.checked_at)>julianday(metric_auth_status.checked_at);

ALTER TABLE review_auth_status RENAME TO legacy_review_auth_status;
ALTER TABLE review_profiles RENAME TO legacy_review_profiles;
ALTER TABLE review_auth_settings RENAME TO legacy_review_auth_settings;

CREATE VIEW review_profiles AS
SELECT profile_id,profile_name,'抖音' AS platform,company,expected_shop_name AS shop_name,
  CASE WHEN excluded=1 OR disabled=1 THEN 1 ELSE 0 END AS excluded,
  CASE WHEN excluded=1 THEN exclusion_reason WHEN disabled=1 THEN '已停用' ELSE '' END AS exclusion_reason,
  last_seen_at FROM metric_profiles WHERE review_enabled=1;
CREATE VIEW review_auth_status AS
SELECT a.profile_id,a.state,a.message,a.error_code,a.actual_shop_name,a.checked_at,a.captured_at
FROM metric_auth_status a JOIN metric_profiles p ON p.profile_id=a.profile_id WHERE p.review_enabled=1;
CREATE VIEW review_auth_settings AS
SELECT id,auth_poll_minutes AS check_interval_minutes FROM metric_service_settings;

CREATE TRIGGER review_profile_identity_update INSTEAD OF UPDATE OF shop_name ON review_profiles BEGIN
  UPDATE metric_profiles SET expected_shop_name=NEW.shop_name WHERE profile_id=OLD.profile_id;
END;
CREATE TRIGGER review_auth_compat_update INSTEAD OF UPDATE ON review_auth_status BEGIN
  UPDATE metric_auth_status SET state=NEW.state,message=NEW.message,error_code=NEW.error_code,
    actual_shop_name=NEW.actual_shop_name,checked_at=NEW.checked_at,captured_at=NEW.captured_at WHERE profile_id=OLD.profile_id;
END;
CREATE TRIGGER review_auth_interval_update INSTEAD OF UPDATE ON review_auth_settings BEGIN
  UPDATE metric_service_settings SET auth_poll_minutes=NEW.check_interval_minutes WHERE id=OLD.id;
END;
CREATE TRIGGER review_auth_interval_insert INSTEAD OF INSERT ON review_auth_settings BEGIN
  INSERT OR IGNORE INTO metric_service_settings(id,auth_poll_minutes) VALUES(NEW.id,COALESCE(NEW.check_interval_minutes,5));
END;
INSERT INTO collection_schema(version) VALUES(1);
