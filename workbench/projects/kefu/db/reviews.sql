CREATE TABLE IF NOT EXISTS review_settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  enabled INTEGER NOT NULL DEFAULT 0,
  frequency_days INTEGER NOT NULL DEFAULT 1 CHECK (frequency_days BETWEEN 1 AND 365),
  lookback_days INTEGER NOT NULL DEFAULT 1 CHECK (lookback_days BETWEEN 1 AND 365),
  run_at TEXT NOT NULL DEFAULT '09:00',
  next_run_at TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT OR IGNORE INTO review_settings (id) VALUES (1);

CREATE TABLE IF NOT EXISTS review_profiles (
  profile_id TEXT PRIMARY KEY,
  profile_name TEXT NOT NULL UNIQUE,
  platform TEXT NOT NULL DEFAULT '抖音',
  company TEXT NOT NULL DEFAULT '',
  shop_name TEXT NOT NULL,
  excluded INTEGER NOT NULL DEFAULT 0,
  exclusion_reason TEXT NOT NULL DEFAULT '',
  last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_runs (
  id TEXT PRIMARY KEY,
  trigger_type TEXT NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  profile_ids TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'queued',
  message TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  heartbeat_at TEXT,
  collected_count INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS review_one_active_run ON review_runs ((1)) WHERE status IN ('queued', 'running');

CREATE TABLE IF NOT EXISTS review_run_shops (
  run_id TEXT NOT NULL REFERENCES review_runs(id),
  profile_id TEXT NOT NULL,
  shop_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  message TEXT NOT NULL DEFAULT '',
  collected_count INTEGER NOT NULL DEFAULT 0,
  missing_code_count INTEGER NOT NULL DEFAULT 0,
  finished_at TEXT,
  PRIMARY KEY (run_id, profile_id)
);

CREATE TABLE IF NOT EXISTS negative_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL DEFAULT '抖音',
  profile_id TEXT NOT NULL,
  company TEXT NOT NULL DEFAULT '',
  shop_name TEXT NOT NULL,
  comment_id TEXT NOT NULL,
  order_id TEXT NOT NULL,
  shop_order_id TEXT NOT NULL DEFAULT '',
  reviewed_at TEXT NOT NULL,
  review_date TEXT NOT NULL,
  review_level TEXT NOT NULL CHECK (review_level IN ('中评', '差评')),
  content TEXT NOT NULL,
  product_id TEXT NOT NULL,
  product_name TEXT NOT NULL,
  sku_id TEXT NOT NULL DEFAULT '',
  sku_name TEXT NOT NULL DEFAULT '',
  product_code TEXT NOT NULL DEFAULT '',
  code_source TEXT NOT NULL DEFAULT '',
  enrichment_status TEXT NOT NULL DEFAULT 'pending',
  keywords TEXT NOT NULL DEFAULT '',
  source_status TEXT NOT NULL DEFAULT '',
  collected_at TEXT NOT NULL,
  run_id TEXT NOT NULL REFERENCES review_runs(id),
  UNIQUE (profile_id, comment_id)
);
CREATE INDEX IF NOT EXISTS negative_reviews_date_shop ON negative_reviews(review_date, shop_name);
CREATE INDEX IF NOT EXISTS negative_reviews_order ON negative_reviews(order_id);
CREATE INDEX IF NOT EXISTS negative_reviews_product ON negative_reviews(product_id);

CREATE TABLE IF NOT EXISTS review_worker_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  pid INTEGER NOT NULL,
  heartbeat_at TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS review_auth_status (
  profile_id TEXT PRIMARY KEY REFERENCES review_profiles(profile_id),
  state TEXT NOT NULL,
  message TEXT NOT NULL,
  error_code TEXT NOT NULL DEFAULT '',
  actual_shop_name TEXT NOT NULL DEFAULT '',
  checked_at TEXT NOT NULL,
  captured_at TEXT
);
CREATE TABLE IF NOT EXISTS review_auth_settings (
  id INTEGER PRIMARY KEY CHECK (id=1),
  check_interval_minutes INTEGER NOT NULL DEFAULT 5 CHECK(check_interval_minutes BETWEEN 1 AND 1440)
);
INSERT OR IGNORE INTO review_auth_settings(id) VALUES(1);
