import asyncio
import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx

from automation import commerce_cli as cli, review_auth as auth, review_worker as worker
from automation.douyin_reviews import CN, COMMENT_PATH, ORDER_PATH, collect_shop
from automation.review_errors import AuthRequired, AuthStoreError, ContractError, HumanRequired, NetworkError
from automation.review_http import DirectHttpSession, SHOP_PATH
from automation.review_session_store import SessionStore

PROFILE = {"profile_id": "http-test", "profile_name": "DY-抖音-测试店", "platform": "抖音", "company": "测试公司", "shop_name": "测试店", "excluded": 0, "exclusion_reason": ""}
DAY = date(2026, 10, 20)


def credentials(profile=PROFILE, value="synthetic-test-value"):
    return {"version": 1, "session_id": "test-session-generation", "profile_id": profile["profile_id"], "user_agent": "kefu-test", "cookies": [
        {"name": "test_session", "value": value, "domain": ".jinritemai.com", "path": "/", "secure": True, "expires": -1}]}


def database():
    db = sqlite3.connect(":memory:"); db.row_factory = sqlite3.Row; db.execute("PRAGMA foreign_keys=ON")
    db.executescript((worker.PROJECT / "db/reviews.sql").read_text(encoding="utf-8"))
    worker.sync_profiles(db, [PROFILE])
    return db


class Store:
    def __init__(self): self.values = {}
    def load(self, key):
        if key not in self.values: raise AuthRequired("请登录")
        return self.values[key]
    def save(self, key, value): self.values[key] = value
    def refresh(self, key, value): self.save(key, value); return True


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_login_closes_only_owned_browser_and_preserves_human_page(self):
        for started, human in ((False, False), (True, False), (True, True)):
            with self.subTest(started=started, human=human):
                db = database(); store = Store()
                page = Mock(evaluate=AsyncMock(return_value="test-agent"), close=AsyncMock(), is_closed=lambda: False, goto=AsyncMock(), on=Mock())
                context = SimpleNamespace(pages=[], cookies=AsyncMock(return_value=credentials()["cookies"]))
                async def new_page():
                    context.pages.append(page)
                    return page
                context.new_page = new_page
                browser = SimpleNamespace(contexts=[context])
                manager = AsyncMock()
                manager.__aenter__.return_value = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=AsyncMock(return_value=browser)))
                connection = SimpleNamespace(endpoint="synthetic-endpoint", started_by_this_run=started, profile_id=PROFILE["profile_id"])
                client = SimpleNamespace(initialize=Mock(), call=Mock())
                goto = AsyncMock(side_effect=HumanRequired("需要人工验证") if human else None)
                lock = SimpleNamespace(acquire=Mock(), release=Mock())
                with patch("automation.metric_auth.shared_modules", return_value=(Mock(return_value=client), Mock(return_value=connection), goto, "https://fxg.jinritemai.com/ffa/mshop/homepage/index")), patch.object(worker, "create_browser_lock", return_value=lock), patch("playwright.async_api.async_playwright", return_value=manager), patch("automation.metric_auth.asyncio.sleep", new=AsyncMock()), patch("automation.metric_auth.check_identity", new=AsyncMock(return_value={"profile_id": PROFILE["profile_id"], "shop_name": PROFILE["shop_name"], "state": "valid", "transport": "direct_http"})):
                    if human:
                        with self.assertRaises(HumanRequired): await auth.login_profile(PROFILE, store=store, db=db)
                    else:
                        result = await auth.login_profile(PROFILE, store=store, db=db)
                        self.assertEqual(result["browser_used_for"], "login_only")
                self.assertEqual(page.close.await_count, 0 if human else 1)
                self.assertEqual(client.call.call_count, int(started and not human))
                if started and not human: client.call.assert_called_once_with("stop_profile", {"id": PROFILE["profile_id"]})
                lock.release.assert_called_once()
                self.assertEqual(db.execute("SELECT state FROM review_auth_status").fetchone()[0], "needs_human" if human else "valid")
                db.close()

    async def test_unrelated_system_proxy_is_not_inherited(self):
        with patch.dict(os.environ, {"ALL_PROXY": "socks5://127.0.0.1:1", "HTTPS_PROXY": "socks5://127.0.0.1:1", "SSL_CERT_FILE": "missing-test-ca-file"}):
            async with DirectHttpSession(PROFILE, credentials()) as session:
                self.assertFalse(session.client.is_closed)

    async def test_shop_identity_and_rotated_cookie_are_persisted(self):
        store = Store(); states = []
        def handle(request):
            self.assertEqual(request.url.path, SHOP_PATH)
            self.assertEqual(request.url.params["_bid"], "fxg_admin")
            self.assertEqual(request.headers["cookie"], "test_session=synthetic-test-value")
            return httpx.Response(200, json={"code": 0, "data": {"shop_name": "测试店"}}, headers={"set-cookie": "test_session=rotated-test-value; Domain=.jinritemai.com; Path=/; Secure"})
        async with DirectHttpSession(PROFILE, credentials(), store=store, on_state=lambda *s: states.append(s), transport=httpx.MockTransport(handle)) as session:
            result = await session.check_identity()
        self.assertEqual(result["transport"], "direct_http")
        self.assertEqual(states[-1][0], "valid")
        self.assertEqual(store.values[PROFILE["profile_id"]]["cookies"][0]["value"], "rotated-test-value")

    async def test_separate_profiles_do_not_share_cookies(self):
        second = {**PROFILE, "profile_id": "second"}
        observed = []
        def handle(request):
            observed.append(request.headers.get("cookie")); return httpx.Response(200, json={"code": 0})
        for profile, value in ((PROFILE, "test-first"), (second, "test-second")):
            async with DirectHttpSession(profile, credentials(profile, value), transport=httpx.MockTransport(handle)) as session:
                await session.get_json(SHOP_PATH, label="test")
        self.assertEqual(observed, ["test_session=test-first", "test_session=test-second"])
        with self.assertRaises(AuthRequired): DirectHttpSession(second, credentials())

    async def test_auth_expiry_has_explicit_recovery_and_does_not_start_browser(self):
        replies = [httpx.Response(401), httpx.Response(302, headers={"location": "https://fxg.jinritemai.com/login"}),
                   httpx.Response(200, json={"code": 400, "msg": "请先登录"}),
                   httpx.Response(200, text='<form id="ecomLoginForm">')]
        for response in replies:
            states = []
            with self.subTest(status=response.status_code), patch("automation.douyin_reviews.shared_modules", side_effect=AssertionError("No browser allowed")):
                async with DirectHttpSession(PROFILE, credentials(), on_state=lambda *s: states.append(s), transport=httpx.MockTransport(lambda _: response)) as session:
                    with self.assertRaises(AuthRequired): await session.check_identity()
            self.assertEqual(states[-1][0], "auth_required")

    async def test_risk_or_permission_is_never_bypassed(self):
        for response in [httpx.Response(code) for code in (403, 412, 418, 429)] + [httpx.Response(200, json={"code": 7, "msg": "需要安全验证"})]:
            states = []
            async with DirectHttpSession(PROFILE, credentials(), on_state=lambda *s: states.append(s), transport=httpx.MockTransport(lambda _: response)) as session:
                with self.assertRaises(HumanRequired): await session.check_identity()
            self.assertEqual(states[-1][0], "needs_human")

    async def test_network_failure_is_not_misreported_as_login_loss(self):
        states = []
        def handle(request): raise httpx.ConnectError("synthetic private diagnostic", request=request)
        async with DirectHttpSession(PROFILE, credentials(), on_state=lambda *s: states.append(s), transport=httpx.MockTransport(handle)) as session:
            with self.assertRaises(NetworkError) as error: await session.check_identity()
        self.assertEqual(states[-1][0], "error")
        self.assertEqual(states[-1][2], "NETWORK_ERROR")
        self.assertNotIn("private diagnostic", str(error.exception))

    async def test_bad_response_contract_is_failure_not_zero_or_valid(self):
        for response in (httpx.Response(200, text="unexpected"), httpx.Response(200, json=[]), httpx.Response(200, json={"code": 0, "data": {}})):
            states = []
            async with DirectHttpSession(PROFILE, credentials(), on_state=lambda *s: states.append(s), transport=httpx.MockTransport(lambda _: response)) as session:
                with self.assertRaises(ContractError): await session.check_identity()
            self.assertEqual(states[-1][0], "error")

    async def test_mismatched_identity_blocks_collection(self):
        states = []
        async with DirectHttpSession(PROFILE, credentials(), on_state=lambda *s: states.append(s), transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"code": 0, "data": {"shop_name": "另一个店铺"}}))) as session:
            with self.assertRaises(HumanRequired): await session.check_identity()
        self.assertEqual(states[-1][2], "SHOP_MISMATCH")

    async def test_unapproved_path_is_rejected_before_network(self):
        async with DirectHttpSession(PROFILE, credentials(), transport=httpx.MockTransport(lambda _: self.fail("must not send request"))) as session:
            with self.assertRaises(ContractError): await session.get_json("https://example.com", label="test")

    async def test_full_collection_uses_only_http_and_matches_correct_order_item(self):
        paths = []; ranks = []
        def handle(request):
            paths.append(request.url.path)
            if request.url.path == SHOP_PATH: return httpx.Response(200, json={"code": 0, "data": {"shop_name": "测试店"}})
            if request.url.path == COMMENT_PATH:
                rank = int(request.url.params["rank"]); ranks.append(rank)
                self.assertEqual(request.url.params["content_search"], "1")
                self.assertEqual(request.url.params["status_filter"], "0")
                self.assertEqual(request.url.params["reply_search"], "0")
                raw = {"id": "comment-1", "order_id": "1234567890123456789", "product_id": "product-1", "comment_time": int(datetime(2026, 10, 20, 12, tzinfo=CN).timestamp()), "content": "味道很淡", "tags": {"rank_info": {"name": "差评"}}, "product": {"name": "咖啡"}}
                return httpx.Response(200, json={"code": 0, "data": [raw] if rank == 1 else [], "page": 0, "total": 1 if rank == 1 else 0})
            self.assertEqual(request.url.path, ORDER_PATH)
            return httpx.Response(200, json={"code": 0, "data": {"product": {"sku": [{"sku_order_id": "gift", "product_id": "gift", "merchant_sku_code": "gift-code"}, {"sku_order_id": "1234567890123456789", "product_id": "product-1", "merchant_sku_code": "COFFEE-01"}]}}})
        session = DirectHttpSession(PROFILE, credentials(), transport=httpx.MockTransport(handle))
        with patch.object(auth, "client_for_profile", return_value=session), patch("automation.douyin_reviews.shared_modules", side_effect=AssertionError("No browser allowed")):
            rows = await collect_shop(dict(PROFILE), DAY, DAY, lambda _: None)
        self.assertEqual(ranks, [2, 1]); self.assertEqual(paths, [SHOP_PATH, COMMENT_PATH, COMMENT_PATH, ORDER_PATH])
        self.assertEqual(rows[0]["product_code"], "COFFEE-01")
        self.assertEqual(rows[0]["order_id"], "1234567890123456789")
        self.assertTrue(session.client.is_closed)

    async def test_missing_cache_attempts_login_then_rechecks_http(self):
        db = database()
        store = Store()
        async def logged_in(*_, **kwargs): store.save(PROFILE["profile_id"], credentials())
        with patch("automation.metric_auth.login_profile", side_effect=logged_in) as login, patch("automation.metric_auth.check_identity", new=AsyncMock(return_value={"shop_name": "测试店"})):
            await auth.check_profile(PROFILE, store=store, db=db)
        login.assert_awaited_once()
        self.assertTrue(login.call_args.kwargs["automatic"])
        self.assertEqual(db.execute("SELECT state FROM review_auth_status").fetchone()[0], "valid")
        db.close()

    async def test_automatic_login_saves_fresh_cookie_and_preserves_pinned_shop_id(self):
        db = database(); store = Store()
        page = Mock(evaluate=AsyncMock(return_value="test-agent"), close=AsyncMock(), is_closed=lambda: False, goto=AsyncMock(), on=Mock())
        context = SimpleNamespace(pages=[], cookies=AsyncMock(return_value=[]))
        async def new_page(): context.pages.append(page); return page
        context.new_page = new_page
        manager = AsyncMock()
        manager.__aenter__.return_value = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=AsyncMock(return_value=SimpleNamespace(contexts=[context]))))
        connection = SimpleNamespace(endpoint="synthetic-endpoint", started_by_this_run=True, profile_id=PROFILE["profile_id"])
        client = SimpleNamespace(initialize=Mock(), call=Mock())
        lock = SimpleNamespace(acquire=Mock(), release=Mock())
        fresh = {**credentials(value="fresh-test-value"), "captured_at": "2026-10-26T00:00:00Z", "identity": {"shop_id": "stable-test-id", "shop_name": "测试店"}}
        with db:
            db.execute("INSERT INTO metric_auth_status(profile_id,state,message,actual_shop_id,checked_at) VALUES(?,'valid','','stable-test-id','2026-10-25')", (PROFILE["profile_id"],))
        with patch("automation.metric_auth.shared_modules", return_value=(Mock(return_value=client), Mock(return_value=connection), AsyncMock(), "")), patch.object(worker, "create_browser_lock", return_value=lock), patch("playwright.async_api.async_playwright", return_value=manager), patch("automation.metric_auth.asyncio.sleep", new=AsyncMock()), patch("automation.metric_auth.await_login", new=AsyncMock(return_value=fresh)) as monitored:
            from automation.metric_auth import login_profile
            canonical = dict(db.execute("SELECT * FROM metric_profiles").fetchone())
            await login_profile(db, canonical, store=store, automatic=True)
        self.assertEqual(store.load(PROFILE["profile_id"])["cookies"][0]["value"], "fresh-test-value")
        self.assertEqual(monitored.call_args.args[4]["identity"]["shop_id"], "stable-test-id")
        page.close.assert_awaited_once(); lock.release.assert_called_once()
        client.call.assert_called_once_with("stop_profile", {"id": PROFILE["profile_id"]})
        db.close()

    async def test_polling_respects_interval_and_stops_after_expiration(self):
        db = database(); auth.record_state(PROFILE["profile_id"], "valid", "test", db=db)
        old = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
        async def expired(target, profile, **kwargs):
            auth.record_state(profile["profile_id"], "auth_required", "登录失效", db=db)
            raise AuthRequired("登录失效")
        with patch("automation.metric_auth.check_profile", side_effect=expired) as check:
            await auth.poll_auth_status(db); check.assert_not_called()
            with db: db.execute("UPDATE review_auth_status SET checked_at=?", (old,))
            await auth.poll_auth_status(db); self.assertEqual(check.await_count, 1)
            await auth.poll_auth_status(db); self.assertEqual(check.await_count, 1)
        db.close()

    async def test_http_worker_ignores_report_browser_lock(self):
        db = database(); cli.enqueue(db, {"from": "2026-10-20", "to": "2026-10-20"})
        calls = 0
        def alive(_):
            nonlocal calls
            calls += 1; return calls == 1
        async def collect(*_): return []
        with patch.object(worker, "connect", return_value=db), patch.object(worker, "parent_alive", side_effect=alive), patch.object(worker, "collect_shop", side_effect=collect) as collected, patch.object(worker, "create_browser_lock", side_effect=AssertionError("HTTP must not acquire browser lock")), patch.object(worker.asyncio, "sleep", new_callable=AsyncMock):
            await worker.worker(0)
        self.assertEqual(collected.await_count, 1)

    async def test_cli_parent_shutdown_cancels_command(self):
        entered = asyncio.Event(); cleaned = asyncio.Event()
        async def command(_):
            entered.set()
            try: await asyncio.sleep(60)
            finally: cleaned.set()
        with patch.object(cli, "dispatch", side_effect=command), patch.object(worker, "parent_alive", return_value=False):
            task = asyncio.create_task(cli.run_command(Namespace(parent_pid=123)))
            await entered.wait(); await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(task.cancelled()); self.assertTrue(cleaned.is_set())


class SessionAndCliTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_older_requests_cannot_restore_logout_or_overwrite_new_login(self):
        with tempfile.TemporaryDirectory(prefix="kefu-http-session-generation-") as folder:
            store = SessionStore(Path(folder)); original = credentials()
            store.save(PROFILE["profile_id"], original)
            rotated = credentials(value="test-rotated")
            self.assertTrue(store.refresh(PROFILE["profile_id"], rotated))
            replacement = {**credentials(value="test-new-login"), "session_id": "new-login-generation"}
            store.save(PROFILE["profile_id"], replacement)
            self.assertFalse(store.refresh(PROFILE["profile_id"], rotated))
            self.assertEqual(store.load(PROFILE["profile_id"]), replacement)
            store.delete(PROFILE["profile_id"])
            self.assertFalse(store.refresh(PROFILE["profile_id"], original))
            self.assertFalse((Path(folder) / (PROFILE["profile_id"] + ".enc")).exists())

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_cache_is_encrypted_and_rejects_corruption_or_wrong_identity(self):
        with tempfile.TemporaryDirectory(prefix="kefu-http-auth-test-") as folder:
            store = SessionStore(Path(folder)); store.save(PROFILE["profile_id"], credentials())
            path = Path(folder) / (PROFILE["profile_id"] + ".enc")
            self.assertNotIn(b"synthetic-test-value", path.read_bytes())
            self.assertEqual(store.load(PROFILE["profile_id"]), credentials())
            with self.assertRaises(AuthRequired): store.load("other-profile")
            with self.assertRaises(AuthStoreError): store.load("../escape")
            path.write_bytes(b"damaged-session")
            with self.assertRaises(AuthStoreError): store.load(PROFILE["profile_id"])
            store.delete(PROFILE["profile_id"]); self.assertFalse(path.exists())

    def invoke(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()): result = cli.main(args)
        return result, json.loads(output.getvalue())

    def test_cli_contract_for_invalid_parameters_and_unknown_platform(self):
        for args, expected in ((["--platform", "tmall", "profiles"], "NOT_SUPPORTED"), (["reviews", "fetch"], "CONTRACT_ERROR"), (["unknown"], "CONTRACT_ERROR")):
            code, result = self.invoke(args)
            self.assertEqual(code, 1); self.assertFalse(result["ok"]); self.assertEqual(result["error"]["code"], expected)
        code, result = self.invoke(["schema"])
        self.assertEqual(code, 0); self.assertEqual(result["data"]["auth"]["browser"], "explicit_login_only")

    def test_cli_keeps_network_error_distinct_from_expired_login(self):
        db = database()
        with patch.object(worker, "connect", return_value=db), patch.object(auth, "check_profile", side_effect=NetworkError("网络请求失败")):
            code, result = self.invoke(["auth", "status", "--all"])
        self.assertEqual(code, 1); self.assertEqual(result["error"]["code"], "NETWORK_ERROR")
        self.assertEqual(result["data"]["profiles"][0]["state"], "error")

    def test_queue_retries_only_failed_shops_and_keeps_history(self):
        db = database(); run = cli.enqueue(db, {"from": "2026-10-20", "to": "2026-10-20", "profileIds": [PROFILE["profile_id"], PROFILE["profile_id"]]})
        with self.assertRaises(ContractError): cli.enqueue(db, {})
        with db:
            db.execute("UPDATE review_runs SET status='partial' WHERE id=?", (run["id"],))
            db.execute("INSERT INTO review_run_shops(run_id,profile_id,shop_name,status,collected_count) VALUES(?,?,'测试店','success',5)", (run["id"], PROFILE["profile_id"]))
            db.execute("INSERT INTO review_run_shops(run_id,profile_id,shop_name,status) VALUES(?,'another','另一店','failed')", (run["id"],))
        result = cli.enqueue(db, {"retryId": run["id"]})
        self.assertEqual(result["id"], run["id"])
        self.assertEqual(tuple(db.execute("SELECT status,collected_count FROM review_run_shops WHERE profile_id=?", (PROFILE["profile_id"],)).fetchone()), ("success", 5))
        self.assertEqual(db.execute("SELECT status FROM review_run_shops WHERE profile_id='another'").fetchone()[0], "pending")
        self.assertEqual(db.execute("SELECT profile_ids FROM review_runs").fetchone()[0], json.dumps([PROFILE["profile_id"]]))
        db.close()


if __name__ == "__main__": unittest.main()
