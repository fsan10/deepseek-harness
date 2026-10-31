import assert from "node:assert/strict";
import fs from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import { boundedPage, pageItems } from "../lib/pagination.ts";
import { reviewOrder } from "../lib/review-order.ts";
import { readReviewLogs, safeLogMessage } from "../lib/review-logs.ts";
import { rangePresets, yesterdayISO } from "../lib/date.ts";

test("pagination uses the first three and last two pages with at most five numeric buttons", () => {
  for (let pages = 1; pages <= 100; pages++) {
    for (let page = 1; page <= pages; page++) {
      const items = pageItems(page, pages);
      const numbers = items.filter((item) => typeof item === "number");
      assert.ok(numbers.length <= 5);
      assert.ok(numbers.includes(1) && numbers.includes(pages));
      assert.deepEqual(numbers, [...new Set(numbers)].sort((a, b) => a - b));
      assert.equal(items.includes("ellipsis"), pages > 5);
      if (pages > 5) assert.deepEqual(items, [1, 2, 3, "ellipsis", pages - 1, pages]);
    }
  }
});

test("page jump bounds out-of-range input and restores blank or invalid input", () => {
  assert.equal(boundedPage("999", 12, 4), 12);
  assert.equal(boundedPage("0", 12, 4), 1);
  assert.equal(boundedPage("-8", 12, 4), 1);
  assert.equal(boundedPage("", 12, 4), 4);
  assert.equal(boundedPage("NaN", 12, 4), 4);
  assert.equal(boundedPage("Infinity", 12, 4), 4);
});

test("yesterday shortcut respects a yesterday end limit without shifting to the day before", () => {
  const yesterday = yesterdayISO();
  const preset = rangePresets(yesterday).find((item) => item.key === "yesterday");
  assert.equal(preset.from, yesterday);
  assert.equal(preset.to, yesterday);
});

test("review priority applies before pagination and keeps a stable chronological tie-break", () => {
  const db = new DatabaseSync(":memory:");
  try {
    db.exec("CREATE TABLE negative_reviews (id INTEGER PRIMARY KEY, review_level TEXT, reviewed_at TEXT)");
    const insert = db.prepare("INSERT INTO negative_reviews VALUES(?,?,?)");
    for (let id = 1; id <= 25; id++) insert.run(id, "中评", "2026-10-21 12:00:00");
    insert.run(26, "差评", "2026-10-20 10:00:00");
    insert.run(27, "差评", "2026-10-20 10:00:00");
    const ordered = (sort) => db.prepare(`SELECT id FROM negative_reviews ORDER BY ${reviewOrder(new URLSearchParams({ sort }))} LIMIT 20`).all().map((row) => row.id);
    assert.deepEqual(ordered("latest").slice(0, 2), [25, 24]);
    assert.deepEqual(ordered("negative_first").slice(0, 3), [27, 26, 25]);
    assert.throws(() => reviewOrder(new URLSearchParams({sort: "id; DROP TABLE negative_reviews"})), /排序无效/);
  } finally { db.close(); }
});

test("log viewer reads real task and shop records, filters scheduled tasks and bounds pages", () => {
  const db = new DatabaseSync(":memory:");
  try {
    db.exec(fs.readFileSync(new URL("../db/reviews.sql", import.meta.url), "utf8"));
    assert.equal(readReviewLogs(db, new URLSearchParams()).pagination.total, 0);
    assert.equal(readReviewLogs(db, new URLSearchParams()).worker, null);
    const insert = db.prepare("INSERT INTO review_runs(id,trigger_type,start_date,end_date,status,message,created_at) VALUES(?,?,'2026-10-20','2026-10-20','success',?,?)");
    for (let i = 1; i <= 13; i++) {
      insert.run(`scheduled-${i}`, "scheduled", "完成", `2026-10-21T${String(i).padStart(2,"0")}:00:00Z`);
      db.prepare("INSERT INTO review_run_shops(run_id,profile_id,shop_name,status,message) VALUES(?,?,'测试店铺','success',?)").run(`scheduled-${i}`, `profile-${i}`, "Cookie: hidden-test-value");
    }
    insert.run("manual", "manual", "手动任务", "2026-10-21T23:00:00Z");
    db.exec("INSERT INTO review_worker_state VALUES(1,123,'2026-10-21T23:00:00Z','运行中')");
    const scheduled = readReviewLogs(db, new URLSearchParams({kind:"scheduled"}));
    assert.equal(scheduled.pagination.total, 13);
    assert.equal(scheduled.runs.length, 10);
    assert.ok(scheduled.runs.every((run) => run.trigger_type === "scheduled" && run.shops.length === 1));
    assert.equal(scheduled.runs[0].shops[0].message.includes("hidden-test-value"), false);
    const last = readReviewLogs(db, new URLSearchParams({kind:"scheduled",page:"999"}));
    assert.equal(last.pagination.page, 2);
    assert.equal(last.runs.length, 3);
    const service = readReviewLogs(db, new URLSearchParams({kind:"service"}));
    assert.equal(service.pagination.total, 14);
    assert.equal(service.runs[0].id, "manual");
    assert.equal(service.worker.message, "运行中");
    assert.throws(() => readReviewLogs(db, new URLSearchParams({kind:"unknown"})), /日志类型无效/);
  } finally { db.close(); }
});

test("log messages hide legacy connection addresses and credentials", () => {
  const result = safeLogMessage('request https://example.invalid/?token=test-secret Authorization: Bearer test-auth\n{"password":"test-password","token":"test-token"}\n验证码：123456');
  for (const secret of ["example.invalid", "test-secret", "test-auth", "test-password", "test-token", "123456"]) assert.equal(result.includes(secret), false);
});
