-- 飞书提醒发送记录直接挂在异常事件上，展示时不需要再按时间窗口猜测归属。
ALTER TABLE collection_notifications ADD COLUMN event_id INTEGER;
CREATE INDEX IF NOT EXISTS collection_notifications_event ON collection_notifications(event_id);
INSERT INTO collection_schema(version) VALUES(5);
