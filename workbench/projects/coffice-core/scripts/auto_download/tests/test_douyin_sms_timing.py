from __future__ import annotations

import tempfile
import unittest
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from scripts.auto_download.playwright import douyin_order_download as module
from apps.automation_center.platform_atomic import execute_platform_atomic


class DouyinSmsTimingTests(unittest.IsolatedAsyncioTestCase):
    async def run_download(self, *, direct=False, wrong_otp=False, registration_failure=False):
        events = []
        state = {}
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            download = SimpleNamespace(suggested_filename="test-orders.zip")

            async def save(path):
                self.assertIn("archive_password_challenge_id", state)
                events.append("save")
                Path(path).write_bytes(b"fixture zip")

            download.save_as = save

            async def download_value():
                return download

            @asynccontextmanager
            async def expect_download(**kwargs):
                yield SimpleNamespace(value=download_value())

            confirm = Mock()
            confirm.count = AsyncMock(return_value=1)
            confirm.last = confirm
            dialog = Mock()
            dialog.get_by_role.return_value = confirm
            field = SimpleNamespace(fill=AsyncMock(side_effect=lambda _: events.append("fill")))
            button = object()
            page = SimpleNamespace(url="https://fxg.jinritemai.com/ffa/morder/order/export", expect_download=expect_download)

            async def create(**kwargs):
                events.append("arm")
                if registration_failure and events.count("arm") == 2:
                    raise RuntimeError("relay unavailable")
                self.assertEqual("archive_password", kwargs["challenge_type"])
                return {"challenge_id": f"password-{events.count('arm')}"}

            async def click(target):
                self.assertIn("archive_password_challenge_id", state)
                events.append("download_click" if target is button else "confirm")
                if target is confirm or direct:
                    # The password arrives synchronously with the platform action,
                    # before a download event or save_as can complete.
                    events.append("password_sms")

            async def otp(*args, **kwargs):
                self.assertNotIn("archive_password_challenge_id", state)
                events.append("otp")
                return "test-otp"

            async def result(*args):
                if wrong_otp:
                    raise module.VerificationCodeError("fixture verification rejection")
                return download

            with patch.object(module, "create_challenge", new=AsyncMock(side_effect=create)), \
                 patch.object(module, "cancel_challenge", new=AsyncMock(side_effect=lambda _: events.append("cancel"))), \
                 patch.object(module, "click_compat", new=AsyncMock(side_effect=click)), \
                 patch.object(module, "_find_dialog", new=AsyncMock(return_value=None)), \
                 patch.object(module, "_visible", side_effect=lambda x: x), \
                 patch.object(module, "_wait_for_download_or_verification", new=AsyncMock(
                     side_effect=lambda info, page, **kw: (download if direct else None, dialog, field, kw['download_task']))), \
                 patch.object(module, "_request_verification_answer_with_retry", new=AsyncMock(side_effect=otp)), \
                 patch.object(module, "_wait_download_or_verification_error", new=AsyncMock(side_effect=result)), \
                 patch.object(module, "reopen_for_human", new=AsyncMock(side_effect=RuntimeError("stop fixture retry"))):
                if wrong_otp or registration_failure:
                    with self.assertRaises(RuntimeError):
                        await module.download_zip_with_challenges(page, button, platform="抖音", company="测试公司",
                            shop="测试店铺", state_path=state_path, state=state)
                else:
                    result_path = await module.download_zip_with_challenges(page, button, platform="抖音", company="测试公司",
                        shop="测试店铺", state_path=state_path, state=state)
                    self.assertTrue(result_path.is_file())
        return events, state

    async def test_listener_exists_before_verification_confirm_and_immediate_password_sms(self):
        events, state = await self.run_download()
        self.assertEqual(["arm", "download_click", "cancel", "otp", "fill", "arm", "confirm", "password_sms", "save"], events)
        self.assertEqual("password-2", state["archive_password_challenge_id"])

    async def test_direct_download_arms_before_click_without_an_otp_challenge(self):
        events, _ = await self.run_download(direct=True)
        self.assertEqual(["arm", "download_click", "password_sms", "save"], events)

    async def test_wrong_otp_cancels_unused_password_listener(self):
        events, state = await self.run_download(wrong_otp=True)
        self.assertEqual("cancel", events[-1])
        self.assertNotIn("archive_password_challenge_id", state)

    async def test_failed_registration_prevents_verification_submission(self):
        events, _ = await self.run_download(registration_failure=True)
        self.assertNotIn("confirm", events)
        self.assertNotIn("password_sms", events)

    async def test_recovery_resends_notice_but_reuses_accepted_answer(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(module, "resume_challenge", new=AsyncMock(return_value={"status": "answered"})) as resume, \
             patch.object(module, "wait_answer", new=AsyncMock(return_value="fixture-password")), \
             patch.object(module, "create_challenge", new=AsyncMock()) as create:
            state = {"archive_password_challenge_id": "existing"}
            self.assertEqual("fixture-password", await module._request_stateful_answer(
                challenge_key="archive_password_challenge_id", challenge_type="archive_password",
                platform="抖音", company="测试公司", shop="测试店铺", purpose="订单报表 ZIP 解压",
                page_url="", state_path=Path(directory) / "state.json", state=state, resume_human=True))
            resume.assert_awaited_once_with("existing")
            create.assert_not_awaited()

    async def test_expired_password_recovery_creates_immediate_human_request(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(module, "resume_challenge", new=AsyncMock(return_value={"status": "expired"})), \
             patch.object(module, "wait_answer", new=AsyncMock(side_effect=[RuntimeError("自动化 Challenge 已过期"), "fixture-password"])), \
             patch.object(module, "create_challenge", new=AsyncMock(return_value={"challenge_id": "new", "timeout_seconds": 300})) as create:
            state = {"archive_password_challenge_id": "expired"}
            await module._request_stateful_answer(
                challenge_key="archive_password_challenge_id", challenge_type="archive_password",
                platform="抖音", company="测试公司", shop="测试店铺", purpose="订单报表 ZIP 解压",
                page_url="", state_path=Path(directory) / "state.json", state=state, resume_human=True)
            self.assertTrue(create.await_args.kwargs["force_human"])
            self.assertEqual("new", state["archive_password_challenge_id_last_answered"])

    async def test_recovery_reuses_last_answer_when_extraction_failed_after_receipt(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(module, "resume_challenge", new=AsyncMock(return_value={"status": "answered"})), \
             patch.object(module, "wait_answer", new=AsyncMock(return_value="fixture-password")), \
             patch.object(module, "create_challenge", new=AsyncMock()) as create:
            state = {"archive_password_challenge_id_last_answered": "received"}
            answer = await module._request_stateful_answer(
                challenge_key="archive_password_challenge_id", challenge_type="archive_password",
                platform="抖音", company="测试公司", shop="测试店铺", purpose="订单报表 ZIP 解压",
                page_url="", state_path=Path(directory) / "state.json", state=state, resume_human=True)
            self.assertEqual("fixture-password", answer)
            create.assert_not_awaited()

    async def test_formal_extract_node_requests_a_recovery_notice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "fixture.csv"
            report.write_text("test,data", encoding="utf-8")
            runner = SimpleNamespace(
                claim={"resume_count": 1}, business_date=date(2026, 10, 14),
                page=SimpleNamespace(url="https://fxg.jinritemai.com/ffa/morder/order/export"),
                _node_config=lambda node: {},
                runtime={"profile": {"platform": "抖音", "company": "测试公司", "shop": "测试店铺"},
                    "douyin_order_archive": root / "fixture.zip", "douyin_order_state_path": root / "state.json",
                    "douyin_order_state": {"archive_password_challenge_id": "pending"}})
            with patch.object(module, "_archive_requires_password", return_value=True), \
                 patch.object(module, "_request_stateful_answer", new=AsyncMock(return_value="fixture-password")) as request, \
                 patch.object(module, "extract_zip", return_value=[report]):
                await execute_platform_atomic(runner, {"component_code": "douyin.order.extract"})
            self.assertTrue(request.await_args.kwargs["resume_human"])
            self.assertEqual(report, runner.runtime["pending_artifact"]["source_path"])
