import asyncio
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from automation.collection_accounts import initialize_accounts
from automation.collection_queue import execution_lock, next_run, plan_order, run_next, save_order
from automation.metric_profiles import sync_profiles
from automation.metric_worker import enqueue
from automation.review_errors import AuthRequired, ContractError, HumanRequired, LoginFailed, NetworkError
from automation import metric_auth

PROFILE = {"profile_id": "serial-test", "profile_name": "DY-抖音-测试店", "platform": "douyin", "company": "测试公司",
           "expected_shop_name": "测试店", "excluded": 0, "exclusion_reason": ""}


def database(path=":memory:"):
    db = sqlite3.connect(path); db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    initialize_accounts(db)
    sync_profiles(db, [PROFILE], [{"platform": "抖音", "name": "测试店", "score": True, "reception": True}])
    return db


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_time_plans_execute_in_default_order(self):
        db = database(); called = []
        due = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        with db:
            db.execute("UPDATE metric_collection_settings SET enabled=1,next_run_at=?", (due,))
            db.execute("UPDATE review_settings SET enabled=1,next_run_at=?", (due,))
        async def metric(target, run):
            called.append(run["kind"])
            with target: target.execute("UPDATE metric_runs SET status='success' WHERE id=?", (run["id"],))
        async def review(target, run):
            called.append("reviews")
            with target: target.execute("UPDATE review_runs SET status='success' WHERE id=?", (run["id"],))
        with patch("automation.metric_worker.execute_run", side_effect=metric), patch("automation.review_worker.execute_run", side_effect=review):
            for _ in range(3): self.assertTrue(await run_next(db))
        self.assertEqual(called, ["score", "reviews", "reception"])
        self.assertIsNone(next_run(db)); db.close()

    async def test_overlapping_workers_wait_and_keep_running_task(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.sqlite"
            db = database(path); other = sqlite3.connect(path); other.row_factory = sqlite3.Row
            enqueue(db, {"kind": "reception"})
            started = asyncio.Event(); finish = asyncio.Event(); called = []
            async def execute(target, run):
                called.append(run["kind"])
                with target: target.execute("UPDATE metric_runs SET status='running' WHERE id=?", (run["id"],))
                started.set(); await finish.wait()
                with target: target.execute("UPDATE metric_runs SET status='success' WHERE id=?", (run["id"],))
            with patch("automation.metric_worker.execute_run", side_effect=execute):
                task = asyncio.create_task(run_next(db)); await started.wait()
                enqueue(other, {"kind": "score"})
                self.assertFalse(await run_next(other))
                self.assertEqual(other.execute("SELECT status FROM metric_runs WHERE kind='reception'").fetchone()[0], "running")
                self.assertEqual(other.execute("SELECT status FROM metric_runs WHERE kind='score'").fetchone()[0], "queued")
                finish.set(); await task
                self.assertTrue(await run_next(other))
            self.assertEqual(called, ["reception", "score"])
            db.close(); other.close()

    async def test_os_lock_blocks_a_separate_process(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.sqlite"; db = database(path)
            code = "import sqlite3,sys; from automation.collection_queue import execution_lock; db=sqlite3.connect(sys.argv[1]); scope=execution_lock(db); print(scope.__enter__()); scope.__exit__(None,None,None); db.close()"
            with execution_lock(db) as acquired:
                self.assertTrue(acquired)
                result = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0, check=True)
                self.assertEqual(result.stdout.strip(), "False")
            with execution_lock(db) as acquired: self.assertTrue(acquired)
            db.close()

    async def test_custom_order_survives_reinitialization_and_invalid_order_rolls_back(self):
        db = database()
        save_order(db, ["reviews", "reception", "score"])
        initialize_accounts(db)
        self.assertEqual(plan_order(db), ["reviews", "reception", "score"])
        for invalid in (["score", "score", "reviews"], ["reviews"], "score", [[], "reviews", "score"]):
            with self.assertRaises(ContractError): save_order(db, invalid)
        self.assertEqual(plan_order(db), ["reviews", "reception", "score"])
        enqueue(db, {"kind": "score"}); enqueue(db, {"kind": "reception"})
        self.assertEqual(next_run(db)["kind"], "reception"); db.close()

    async def test_cancelled_owner_releases_lock_and_keeps_other_queued_run(self):
        with tempfile.TemporaryDirectory() as directory:
            db = database(Path(directory) / "queue.sqlite")
            enqueue(db, {"kind": "score"}); enqueue(db, {"kind": "reception"})
            started = asyncio.Event()
            async def execute(target, run):
                with target: target.execute("UPDATE metric_runs SET status='running' WHERE id=?", (run["id"],))
                started.set(); await asyncio.Event().wait()
            with patch("automation.metric_worker.execute_run", side_effect=execute):
                task = asyncio.create_task(run_next(db)); await started.wait(); task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.assertEqual(db.execute("SELECT status FROM metric_runs WHERE kind='score'").fetchone()[0], "failed")
            self.assertEqual(next_run(db)["kind"], "reception")
            with execution_lock(db) as acquired: self.assertTrue(acquired)
            db.close()


class LoginRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self): self.db = database()
    def tearDown(self): self.db.close()

    async def test_expiry_recovers_then_retries_same_http_operation_without_alert(self):
        operation = AsyncMock(side_effect=[AuthRequired("expired"), {"value": 7}])
        with patch.object(metric_auth, "login_profile", new=AsyncMock()) as login, patch.object(metric_auth, "queue_alert") as alert:
            self.assertEqual(await metric_auth.with_login_recovery(self.db, PROFILE, operation), {"value": 7})
        self.assertEqual(operation.await_count, 2)
        login.assert_awaited_once(); self.assertTrue(login.call_args.kwargs["automatic"])
        alert.assert_not_called()

    async def test_network_permission_and_identity_errors_do_not_login(self):
        for error in (NetworkError("network"), HumanRequired("identity mismatch"), ContractError("schema")):
            with patch.object(metric_auth, "login_profile", new=AsyncMock()) as login:
                with self.assertRaises(type(error)):
                    await metric_auth.with_login_recovery(self.db, PROFILE, AsyncMock(side_effect=error))
                login.assert_not_awaited()

    async def test_second_expiry_fails_once_and_does_not_loop_login(self):
        with patch.object(metric_auth, "login_profile", new=AsyncMock()) as login, patch.object(metric_auth, "queue_alert") as alert:
            with self.assertRaises(LoginFailed):
                await metric_auth.with_login_recovery(self.db, PROFILE, AsyncMock(side_effect=AuthRequired("expired")))
        login.assert_awaited_once(); alert.assert_called_once()

    async def test_plain_expiry_does_not_notify_group(self):
        with patch.object(metric_auth, "queue_alert") as alert:
            metric_auth.record_auth(self.db, PROFILE, "auth_required", "expired", "AUTH_REQUIRED")
        alert.assert_not_called()

    async def test_challenge_notifies_then_resumes_with_new_cookies(self):
        finished = asyncio.Event()
        async def login(): await finished.wait()
        credentials = {"identity": {"shop_name": "测试店"}}
        with patch.object(metric_auth, "login_challenge_visible", new=AsyncMock(return_value=True)), patch.object(metric_auth, "login_credentials", new=AsyncMock(side_effect=[AuthRequired("waiting"), credentials])), patch.object(metric_auth, "flush_alerts", new=AsyncMock()) as flush, patch.object(metric_auth, "queue_alert") as alert:
            result = await metric_auth.await_login(self.db, PROFILE, None, None, {}, login, timeout=3)
        self.assertEqual(result, credentials); alert.assert_called_once(); flush.assert_awaited_once()

    async def test_challenge_timeout_is_distinct_from_initial_human_notice(self):
        async def login(): await asyncio.Event().wait()
        with patch.object(metric_auth, "login_challenge_visible", new=AsyncMock(return_value=True)), patch.object(metric_auth, "login_credentials", new=AsyncMock(side_effect=AuthRequired("waiting"))), patch.object(metric_auth, "flush_alerts", new=AsyncMock()), patch.object(metric_auth, "queue_alert") as alert:
            with self.assertRaises(LoginFailed) as error:
                await metric_auth.await_login(self.db, PROFILE, None, None, {}, login, timeout=.02)
            self.assertEqual(error.exception.code, "LOGIN_TIMEOUT")
            self.assertTrue(error.exception.preserve_profile)
            self.assertEqual(alert.call_count, 1)
            metric_auth.record_auth(self.db, PROFILE, "error", str(error.exception), error.exception.code)
            self.assertEqual(alert.call_count, 2)

    async def test_iframe_slider_is_detected(self):
        hidden = SimpleNamespace(locator=Mock(return_value=SimpleNamespace(first=SimpleNamespace(is_visible=AsyncMock(return_value=False)))))
        visible = SimpleNamespace(locator=Mock(return_value=SimpleNamespace(first=SimpleNamespace(is_visible=AsyncMock(return_value=True)))))
        page = SimpleNamespace(locator=hidden.locator, frames=[hidden, visible])
        self.assertTrue(await metric_auth.login_challenge_visible(page))

    async def test_new_challenge_pauses_login_script_then_resumes_original_operation(self):
        entered = asyncio.Event(); stopped = asyncio.Event()
        async def login_script():
            entered.set()
            try: await asyncio.Event().wait()
            finally: stopped.set()
        async def visible(_): return entered.is_set()
        fresh = {"identity": {"shop_name": "测试店", "shop_id": "stable-id"}}
        async def cookies(*_):
            self.assertTrue(stopped.is_set())
            return fresh
        async def login(*_, **__):
            return await metric_auth.await_login(self.db, PROFILE, None, None, {}, login_script, timeout=3)
        operation = AsyncMock(side_effect=[AuthRequired("expired"), {"records": [1]}])
        with patch.object(metric_auth, "login_profile", new=login), patch.object(metric_auth, "login_challenge_visible", new=visible), patch.object(metric_auth, "login_credentials", new=cookies), patch.object(metric_auth, "flush_alerts", new=AsyncMock()), patch.object(metric_auth, "queue_alert") as alert:
            result = await metric_auth.with_login_recovery(self.db, PROFILE, operation)
        self.assertEqual(result, {"records": [1]})
        self.assertEqual(operation.await_count, 2)
        self.assertTrue(stopped.is_set()); alert.assert_called_once()

    async def test_error_while_waiting_for_human_preserves_profile(self):
        with patch.object(metric_auth, "login_challenge_visible", new=AsyncMock(return_value=True)), patch.object(metric_auth, "login_credentials", new=AsyncMock(side_effect=NetworkError("network"))), patch.object(metric_auth, "flush_alerts", new=AsyncMock()), patch.object(metric_auth, "queue_alert"):
            with self.assertRaises(NetworkError) as error:
                await metric_auth.await_login(self.db, PROFILE, None, None, {}, AsyncMock(), timeout=3)
        self.assertTrue(error.exception.preserve_profile)

