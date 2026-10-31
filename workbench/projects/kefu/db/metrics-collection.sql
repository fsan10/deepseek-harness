-- 采集控制与来源审计。业务指标仍由 /api/import 写入 daily_records。
CREATE TABLE IF NOT EXISTS metric_profiles (
  profile_id TEXT PRIMARY KEY,
  profile_name TEXT NOT NULL UNIQUE,
  platform TEXT NOT NULL,
  company TEXT NOT NULL DEFAULT '',
  expected_shop_name TEXT NOT NULL DEFAULT '',
  shop_name TEXT NOT NULL DEFAULT '',
  shop_kind TEXT NOT NULL DEFAULT 'own' CHECK(shop_kind='own'),
  score_enabled INTEGER NOT NULL DEFAULT 0 CHECK(score_enabled IN(0,1)),
  reception_enabled INTEGER NOT NULL DEFAULT 0 CHECK(reception_enabled IN(0,1)),
  excluded INTEGER NOT NULL DEFAULT 0 CHECK(excluded IN(0,1)),
  exclusion_reason TEXT NOT NULL DEFAULT '',
  last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS metric_auth_status (
  profile_id TEXT PRIMARY KEY REFERENCES metric_profiles(profile_id),
  state TEXT NOT NULL,
  message TEXT NOT NULL,
  error_code TEXT NOT NULL DEFAULT '',
  actual_shop_name TEXT NOT NULL DEFAULT '',
  actual_shop_id TEXT NOT NULL DEFAULT '',
  checked_at TEXT NOT NULL,
  captured_at TEXT
);
CREATE TABLE IF NOT EXISTS metric_collection_settings (
  kind TEXT PRIMARY KEY CHECK(kind IN('reception','score')),
  enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN(0,1)),
  frequency_days INTEGER NOT NULL DEFAULT 1 CHECK(frequency_days BETWEEN 1 AND 365),
  lookback_days INTEGER NOT NULL DEFAULT 1 CHECK(lookback_days BETWEEN 1 AND 31),
  run_at TEXT NOT NULL DEFAULT '09:00',
  next_run_at TEXT,
  updated_at TEXT NOT NULL DEFAULT ''
);
INSERT OR IGNORE INTO metric_collection_settings(kind) VALUES('reception'),('score');
CREATE TABLE IF NOT EXISTS metric_service_settings (
  id INTEGER PRIMARY KEY CHECK(id=1),
  auth_poll_minutes INTEGER NOT NULL DEFAULT 15 CHECK(auth_poll_minutes BETWEEN 1 AND 1440)
);
INSERT OR IGNORE INTO metric_service_settings(id) VALUES(1);
CREATE TABLE IF NOT EXISTS metric_runs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN('reception','score')),
  trigger_type TEXT NOT NULL DEFAULT 'manual',
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  profile_ids TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  message TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  heartbeat_at TEXT,
  collected_count INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS metric_one_active_run_per_kind ON metric_runs(kind) WHERE status IN('queued','running');
CREATE TABLE IF NOT EXISTS metric_run_items (
  run_id TEXT NOT NULL REFERENCES metric_runs(id),
  profile_id TEXT NOT NULL REFERENCES metric_profiles(profile_id),
  requested_date TEXT NOT NULL,
  report_date TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  message TEXT NOT NULL DEFAULT '',
  error_code TEXT NOT NULL DEFAULT '',
  record_count INTEGER NOT NULL DEFAULT 0,
  source_metric TEXT NOT NULL DEFAULT '',
  import_request_id TEXT NOT NULL DEFAULT '',
  payload_sha256 TEXT NOT NULL DEFAULT '',
  collected_at TEXT,
  finished_at TEXT,
  PRIMARY KEY(run_id,profile_id,requested_date)
);
CREATE TABLE IF NOT EXISTS metric_worker_state (
  id INTEGER PRIMARY KEY CHECK(id=1),
  pid INTEGER NOT NULL,
  heartbeat_at TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS collection_notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_key TEXT NOT NULL UNIQUE,
  profile_id TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL,
  message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  message_id TEXT NOT NULL DEFAULT '',
  error_summary TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  finished_at TEXT
);
