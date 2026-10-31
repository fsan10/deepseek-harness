import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { initializeCollectionAccounts } from "../lib/collection-accounts.ts";

test("web runtime merges the legacy registry atomically and keeps the shared identity mapping", () => {
  const db = new DatabaseSync(":memory:");
  db.exec("PRAGMA foreign_keys=ON");
  for (const name of ["reviews.sql", "metrics-collection.sql"]) db.exec(fs.readFileSync(new URL(`../db/${name}`, import.meta.url), "utf8"));
  db.exec(`INSERT INTO review_profiles(profile_id,profile_name,shop_name,last_seen_at) VALUES('p','DY-抖音-测试店','实际店铺','2026-10-21');
    INSERT INTO metric_profiles(profile_id,profile_name,platform,shop_name,last_seen_at) VALUES('p','DY-抖音-测试店','douyin','入库映射','2026-10-22');
    INSERT INTO review_auth_status(profile_id,state,message,checked_at) VALUES('p','valid','有效','2026-10-22T01:00:00Z');`);
  initializeCollectionAccounts(db);
  assert.equal(db.prepare("SELECT shop_name FROM metric_profiles").get().shop_name, "入库映射");
  assert.equal(db.prepare("SELECT shop_name FROM review_profiles").get().shop_name, "实际店铺");
  assert.equal(db.prepare("SELECT state FROM metric_auth_status").get().state, "valid");
  assert.equal(db.prepare("SELECT auth_check_enabled FROM metric_profiles").get().auth_check_enabled, 1);
  db.exec("UPDATE metric_profiles SET auth_check_enabled=0");
  assert.throws(() => db.exec("UPDATE metric_profiles SET auth_check_enabled=2"));
  db.exec("UPDATE metric_profiles SET disabled=1; UPDATE review_auth_settings SET check_interval_minutes=29;");
  initializeCollectionAccounts(db);
  assert.equal(db.prepare("SELECT excluded FROM review_profiles").get().excluded, 1);
  assert.equal(db.prepare("SELECT auth_poll_minutes FROM metric_service_settings").get().auth_poll_minutes, 29);
  assert.equal(db.prepare("SELECT auth_check_enabled FROM metric_profiles").get().auth_check_enabled, 0);
  assert.deepEqual(db.prepare("PRAGMA foreign_key_check").all(), []);
  db.close();
});

test("web runtime rolls back a conflicting profile without overwriting either registry", () => {
  const db = new DatabaseSync(":memory:");
  for (const name of ["reviews.sql", "metrics-collection.sql"]) db.exec(fs.readFileSync(new URL(`../db/${name}`, import.meta.url), "utf8"));
  db.exec(`INSERT INTO review_profiles(profile_id,profile_name,shop_name,last_seen_at) VALUES('p','DY-抖音-测试店','评论店铺','2026-10-21');
    INSERT INTO metric_profiles(profile_id,profile_name,platform,last_seen_at) VALUES('p','JD-京东-测试店','jd','2026-10-22');`);
  assert.throws(() => initializeCollectionAccounts(db), /平台不一致/);
  assert.equal(db.prepare("SELECT type FROM sqlite_master WHERE name='review_profiles'").get().type, "table");
  assert.equal(db.prepare("SELECT platform FROM metric_profiles").get().platform, "jd");
  assert.equal(db.prepare("SELECT shop_name FROM review_profiles").get().shop_name, "评论店铺");
  db.close();
});
