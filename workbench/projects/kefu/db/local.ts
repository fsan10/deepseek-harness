import fs from "node:fs";
import path from "node:path";
import { DatabaseSync, type SQLInputValue } from "node:sqlite";
import { REPORTING_SHOPS } from "@/db/reporting-config";

type GlobalDatabase = typeof globalThis & { __kefuDatabase?: DatabaseSync };

function databasePath() {
  const configured = process.env.KEFU_DB_PATH?.trim();
  return configured ? path.resolve(configured) : path.join(process.cwd(), "data", "kefu.sqlite");
}

function hasSchema(database: DatabaseSync) {
  const row = database.prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'daily_records'").get();
  return Boolean(row);
}

function initialize(database: DatabaseSync) {
  database.exec("PRAGMA foreign_keys = ON; PRAGMA journal_mode = WAL; PRAGMA busy_timeout = 5000;");
  if (!hasSchema(database)) {
    const seedPath = path.join(process.cwd(), "drizzle", "0000_kefu_initial.sql");
    if (!fs.existsSync(seedPath)) throw new Error(`找不到初始数据库脚本：${seedPath}`);
    database.exec(fs.readFileSync(seedPath, "utf8"));
  }
  migrateReportingScopes(database);
}

function migrateReportingScopes(database: DatabaseSync) {
  const columns = new Set(
    (database.prepare("PRAGMA table_info(shops)").all() as { name: string }[]).map((column) => column.name),
  );
  if (!columns.has("score_enabled")) database.exec("ALTER TABLE shops ADD COLUMN score_enabled INTEGER NOT NULL DEFAULT 0");
  if (!columns.has("reception_enabled")) database.exec("ALTER TABLE shops ADD COLUMN reception_enabled INTEGER NOT NULL DEFAULT 0");
  database.exec(
    "CREATE INDEX IF NOT EXISTS shops_score_enabled_idx ON shops(score_enabled, platform, name);" +
    "CREATE INDEX IF NOT EXISTS shops_reception_enabled_idx ON shops(reception_enabled, platform, name);",
  );

  database.exec("BEGIN IMMEDIATE");
  try {
    database.prepare("UPDATE shops SET score_enabled = 0, reception_enabled = 0 WHERE kind = 'own'").run();
    const upsert = database.prepare(
      `INSERT INTO shops (name, platform, kind, score_enabled, reception_enabled)
       VALUES (?, ?, 'own', ?, ?)
       ON CONFLICT(name, platform, kind) DO UPDATE SET
         score_enabled = excluded.score_enabled,
         reception_enabled = excluded.reception_enabled`,
    );
    for (const shop of REPORTING_SHOPS) {
      upsert.run(shop.name, shop.platform, shop.score ? 1 : 0, shop.reception ? 1 : 0);
    }
    database.exec("COMMIT");
  } catch (error) {
    database.exec("ROLLBACK");
    throw error;
  }
}

export function getLocalDb() {
  const globalDatabase = globalThis as GlobalDatabase;
  if (globalDatabase.__kefuDatabase) return globalDatabase.__kefuDatabase;
  const filePath = databasePath();
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const database = new DatabaseSync(filePath);
  initialize(database);
  globalDatabase.__kefuDatabase = database;
  return database;
}

export function all<T>(sql: string, bindings: SQLInputValue[] = []) {
  return getLocalDb().prepare(sql).all(...bindings) as T[];
}

export function first<T>(sql: string, bindings: SQLInputValue[] = []) {
  return (getLocalDb().prepare(sql).get(...bindings) as T | undefined) ?? null;
}
