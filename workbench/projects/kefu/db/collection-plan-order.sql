-- 三类任务共用优先级；只影响尚未执行的任务，不打断正在运行的采集。
CREATE TABLE IF NOT EXISTS collection_plan_order (
  kind TEXT PRIMARY KEY CHECK(kind IN('score','reviews','reception')),
  position INTEGER NOT NULL UNIQUE CHECK(position BETWEEN 0 AND 2)
);
INSERT OR IGNORE INTO collection_plan_order(kind,position) VALUES('score',0),('reviews',1),('reception',2);
INSERT OR IGNORE INTO collection_schema(version) VALUES(6);
