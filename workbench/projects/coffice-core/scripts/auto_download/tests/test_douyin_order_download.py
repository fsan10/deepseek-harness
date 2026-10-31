from __future__ import annotations

import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import urllib.error

from scripts.auto_download.playwright.automation_challenge import probe_relay, request_answer
from scripts.auto_download.playwright.douyin_order_common import near_thirty_days
from scripts.auto_download.playwright.douyin_order_download import (
    _EXPORT_RATE_LIMIT_RE,
    _request_stateful_answer,
    _request_verification_answer_with_retry,
    _challenge_purpose,
    extract_zip,
    select_report_file,
)


class DouyinOrderDownloadTests(unittest.TestCase):
    def test_near_thirty_days_includes_today(self):
        self.assertEqual(("2026-07-26", "2026-08-25"), near_thirty_days(today=date(2026, 8, 25)))

    def test_extract_unencrypted_zip_and_select_single_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "orders.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("orders.xlsx", b"xlsx")
            files = extract_zip(archive, root / "out")
            self.assertEqual(b"xlsx", files[0].read_bytes())
            self.assertEqual("orders.xlsx", select_report_file(files).name)

    def test_multiple_report_members_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "未找到唯一报表"):
                select_report_file([root / "a.xlsx", root / "b.csv"])

    def test_archive_password_challenge_is_sent_as_typed_request(self):
        with patch(
            "scripts.auto_download.playwright.automation_challenge.relay_settings",
            return_value=("http://relay.test", "token-not-logged"),
        ), patch(
            "scripts.auto_download.playwright.automation_challenge.json_request",
            side_effect=[
                {"challenge_id": "00000000-0000-0000-0000-000000000001", "timeout_seconds": 30},
                {"status": "answered", "challenge_type": "archive_password", "answer": "masked-in-test"},
            ],
        ) as request:
            import asyncio

            answer = asyncio.run(request_answer(
                challenge_type="archive_password", platform="抖音", company="公司",
                shop="店铺", purpose="订单报表 ZIP 解压",
            ))
            self.assertEqual("masked-in-test", answer)
            payload = request.call_args_list[0].kwargs["payload"]
            self.assertEqual("archive_password", payload["challenge_type"])

    def test_retry_purposes_are_explicit(self):
        self.assertIn("验证码错误，请重新输入。", _challenge_purpose("订单报表下载验证码", "verification_code", True))
        self.assertIn("解压密码错误，请重新输入。", _challenge_purpose("订单报表 ZIP 解压", "archive_password", True))

    def test_relay_probe_accepts_expected_route_miss(self):
        with patch(
            "scripts.auto_download.playwright.automation_challenge.relay_settings",
            return_value=("http://relay.test", "masked-token"),
        ), patch(
            "scripts.auto_download.playwright.automation_challenge.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError("http://relay.test", 404, "not found", {}, None),
        ):
            import asyncio

            # GET collection is intentionally unsupported; 404 proves the service
            # and Bearer path are reachable without creating a challenge.
            asyncio.run(asyncio.to_thread(probe_relay))

    def test_export_rate_limit_patterns_are_narrow(self):
        self.assertRegex("操作过于频繁，请稍后再试", _EXPORT_RATE_LIMIT_RE)
        self.assertRegex("5分钟内不能重复生成", _EXPORT_RATE_LIMIT_RE)
        self.assertRegex("重复提交任务", _EXPORT_RATE_LIMIT_RE)
        self.assertNotRegex("导出成功", _EXPORT_RATE_LIMIT_RE)

    def test_stateful_challenge_id_survives_transient_wait_failure(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.auto_download.playwright.douyin_order_download.create_challenge",
            return_value={"challenge_id": "00000000-0000-0000-0000-000000000002", "timeout_seconds": 30},
        ), patch(
            "scripts.auto_download.playwright.douyin_order_download.wait_answer",
            side_effect=TimeoutError("relay temporarily unavailable"),
        ):
            import asyncio

            state = {}
            state_path = Path(directory) / "state.json"
            with self.assertRaises(TimeoutError):
                asyncio.run(asyncio.wait_for(_request_stateful_answer(
                    challenge_key="verification_challenge_id",
                    challenge_type="verification_code", platform="抖音", company="公司", shop="店铺",
                    purpose="订单报表下载验证码", page_url="", state_path=state_path, state=state,
                ), timeout=2))
            self.assertEqual(
                "00000000-0000-0000-0000-000000000002",
                state.get("verification_challenge_id"),
            )

    def test_new_challenge_triggers_callback_but_resume_does_not(self):
        async def callback():
            calls.append("sms")

        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.auto_download.playwright.douyin_order_download.create_challenge",
            new=AsyncMock(return_value={"challenge_id": "00000000-0000-0000-0000-000000000003", "timeout_seconds": 30}),
        ), patch(
            "scripts.auto_download.playwright.douyin_order_download.wait_answer",
            new=AsyncMock(return_value="masked-answer"),
        ):
            import asyncio

            calls = []
            state_path = Path(directory) / "state.json"
            state = {}
            answer = asyncio.run(_request_stateful_answer(
                challenge_key="verification_challenge_id",
                challenge_type="verification_code", platform="抖音", company="公司", shop="店铺",
                purpose="订单报表下载验证码", page_url="", state_path=state_path, state=state,
                after_create=callback,
            ))
            self.assertEqual("masked-answer", answer)
            self.assertEqual(["sms"], calls)

            calls.clear()
            state["verification_challenge_id"] = "00000000-0000-0000-0000-000000000004"
            asyncio.run(_request_stateful_answer(
                challenge_key="verification_challenge_id",
                challenge_type="verification_code", platform="抖音", company="公司", shop="店铺",
                purpose="订单报表下载验证码", page_url="", state_path=state_path, state=state,
                after_create=callback,
            ))
            self.assertEqual([], calls)

    def test_relay_failure_triggers_sms_only_after_registration_recovers(self):
        request_count = 0

        async def request_answer(**kwargs):
            nonlocal request_count
            request_count += 1
            if request_count == 1:
                raise RuntimeError("自动化验证码服务 HTTP 500")
            await kwargs["after_create"]()
            return "masked-answer"

        with tempfile.TemporaryDirectory() as directory, \
                patch(
                    "scripts.auto_download.playwright.douyin_order_download.probe_relay",
                    return_value=None,
                ) as probe, \
                patch(
                    "scripts.auto_download.playwright.douyin_order_download._request_stateful_answer",
                    new=AsyncMock(side_effect=request_answer),
                ), \
                patch(
                    "scripts.auto_download.playwright.douyin_order_download._click_get_code_control",
                    new=AsyncMock(),
                ) as click_get_code:
            import asyncio

            answer = asyncio.run(_request_verification_answer_with_retry(
                SimpleNamespace(url="https://fxg.jinritemai.com/ffa/morder/order/export"),
                object(), platform="抖音", company="公司", shop="店铺",
                state_path=Path(directory) / "state.json", state={},
            ))

            self.assertEqual("masked-answer", answer)
            self.assertEqual(2, probe.call_count)
            self.assertEqual(1, click_get_code.await_count)
            self.assertTrue(click_get_code.await_args.kwargs["retry"])

    def test_preflight_relay_failure_does_not_trigger_sms_resend(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch(
                    "scripts.auto_download.playwright.douyin_order_download.probe_relay",
                    side_effect=RuntimeError("自动化验证码服务不可用"),
                ), \
                patch(
                    "scripts.auto_download.playwright.douyin_order_download._request_stateful_answer",
                    new=AsyncMock(),
                ) as request_answer, \
                patch(
                    "scripts.auto_download.playwright.douyin_order_download._click_get_code_control",
                    new=AsyncMock(),
                ) as click_get_code:
            import asyncio

            with self.assertRaisesRegex(RuntimeError, "自动化验证码服务不可用"):
                asyncio.run(_request_verification_answer_with_retry(
                    SimpleNamespace(url="https://fxg.jinritemai.com/ffa/morder/order/export"),
                    object(), platform="抖音", company="公司", shop="店铺",
                    state_path=Path(directory) / "state.json", state={},
                ))

            request_answer.assert_not_awaited()
            click_get_code.assert_not_awaited()

    def test_relay_failure_is_capped_at_three_retries(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch(
                    "scripts.auto_download.playwright.douyin_order_download.probe_relay",
                    return_value=None,
                ), \
                patch(
                    "scripts.auto_download.playwright.douyin_order_download._request_stateful_answer",
                    new=AsyncMock(side_effect=RuntimeError("自动化验证码服务 HTTP 500")),
                ), \
                patch(
                    "scripts.auto_download.playwright.douyin_order_download._click_get_code_control",
                    new=AsyncMock(),
                ) as click_get_code:
            import asyncio

            with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
                asyncio.run(_request_verification_answer_with_retry(
                    SimpleNamespace(url="https://fxg.jinritemai.com/ffa/morder/order/export"),
                    object(), platform="抖音", company="公司", shop="店铺",
                    state_path=Path(directory) / "state.json", state={},
                ))

            click_get_code.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
