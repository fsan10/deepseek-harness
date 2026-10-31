from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from scripts.auto_download.playwright.jd_order_download import _request_stateful_answer


class JDChallengeResumeTests(unittest.TestCase):
    def test_expired_challenge_registers_before_resending_password(self):
        with tempfile.TemporaryDirectory() as directory:
            state = {"file_password_challenge_id": "old-challenge", "password_requested": True}
            path = Path(directory) / "state.json"
            resend = AsyncMock()
            calls = []
            async def register(**kwargs):
                calls.append('register')
                return {"challenge_id": "new-challenge", "timeout_seconds": 300}
            async def send():
                calls.append('send')
            resend.side_effect = send
            with patch(
                "scripts.auto_download.playwright.jd_order_download.wait_answer",
                new=AsyncMock(side_effect=[RuntimeError("自动化 Challenge 已过期"), "new-password"]),
            ) as wait, patch(
                "scripts.auto_download.playwright.jd_order_download.create_challenge",
                new=AsyncMock(side_effect=register),
            ) as create, patch(
                "scripts.auto_download.playwright.jd_order_download.probe_relay"
            ):
                answer = asyncio.run(_request_stateful_answer(
                    challenge_key="file_password_challenge_id",
                    platform="京东", company="测试公司", shop="测试店铺",
                    purpose="测试文件提取码", page_url="",
                    state_path=path, state=state,
                    before_new_challenge=resend,
                ))
            self.assertEqual("new-password", answer)
            resend.assert_awaited_once()
            self.assertEqual(2, wait.await_count)
            create.assert_awaited_once()
            self.assertEqual(calls, ['register', 'send'])
            self.assertNotIn("file_password_challenge_id", state)

    def test_transient_wait_timeout_keeps_original_challenge_and_does_not_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            state = {"file_password_challenge_id": "old-challenge", "password_requested": True}
            resend = AsyncMock()
            with patch(
                "scripts.auto_download.playwright.jd_order_download.wait_answer",
                new=AsyncMock(side_effect=TimeoutError("still waiting")),
            ), patch(
                "scripts.auto_download.playwright.jd_order_download.create_challenge",
                new=AsyncMock(),
            ) as create:
                with self.assertRaises(TimeoutError):
                    asyncio.run(_request_stateful_answer(
                        challenge_key="file_password_challenge_id",
                        platform="京东", company="测试公司", shop="测试店铺",
                        purpose="测试文件提取码", page_url="",
                        state_path=Path(directory) / "state.json", state=state,
                        before_new_challenge=resend,
                    ))
            self.assertEqual("old-challenge", state["file_password_challenge_id"])
            resend.assert_not_awaited()
            create.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
