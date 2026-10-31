import asyncio
import contextlib
import io
import json
import logging
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfoNotFoundError

from automation.douyin_reviews import (
    CN, ContractError, api_query, collect_window, day_windows, enrich_order, normalize_comment, profile_identity,
)
from automation import review_worker as worker

PROFILE = {"profile_id": "p1", "shop_name": "测试店", "company": "测试公司"}
DAY = date(2026, 10, 20)


def comment(index=1, **overrides):
    return {"id": str(index), "order_id": "6918590111790935090", "product_id": "3844503702513779052",
            "comment_time": int(datetime(2026, 10, 20, 12, tzinfo=CN).timestamp()), "content": "包装不好，客服没处理",
            "tags": {"rank_info": {"name": "差评"}}, "product": {"name": "测试商品"}, "sku_id": "sku1", "sku": "9盒", **overrides}


def database():
    db = sqlite3.connect(":memory:"); db.row_factory = sqlite3.Row; db.execute("PRAGMA foreign_keys=ON")
    db.executescript((worker.PROJECT / "db" / "reviews.sql").read_text(encoding="utf-8"))
    return db


class ReviewsTests(unittest.TestCase):
    def test_time_boundaries_and_single_grade(self):
        middle = api_query(DAY, DAY, "中评")
        negative = api_query(DAY, DAY, "差评")
        self.assertEqual(middle["rank"], 2); self.assertEqual(negative["rank"], 1)
        self.assertEqual(middle["comment_time_to"] - middle["comment_time_from"], 86399)
        self.assertEqual(datetime.fromtimestamp(middle["comment_time_from"], CN).isoformat(), "2026-10-20T00:00:00+08:00")
        self.assertEqual((middle["content_search"], middle["status_filter"], middle["reply_search"]), (1, 0, 0))

    def test_profile_notes_and_closed_shop(self):
        item = profile_identity({"id": "p", "name": "DY-抖音-MOCK吉饮咖啡专卖店", "note": "platform=抖音;company=甲公司;shop=MOCK吉饮咖啡专卖店"})
        self.assertTrue(item["excluded"]); self.assertEqual(item["company"], "甲公司")
        with self.assertRaises(ContractError):
            profile_identity({"id": "p", "name": "DY-千川-测试店"})

    def test_reject_wrong_grade_date_or_empty_content(self):
        for raw in (comment(tags={"rank_info": {"name": "好评"}}), comment(comment_time=1), comment(content="")):
            with self.subTest(raw=raw), self.assertRaises(ContractError):
                normalize_comment(raw, PROFILE, "差评", DAY, DAY)

    def test_windows_do_not_drop_dates(self):
        windows = list(day_windows(date(2026, 1, 1), date(2026, 4, 1)))
        self.assertEqual(windows[0][0], date(2026, 1, 1)); self.assertEqual(windows[-1][1], date(2026, 4, 1))
        self.assertEqual(sum((end - start).days + 1 for start, end in windows), 91)
        for previous, following in zip(windows, windows[1:]):
            self.assertEqual((following[0] - previous[1]).days, 1)

    def test_browser_lock_path_follows_report_archive_configuration(self):
        project = Path.cwd()
        default = project / "test-archive"
        expected = default / ".automation_logs" / "all_platform_downloads" / "controller.lock"
        self.assertEqual(worker.report_lock_path({}, project_root=project, default_destination=default), expected)
        self.assertEqual(worker.report_lock_path({"destination": "archive"}, project_root=project, default_destination=default),
                         project / "archive" / ".automation_logs" / "all_platform_downloads" / "controller.lock")
        self.assertEqual(worker.report_lock_path({"destination": "archive", "log_directory": "reports-log"}, project_root=project, default_destination=default),
                         project / "reports-log" / "controller.lock")

    def test_shared_lock_timestamp_failure_releases_os_lock(self):
        with tempfile.TemporaryDirectory(prefix="kefu-review-lock-") as folder:
            path = Path(folder) / "controller.lock"
            with patch.object(worker, "report_lock_path", return_value=path):
                lock = worker.create_browser_lock("test-post-acquire-failure", logging.getLogger("test"))
                with patch("scripts.auto_download.run_all_platform_downloads.local_timestamp", side_effect=ZoneInfoNotFoundError("Asia/Shanghai")):
                    with self.assertRaises(ZoneInfoNotFoundError), worker.browser_lock_scope(lock):
                        self.fail("Broken lock initialization must not start collection")
                self.assertFalse(lock.acquired); self.assertIsNone(lock.handle)
                following = worker.create_browser_lock("test-following-attempt", logging.getLogger("test"))
                with worker.browser_lock_scope(following):
                    self.assertTrue(following.acquired)
                self.assertFalse(following.acquired); self.assertIsNone(following.handle)

    def test_shared_lock_real_contention_is_classified_as_busy(self):
        with tempfile.TemporaryDirectory(prefix="kefu-review-lock-") as folder:
            path = Path(folder) / "controller.lock"
            with patch.object(worker, "report_lock_path", return_value=path):
                owner = worker.create_browser_lock("test-lock-owner", logging.getLogger("test"))
                contender = worker.create_browser_lock("test-lock-contender", logging.getLogger("test"))
                with worker.browser_lock_scope(owner):
                    with self.assertRaises(worker.BrowserLockBusy), worker.browser_lock_scope(contender):
                        self.fail("A contending collector must stay queued")
                    self.assertTrue(owner.acquired)
                    self.assertFalse(contender.acquired)
                self.assertFalse(owner.acquired)

    def test_order_matches_reviewed_product_instead_of_gift(self):
        row = normalize_comment(comment(), PROFILE, "差评", DAY, DAY)
        enrich_order(row, {"data": {"product": {"sku": [
            {"sku_order_id": "gift", "product_id": "gift", "product_name": "赠品", "properties": [{"key": "merchant_sku_code", "text": "商家编码:WRONG"}]},
            {"sku_order_id": row["order_id"], "product_id": row["product_id"], "product_name": "正品", "properties": [{"key": "merchant_sku_code", "text": "商家编码:M-NXSY-9"}]},
        ]}}})
        self.assertEqual(row["product_code"], "M-NXSY-9"); self.assertEqual(row["product_name"], "正品")

    def test_ambiguous_sku_does_not_invent_code(self):
        row = normalize_comment(comment(), PROFILE, "差评", DAY, DAY)
        enrich_order(row, {"data": {"product": {"sku": [{"product_id": row["product_id"]}, {"product_id": row["product_id"]}]}}})
        self.assertEqual(row["enrichment_status"], "unmatched"); self.assertEqual(row["product_code"], "")

    def test_idempotent_storage_and_per_profile_identity(self):
        db = database()
        with db:
            db.execute("INSERT INTO review_runs(id,trigger_type,start_date,end_date,created_at,status) VALUES ('r','manual','2026-10-20','2026-10-20','now','success')")
            row = normalize_comment(comment(), PROFILE, "差评", DAY, DAY)
            worker.save_reviews(db, "r", [row]); worker.save_reviews(db, "r", [{**row, "product_code": "fixed"}])
            worker.save_reviews(db, "r", [{**row, "profile_id": "p2"}])
        self.assertEqual(db.execute("SELECT COUNT(*) FROM negative_reviews").fetchone()[0], 2)
        self.assertEqual(db.execute("SELECT product_code FROM negative_reviews WHERE profile_id='p1'").fetchone()[0], "fixed")
        db.close()

    def test_scheduler_catches_unfinished_period(self):
        db = database()
        with db:
            db.execute("UPDATE review_settings SET enabled=1,frequency_days=3,lookback_days=1,run_at='09:00',next_run_at='2026-10-22T00:00:00+00:00'")
            db.execute("INSERT INTO review_runs(id,trigger_type,start_date,end_date,created_at,status) VALUES ('r','scheduled','2026-10-18','2026-10-18','now','partial')")
        worker.schedule_due(db, datetime(2026, 10, 22, 4, tzinfo=timezone.utc))
        queued = db.execute("SELECT * FROM review_runs WHERE status='queued'").fetchone()
        self.assertEqual((queued["start_date"], queued["end_date"]), ("2026-10-18", "2026-10-21"))
        worker.schedule_due(db, datetime(2026, 10, 22, 4, tzinfo=timezone.utc))
        self.assertEqual(db.execute("SELECT COUNT(*) FROM review_runs WHERE status='queued'").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT next_run_at FROM review_settings").fetchone()[0], "2026-10-25T01:00:00+00:00")
        db.close()

    def test_excel_preserves_long_ids_and_untrusted_content(self):
        from openpyxl import load_workbook
        output = io.BytesIO()
        stdout = type("Output", (), {"buffer": output})()
        with patch("sys.stdin", io.StringIO(json.dumps([{"order_id": "6918590111790935090", "content": '=HYPERLINK("https://bad")'}]))), patch("sys.stdout", stdout):
            worker.export_xlsx()
        ws = load_workbook(io.BytesIO(output.getvalue())).active
        self.assertEqual(ws["E2"].value, "6918590111790935090"); self.assertEqual(ws["E2"].data_type, "s")
        self.assertEqual(ws["F2"].data_type, "s"); self.assertEqual(ws.freeze_panes, "A2")


class PaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_confirmed_browser_lock_contention_is_waiting(self):
        db = database()
        with db:
            db.execute("INSERT INTO review_runs(id,trigger_type,start_date,end_date,created_at) VALUES ('r','manual','2026-10-20','2026-10-20','now')")
        class BusyLock:
            acquired = False
            contended = True
            released = False
            def acquire(self): raise PermissionError("busy")
            def release(self): self.released = True
        lock = BusyLock()
        with patch.object(worker, "create_browser_lock", return_value=lock), patch.object(worker, "execute_run", new_callable=AsyncMock) as collect:
            await worker.execute_with_browser_lock(db, db.execute("SELECT * FROM review_runs").fetchone(), logging.getLogger("test"))
        collect.assert_not_called(); self.assertTrue(lock.released)
        run = db.execute("SELECT * FROM review_runs").fetchone()
        self.assertEqual(run["status"], "queued"); self.assertIn("等待其他浏览器任务", run["message"])
        db.close()

    async def test_timezone_and_file_errors_are_failed_and_release_the_lock(self):
        for error in (ZoneInfoNotFoundError("Asia/Shanghai"), PermissionError("cannot open lock file")):
            db = database()
            with db:
                db.execute("INSERT INTO review_runs(id,trigger_type,start_date,end_date,created_at) VALUES ('r','manual','2026-10-20','2026-10-20','now')")
            class BrokenLock:
                acquired = isinstance(error, ZoneInfoNotFoundError)
                contended = False
                released = False
                def acquire(self): raise error
                def release(self): self.released = True; self.acquired = False
            lock = BrokenLock()
            logger = logging.getLogger("test.lock-error"); logger.addHandler(logging.NullHandler())
            with patch.object(worker, "create_browser_lock", return_value=lock), patch.object(worker, "execute_run", new_callable=AsyncMock) as collect:
                await worker.execute_with_browser_lock(db, db.execute("SELECT * FROM review_runs").fetchone(), logger)
            collect.assert_not_called(); self.assertTrue(lock.released)
            run = db.execute("SELECT * FROM review_runs").fetchone()
            self.assertEqual(run["status"], "failed"); self.assertNotIn("等待", run["message"])
            if isinstance(error, ZoneInfoNotFoundError): self.assertIn("tzdata", run["message"])
            db.close()

    async def test_cancelled_collection_releases_browser_lock(self):
        db = database()
        with db:
            db.execute("INSERT INTO review_runs(id,trigger_type,start_date,end_date,created_at) VALUES ('r','manual','2026-10-20','2026-10-20','now')")
        class Lock:
            acquired = False
            def acquire(self): self.acquired = True
            def release(self): self.acquired = False
        lock = Lock(); entered = asyncio.Event()
        async def collecting(*_):
            entered.set(); await asyncio.sleep(60)
        with patch.object(worker, "create_browser_lock", return_value=lock), patch.object(worker, "execute_run", side_effect=collecting):
            task = asyncio.create_task(worker.execute_with_browser_lock(db, db.execute("SELECT * FROM review_runs").fetchone(), logging.getLogger("test")))
            await entered.wait(); self.assertTrue(lock.acquired)
            task.cancel(); await asyncio.gather(task, return_exceptions=True)
        self.assertFalse(lock.acquired); self.assertTrue(task.cancelled()); db.close()

    async def test_parent_shutdown_cancels_an_active_collection(self):
        cleanup = asyncio.Event()
        async def running_collection():
            try:
                await asyncio.sleep(60)
            finally:
                cleanup.set()
        job = asyncio.create_task(running_collection())
        await asyncio.sleep(0)
        with patch.object(worker, "parent_alive", side_effect=[True, False]):
            await worker.watch_parent(123, job, poll_interval=0.01)
        await asyncio.gather(job, return_exceptions=True)
        self.assertTrue(job.cancelled())
        self.assertTrue(cleanup.is_set())

    async def test_multi_shop_queue_skips_closed_and_advances_after_zero(self):
        db = database()
        with db:
            db.execute("INSERT INTO review_runs(id,trigger_type,start_date,end_date,created_at) VALUES ('r','manual','2026-10-20','2026-10-20','now')")
        profiles = [{**PROFILE, "profile_name": "DY-抖音-测试店", "excluded": 0, "exclusion_reason": "", "platform": "抖音"},
                    {**PROFILE, "profile_id": "p2", "profile_name": "DY-抖音-第二店", "shop_name": "第二店", "excluded": 0, "exclusion_reason": "", "platform": "抖音"},
                    {**PROFILE, "profile_id": "closed", "profile_name": "DY-抖音-关店", "excluded": 1, "exclusion_reason": "已关店", "platform": "抖音"}]
        called = []
        async def collect(profile, *args):
            called.append(profile["profile_id"])
            return [] if profile["profile_id"] == "p1" else [normalize_comment(comment(), profile, "差评", DAY, DAY)]
        worker.sync_profiles(db, profiles)
        with patch.object(worker, "list_profiles", side_effect=AssertionError("HTTP jobs must not connect to Cloak")), patch.object(worker, "collect_shop", side_effect=collect):
            await worker.execute_run(db, db.execute("SELECT * FROM review_runs").fetchone())
        self.assertEqual(called, ["p1", "p2"])
        self.assertEqual([r[0] for r in db.execute("SELECT status FROM review_run_shops ORDER BY profile_id")], ["no_data", "success"])
        self.assertEqual(db.execute("SELECT status FROM review_runs").fetchone()[0], "success")
        db.close()

    async def test_retry_preserves_successful_shop_checkpoint(self):
        db = database()
        with db:
            db.execute("INSERT INTO review_runs(id,trigger_type,start_date,end_date,created_at) VALUES ('r','manual','2026-10-20','2026-10-20','now')")
            db.execute("INSERT INTO review_run_shops(run_id,profile_id,shop_name,status,collected_count) VALUES ('r','p1','测试店','success',2)")
        profiles = [{**PROFILE, "profile_name": "DY-抖音-测试店", "excluded": 0, "exclusion_reason": "", "platform": "抖音"}]
        worker.sync_profiles(db, profiles)
        with patch.object(worker, "list_profiles", side_effect=AssertionError("HTTP jobs must not connect to Cloak")), patch.object(worker, "collect_shop") as collect:
            await worker.execute_run(db, db.execute("SELECT * FROM review_runs").fetchone())
        collect.assert_not_called()
        self.assertEqual(db.execute("SELECT collected_count FROM review_runs").fetchone()[0], 2)
        db.close()

    async def test_fetches_next_page_and_empty_grade(self):
        class Session:
            def __init__(self): self.queries = []
            async def get_json(self, path, query, **kwargs):
                self.queries.append(query)
                if query["rank"] == 2: return {"data": [], "total": 0, "page": 0}
                return {"data": [comment(i) for i in (range(1, 21) if query["page"] == 0 else [21])], "total": 21, "page": query["page"]}
        session = Session()
        rows = await collect_window(session, PROFILE, DAY, DAY, "差评", lambda _: None)
        self.assertEqual(len(rows), 21)
        self.assertEqual([q["page"] for q in session.queries], [0, 1])
        self.assertEqual(await collect_window(session, PROFILE, DAY, DAY, "中评", lambda _: None), [])

    async def test_detects_duplicate_or_missing_pages(self):
        for bad_page in ([comment(1)], []):
            class Session:
                async def get_json(self, path, query, **kwargs):
                    return {"data": [comment(1)] if query["page"] == 0 else bad_page, "total": 2, "page": query["page"]}
            with self.subTest(page=bad_page), self.assertRaises(ContractError):
                await collect_window(Session(), PROFILE, DAY, DAY, "差评", lambda _: None)


if __name__ == "__main__":
    unittest.main()
