import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from automation.collection_accounts import initialize_accounts
from automation.collection_queue import run_next
from automation.metric_profiles import sync_profiles
from automation.metric_worker import enqueue, execute_run, schedule_due
from automation.review_errors import ContractError


class ReceptionScheduleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "schedule.sqlite"
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        initialize_accounts(self.db)
        profiles = [{"profile_id": identifier, "profile_name": "DY-抖音-" + identifier,
                     "platform": "douyin", "company": "测试公司", "expected_shop_name": identifier,
                     "excluded": 0, "exclusion_reason": ""} for identifier in ("p1", "p2")]
        sync_profiles(self.db, profiles, [{"platform": "抖音", "name": identifier, "score": True,
                                          "reception": True} for identifier in ("p1", "p2")])
        self.current = datetime(2026, 10, 28, 3, 30, tzinfo=timezone.utc)
        self.due = "2026-10-28T03:22:00+00:00"
        self.clock = patch("automation.metric_worker.datetime", wraps=datetime).start()
        self.clock.now.side_effect = lambda tz=None: self.current.astimezone(tz)
        self.addCleanup(patch.stopall)
        self.fetches = []
        self.fetch = patch("automation.metric_worker.fetch_metrics", side_effect=self.fetch_metrics).start()
        patch("automation.metric_worker.import_records", new=AsyncMock(return_value=1)).start()
        patch("automation.metric_worker.queue_alert").start()
        self.enable_schedule()

    def tearDown(self):
        self.db.close()
        self.temporary.cleanup()

    def enable_schedule(self, *, lookback=1, frequency=1):
        with self.db:
            self.db.execute("UPDATE metric_collection_settings SET enabled=1,run_at='11:22',"
                            "lookback_days=?,frequency_days=?,next_run_at=? WHERE kind='reception'",
                            (lookback, frequency, self.due))

    def unfinished(self, day, *, finished_at="2026-10-27T03:22:20+00:00"):
        run_id = enqueue(self.db, {"kind": "reception", "trigger_type": "scheduled",
                                   "from": day, "to": day})["id"]
        with self.db:
            self.db.execute("UPDATE metric_runs SET status='partial',created_at=?,finished_at=? WHERE id=?",
                            (finished_at, finished_at, run_id))
            self.db.execute("UPDATE metric_run_items SET status='success',report_date=?,record_count=1,"
                            "import_request_id='saved-checkpoint',finished_at=? WHERE run_id=? AND profile_id='p1'",
                            (day, finished_at, run_id))
            self.db.execute("UPDATE metric_run_items SET status='failed',finished_at=? "
                            "WHERE run_id=? AND profile_id='p2'", (finished_at, run_id))
        return run_id

    async def fetch_metrics(self, profile, kind, day):
        self.fetches.append((profile["profile_id"], day.isoformat()))
        return {"identity": {"shop_name": profile["shop_name"], "shop_id": profile["profile_id"]},
                "records": [{"value": 1}], "report_date": day.isoformat(), "source_metric": "测试口径"}

    def next_schedule(self):
        return self.db.execute("SELECT next_run_at FROM metric_collection_settings WHERE kind='reception'").fetchone()[0]

    async def complete_run(self, day, *, trigger="manual", profiles=None):
        run_id = enqueue(self.db, {"kind": "reception", "trigger_type": trigger, "from": day, "to": day,
                                   "profileIds": profiles or []})["id"]
        await execute_run(self.db, self.db.execute("SELECT * FROM metric_runs WHERE id=?", (run_id,)).fetchone())
        return run_id

    def advance_day(self):
        self.current = datetime(2026, 10, 29, 3, 30, tzinfo=timezone.utc)
        self.due = "2026-10-29T03:22:00+00:00"
        self.enable_schedule()

    async def test_manual_success_for_all_shops_prevents_recollecting_old_day(self):
        await self.complete_run("2026-10-26", trigger="scheduled")
        await self.complete_run("2026-10-27")
        self.advance_day()
        self.fetches.clear()
        self.assertTrue(await run_next(self.db))
        self.assertEqual(self.fetches, [("p1", "2026-10-28"), ("p2", "2026-10-28")])
        latest = self.db.execute("SELECT start_date,end_date FROM metric_runs ORDER BY created_at DESC,id DESC LIMIT 1").fetchone()
        self.assertEqual(tuple(latest), ("2026-10-28", "2026-10-28"))

    async def test_manual_subset_only_reuses_those_shop_date_checkpoints(self):
        await self.complete_run("2026-10-26", trigger="scheduled")
        manual_id = await self.complete_run("2026-10-27", profiles=["p1"])
        saved = self.db.execute("SELECT import_request_id FROM metric_run_items WHERE run_id=?", (manual_id,)).fetchone()[0]
        self.advance_day()
        self.fetches.clear()
        self.assertTrue(await run_next(self.db))
        self.assertEqual(self.fetches, [("p1", "2026-10-28"), ("p2", "2026-10-27"), ("p2", "2026-10-28")])
        reused = self.db.execute("SELECT import_request_id,message FROM metric_run_items WHERE run_id<>? "
                                 "AND profile_id='p1' AND requested_date='2026-10-27'", (manual_id,)).fetchone()
        self.assertEqual(reused["import_request_id"], saved)
        self.assertIn("复用", reused["message"])

    async def test_scheduled_retry_reuses_successful_manual_repair(self):
        old_id = self.unfinished("2026-10-26")
        await self.complete_run("2026-10-26", profiles=["p2"])
        self.fetches.clear()
        self.assertTrue(await run_next(self.db))
        self.assertEqual(self.fetches, [])
        row = self.db.execute("SELECT status,message FROM metric_run_items WHERE run_id=? AND profile_id='p2'", (old_id,)).fetchone()
        self.assertEqual(row["status"], "success")
        self.assertIn("复用", row["message"])

    async def test_old_retry_is_followed_by_current_period_and_keeps_successful_checkpoint(self):
        old_id = self.unfinished("2026-10-26")
        checkpoint = tuple(self.db.execute("SELECT * FROM metric_run_items WHERE run_id=? AND profile_id='p1'", (old_id,)).fetchone())
        self.assertTrue(await run_next(self.db))
        self.assertEqual(self.next_schedule(), self.due)
        self.assertEqual(tuple(self.db.execute("SELECT * FROM metric_run_items WHERE run_id=? AND profile_id='p1'", (old_id,)).fetchone()), checkpoint)
        self.assertTrue(await run_next(self.db))
        self.assertFalse(await run_next(self.db))
        self.assertEqual(self.fetches, [("p2", "2026-10-26"), ("p1", "2026-10-27"), ("p2", "2026-10-27")])
        self.assertEqual([tuple(row) for row in self.db.execute("SELECT start_date,end_date,status FROM metric_runs ORDER BY created_at")],
                         [("2026-10-26", "2026-10-26", "success"), ("2026-10-27", "2026-10-27", "success")])
        self.assertEqual(self.next_schedule(), "2026-10-29T03:22:00+00:00")

    async def test_failed_old_retry_does_not_block_current_period_or_loop(self):
        old_id = self.unfinished("2026-10-26")
        fetch = self.fetch_metrics
        async def fail_one(profile, kind, day):
            result = await fetch(profile, kind, day)
            if profile["profile_id"] == "p2":
                raise ContractError("平台接口失败")
            return result
        self.fetch.side_effect = fail_one
        self.assertTrue(await run_next(self.db))
        self.assertTrue(await run_next(self.db))
        self.assertFalse(await run_next(self.db))
        self.assertEqual(self.fetches, [("p2", "2026-10-26"), ("p1", "2026-10-27"), ("p2", "2026-10-27")])
        self.assertEqual(self.db.execute("SELECT status FROM metric_runs WHERE id=?", (old_id,)).fetchone()[0], "partial")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM metric_runs").fetchone()[0], 2)
        self.assertEqual(self.next_schedule(), "2026-10-29T03:22:00+00:00")

    async def test_retry_already_covering_current_period_does_not_create_duplicate(self):
        self.unfinished("2026-10-27", finished_at="2026-10-28T03:00:00+00:00")
        self.assertTrue(await run_next(self.db))
        self.assertFalse(await run_next(self.db))
        self.assertEqual(self.fetches, [("p2", "2026-10-27")])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM metric_runs").fetchone()[0], 1)
        self.assertEqual(self.next_schedule(), "2026-10-29T03:22:00+00:00")

    async def test_pending_current_period_survives_database_reopen(self):
        self.unfinished("2026-10-26")
        self.assertTrue(await run_next(self.db))
        self.db.close()
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        initialize_accounts(self.db)
        self.assertTrue(await run_next(self.db))
        self.assertFalse(await run_next(self.db))
        self.assertEqual(self.fetches[-2:], [("p1", "2026-10-27"), ("p2", "2026-10-27")])

    async def test_multiple_old_failures_are_tried_once_before_current_period(self):
        self.unfinished("2026-10-25", finished_at="2026-10-26T03:22:20+00:00")
        self.unfinished("2026-10-26")
        fetch = self.fetch_metrics
        async def fail_old(profile, kind, day):
            result = await fetch(profile, kind, day)
            if day.isoformat() < "2026-10-27":
                raise ContractError("旧日期接口失败")
            return result
        self.fetch.side_effect = fail_old
        for _ in range(3):
            self.assertTrue(await run_next(self.db))
        self.assertFalse(await run_next(self.db))
        self.assertEqual(self.fetches, [("p2", "2026-10-25"), ("p2", "2026-10-26"),
                                       ("p1", "2026-10-27"), ("p2", "2026-10-27")])

    async def test_followup_keeps_configured_lookback_and_frequency(self):
        self.enable_schedule(lookback=3, frequency=2)
        self.unfinished("2026-10-26")
        self.assertTrue(await run_next(self.db))
        schedule_due(self.db, self.current)
        current = self.db.execute("SELECT start_date,end_date FROM metric_runs WHERE status='queued'").fetchone()
        self.assertIsNotNone(current)
        self.assertEqual(tuple(current), ("2026-10-25", "2026-10-27"))
        self.assertEqual(self.next_schedule(), "2026-10-30T03:22:00+00:00")

    async def test_failed_retry_does_not_hide_an_earlier_uncollected_gap(self):
        previous = enqueue(self.db, {"kind": "reception", "trigger_type": "scheduled",
                                     "from": "2026-10-23", "to": "2026-10-23"})["id"]
        with self.db:
            self.db.execute("UPDATE metric_runs SET status='success',created_at='2026-10-24T03:22:00+00:00',"
                            "finished_at='2026-10-24T03:22:20+00:00' WHERE id=?", (previous,))
            self.db.execute("UPDATE metric_run_items SET status='success' WHERE run_id=?", (previous,))
        self.unfinished("2026-10-26")
        self.fetch.side_effect = ContractError("旧日期接口失败")
        self.assertTrue(await run_next(self.db))
        schedule_due(self.db, self.current)
        current = self.db.execute("SELECT start_date,end_date FROM metric_runs WHERE status='queued'").fetchone()
        self.assertEqual(tuple(current), ("2026-10-24", "2026-10-27"))


if __name__ == "__main__":
    unittest.main()
