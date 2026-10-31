import asyncio
import json
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from commerce_api.core.contracts import Period, ReportRequest
from commerce_api.core.errors import AuthRequired, ChallengeExpired, ContractError, LockBusy, NeedsHuman, NotReady, OutcomeUnknown
from commerce_api.core.registry import Registry
from commerce_api.runtime.engine import Context, Engine
from commerce_api.runtime.files import receipt
from commerce_api.runtime.runs import Run
from commerce_api.runtime.sessions import SessionStore, session_key
from commerce_api.runtime.storage import file_lock
from commerce_api.runtime.health import check_due, set_policy, watch
from commerce_api.runtime.auth import AuthManager
from commerce_api.runtime.storage import read_json
from .support import owned_temporary, fictional_profile


class FakeClient:
    credential = {"identity": {"shop_id": "fictional"}}
    identity_data = {}
    async def close(self):
        pass


class FakeAuth:
    def __init__(self):
        self.checks = self.logins = 0
    async def check(self, *args, **kwargs):
        self.checks += 1
    async def login(self, *args, **kwargs):
        self.logins += 1
    def client(self, *args):
        return FakeClient()


async def deliver(ctx, request):
    target = ctx.paths.root / "downloads" / ctx.run.id / "result.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("date,total\n2026-10-28,1\n", encoding="utf-8")
    ctx.run.state["files"].append(receipt(target, period=request.period.public()))
    return ctx.result(row_count=1)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.paths = owned_temporary(self)
        self.profile = fictional_profile(self.paths)
        self.request = ReportRequest("douyin", "fund", "merchant", self.profile.name,
            Period(date(2026, 10, 28), date(2026, 10, 28)), timeout=.1, poll_interval=.01)
        self.auth = FakeAuth()
        self.engine = Engine(self.paths, auth=self.auth, use_legacy_lock=False)

    async def test_login_timeout_preserves_human_state_and_returns(self):
        store = SimpleNamespace(load=lambda key: (_ for _ in ()).throw(AuthRequired("fictional missing session")))
        manager = AuthManager(self.paths, Registry(), store=store, login_timeout=.01)
        backend = Registry().backend("douyin", "merchant")
        async def waiting(*args, **kwargs):
            await asyncio.sleep(10)
        with patch("commerce_api.integrations.legacy.login.authenticate", new=waiting):
            with self.assertRaises(NeedsHuman):
                await manager.login(self.profile, backend)
        state = read_json(self.paths.file("health", session_key(self.profile.id, "douyin", "merchant")))
        self.assertEqual(state["state"], "needs_human")
        self.assertFalse(list((self.paths.root / "sessions").glob("*.enc")))

    async def test_repeated_business_request_reuses_success_without_auth_or_export(self):
        handler = AsyncMock(side_effect=deliver)
        with patch("commerce_api.runtime.engine.load_symbol", return_value=handler):
            first = await self.engine.execute(self.request)
            self.request.timeout = 99
            second = await self.engine.execute(self.request)
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(second["status"], "reused")
        self.assertEqual(handler.await_count, 1)
        self.assertEqual(self.auth.checks, 1)

    async def test_recovered_and_cached_success_clear_stale_active_error(self):
        handler = AsyncMock(side_effect=NeedsHuman("fictional verification required"))
        with patch("commerce_api.runtime.engine.load_symbol", return_value=handler), patch(
            "commerce_api.integrations.legacy.notifications.notify", new=AsyncMock(return_value=True)):
            with self.assertRaises(NeedsHuman):
                await self.engine.execute(self.request)
        with patch("commerce_api.runtime.engine.load_symbol", new=lambda _: deliver):
            completed = await self.engine.execute(self.request)
        run = Run.load(self.paths, completed["run_id"])
        self.assertIsNone(run.state["error"])
        # Compatibility for a completed Run created before the fix.
        run.update(error={"code": "OLD_FICTIONAL_ERROR"})
        reused = await self.engine.execute(self.request)
        self.assertEqual(reused["status"], "reused")
        self.assertIsNone(Run.load(self.paths, run.id).state["error"])

    async def test_unknown_submission_never_replays_on_fresh_cli_invocation(self):
        effects = []
        async def send():
            effects.append(1)
            raise OutcomeUnknown("fictional transport uncertainty")
        async def handler(ctx, request):
            await ctx.submit("create_export", send)
        with patch("commerce_api.runtime.engine.load_symbol", return_value=handler), patch(
            "commerce_api.integrations.legacy.notifications.notify", new=AsyncMock(return_value=False)):
            for _ in range(2):
                with self.assertRaises(OutcomeUnknown):
                    await self.engine.execute(self.request)
        self.assertEqual(len(effects), 1)

    async def test_confirmed_auth_expiry_recovers_at_most_once(self):
        calls = []
        async def handler(ctx, request):
            calls.append(1)
            if len(calls) == 1:
                raise AuthRequired("fictional expired session")
            return await deliver(ctx, request)
        with patch("commerce_api.runtime.engine.load_symbol", return_value=handler):
            await self.engine.execute(self.request)
        self.assertEqual(self.auth.logins, 1)
        self.assertEqual(len(calls), 2)

    async def test_initial_recovery_and_handler_share_one_login_budget(self):
        self.auth.check = AsyncMock(side_effect=AuthRequired("initial expiry"))
        handler = AsyncMock(side_effect=AuthRequired("still expired"))
        with patch("commerce_api.runtime.engine.load_symbol", return_value=handler), patch(
            "commerce_api.integrations.legacy.notifications.notify", new=AsyncMock(return_value=False)):
            with self.assertRaises(AuthRequired):
                await self.engine.execute(self.request)
        self.assertEqual(self.auth.logins, 1)
        self.assertEqual(handler.await_count, 1)

    async def test_busy_lock_does_not_leave_an_orphan_run(self):
        key = session_key(self.profile.id, "douyin", "merchant")
        with file_lock(self.paths.file("locks", key, ".lock")):
            with self.assertRaises(LockBusy):
                await self.engine.execute(self.request)
        self.assertFalse((self.paths.root / "runs").exists())

    async def test_uncertain_sms_waits_existing_challenge_without_resending(self):
        run = Run.create(self.paths, self.request, self.profile.id)
        run.state["operations"]["verification"] = {"status": "unknown", "challenge_id": "fictional-challenge"}
        ctx = Context(self.paths, run, self.profile, Registry().backend("douyin", "merchant"), FakeClient())
        send = AsyncMock()
        with patch("commerce_api.integrations.legacy.verification.answer", new=AsyncMock(return_value="fictional-answer")):
            self.assertEqual(await ctx.verification(purpose="test", send=send), "fictional-answer")
        send.assert_not_awaited()
        self.assertNotIn("fictional-answer", self.paths.file("runs", run.id).read_text(encoding="utf-8"))

    async def test_expired_archive_listener_renews_once_using_legacy_callback_policy(self):
        run = Run.create(self.paths, self.request, self.profile.id)
        run.state["operations"]["archive_password"] = {"status": "sent", "challenge_id": "expired-example"}
        ctx = Context(self.paths, run, self.profile, Registry().backend("douyin", "merchant"), FakeClient())
        sender = AsyncMock()
        creator = AsyncMock(return_value={"challenge_id": "new-example"})
        with patch("commerce_api.integrations.legacy.verification.answer", new=AsyncMock(side_effect=[
            ChallengeExpired("expired"), "fictional-answer"])), patch(
            "commerce_api.integrations.legacy.verification.create", new=creator):
            await ctx.verification(purpose="test", send=sender, kind="archive_password", name="archive_password")
        sender.assert_awaited_once()
        self.assertTrue(creator.call_args.kwargs["force_human"])
        self.assertEqual(run.state["operations"]["archive_password"]["previous_challenge_id"], "expired-example")

    async def test_jd_password_challenge_uses_platform_task_id(self):
        run = Run.create(self.paths, self.request, self.profile.id)
        run.confirmed("create_export", task_id="123456")
        profile = SimpleNamespace(platform="jd")
        ctx = Context(self.paths, run, profile, Registry().backend("jd", "merchant"), FakeClient())
        creator = AsyncMock(return_value={"challenge_id": "fictional-challenge"})
        with patch("commerce_api.integrations.legacy.verification.create", new=creator):
            await ctx.register_verification(purpose="test", kind="archive_password", name="archive_password")
        self.assertEqual(creator.call_args.kwargs["reference"], "taskid-123456")

    async def test_poll_deadline_bounds_slow_query(self):
        run = Run.create(self.paths, self.request, self.profile.id)
        ctx = Context(self.paths, run, self.profile, Registry().backend("douyin", "merchant"), FakeClient())
        with self.assertRaises(NotReady):
            await ctx.poll(lambda: asyncio.sleep(1), lambda row: None)

    async def test_disabled_health_does_not_resolve_profiles_or_create_auth_manager(self):
        with patch("commerce_api.runtime.health.AuthManager", side_effect=AssertionError("unexpected auth")), patch(
            "commerce_api.runtime.health.profile_binding", side_effect=AssertionError("unexpected profile lookup")):
            self.assertFalse((await check_due(self.paths, Registry()))["enabled"])
            self.assertEqual((await watch(self.paths, Registry()))["cycles"], 0)


class GenerationTests(unittest.TestCase):
    def test_old_refresh_cannot_overwrite_new_login_or_resurrect_logout(self):
        paths = owned_temporary(self)
        def codec(value, **kwargs):
            return value
        store = SessionStore(paths, codec=codec)
        old = store.save("example", {"identity": {"shop_id": "old"}})
        current = store.save("example", {"identity": {"shop_id": "current"}})
        self.assertFalse(store.refresh("example", old))
        self.assertEqual(store.load("example")["generation"], current["generation"])
        store.delete("example")
        self.assertFalse(store.refresh("example", current))
        self.assertFalse(paths.file("sessions", "example", ".enc").exists())
