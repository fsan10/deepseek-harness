import unittest
from types import SimpleNamespace
from unittest.mock import patch

from commerce_api.integrations.legacy.environment import prepare
from commerce_api.integrations.legacy.notifications import failure_message, notify


class NotificationClassificationTests(unittest.IsolatedAsyncioTestCase):
    def test_generic_failure_uses_generic_formatter(self):
        prepare()
        from apps.feishu_ai.service import FeishuService
        profile = SimpleNamespace(platform="douyin", shop="示例店铺")
        message = failure_message(FeishuService, {"mention_open_ids": []}, profile,
            "资金报表失败 token=private-value https://example.test/private")
        text = str(message)
        self.assertIn("自动化任务 · 失败", text)
        self.assertIn("资金报表失败", text)
        self.assertNotIn("滑块", text)
        self.assertNotIn("自动化登录提醒", text)
        self.assertNotIn("private-value", text)
        self.assertNotIn("example.test", text)

    async def test_generic_failure_does_not_call_handoff(self):
        with patch("commerce_api.integrations.legacy.notifications._send", return_value=True) as send:
            self.assertTrue(await notify(SimpleNamespace(platform="douyin", shop="示例店铺"), "测试分类"))
        send.assert_called_once()
