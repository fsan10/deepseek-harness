-- 逐店控制后台登录轮询；不影响手动检查和采集时的自动登录恢复。
ALTER TABLE metric_profiles ADD COLUMN auth_check_enabled INTEGER NOT NULL DEFAULT 1 CHECK(auth_check_enabled IN(0,1));
INSERT INTO collection_schema(version) VALUES(7);
