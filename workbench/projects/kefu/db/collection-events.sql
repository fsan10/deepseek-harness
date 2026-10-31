-- 异常事件唯一存储：服务登录检查与采集任务写入同一张表。
-- 只有未恢复的事件保持唯一（部分唯一索引），恢复后再次发生会产生新事件，历史完整保留。
CREATE TABLE IF NOT EXISTS collection_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dedupe_key TEXT NOT NULL,
  source TEXT NOT NULL CHECK(source IN ('service','run')),
  sources TEXT NOT NULL DEFAULT '[]',
  category TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'warning' CHECK(severity IN ('warning','danger')),
  platform TEXT NOT NULL DEFAULT '',
  profile_id TEXT NOT NULL DEFAULT '',
  shop_name TEXT NOT NULL DEFAULT '',
  task_kind TEXT NOT NULL DEFAULT '',
  run_ids TEXT NOT NULL DEFAULT '[]',
  task_count INTEGER NOT NULL DEFAULT 0,
  message TEXT NOT NULL DEFAULT '',
  occurrences INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','recovered')),
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  recovered_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS collection_events_open_key ON collection_events(dedupe_key) WHERE status='open';
CREATE INDEX IF NOT EXISTS collection_events_last_seen ON collection_events(last_seen_at DESC);
CREATE INDEX IF NOT EXISTS collection_events_status ON collection_events(status,last_seen_at DESC);
INSERT INTO collection_schema(version) VALUES(4);
