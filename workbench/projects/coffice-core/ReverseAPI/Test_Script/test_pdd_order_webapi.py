# -*- coding: utf-8 -*-
"""拼多多订单导出任务终态回归测试。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from ReverseAPI.Formal_Script import pdd_order_export_download as order_module
from ReverseAPI.Formal_Script.pdd_order_export_download import (
    BrowserManager,
    NoDataExport,
    call_api,
    poll_export_task,
)
from ReverseAPI.Formal_Script.pdd_webapi_common import ApiError, NeedsHumanError


class FakePage:
    target_id = "fixture-target"

    def browser_fetch_json(self, url, payload, headers, timeout):
        return {
            "success": True,
            "errorCode": 0,
            "result": {
                "pageItems": [
                    {
                        "id": 123,
                        "groupStartTime": 1,
                        "groupEndTime": 2,
                        "createdTime": 100,
                        "status": 4,
                        "statusStr": "您申请导出的数据为0条，请调整查询条件后重试",
                        "progressRate": 20,
                    }
                ]
            },
        }


class FakeManager:
    start_ts = 1
    end_ts = 2

    def best_api_page(self):
        return FakePage()

    def get_dynamic_headers(self, url=None, target_id=None):
        return {}


class PddOrderWebApiTests(unittest.TestCase):
    def test_zero_data_task_is_terminal(self) -> None:
        with self.assertRaises(NoDataExport):
            poll_export_task(
                FakeManager(),
                timeout=1,
                poll_interval=0.001,
                created_after=100,
            )

    def test_existing_target_with_dead_listener_is_reconnected(self) -> None:
        class Session:
            def __init__(self, alive: bool, ws_url: str) -> None:
                self.url = "https://mms.pinduoduo.com/orders/list?tab=0"
                self.ws_url = ws_url
                self.target_id = "target-1"
                self.started_at = 0.0
                self._alive = alive
                self.closed = False

            def is_alive(self) -> bool:
                return self._alive and not self.closed

            def close(self) -> None:
                self.closed = True

        manager = BrowserManager(60120, 1, 2, "对账报表")
        dead = Session(False, "ws://fixture/dead")
        replacement = Session(True, "ws://fixture/live")
        manager.sessions["target-1"] = dead  # type: ignore[assignment]
        manager._fetch_targets = lambda: [  # type: ignore[method-assign]
            {
                "id": "target-1",
                "type": "page",
                "url": "https://mms.pinduoduo.com/orders/list?tab=0",
                "webSocketDebuggerUrl": "ws://fixture/live",
            }
        ]
        with patch.object(order_module, "PageSession", return_value=replacement):
            manager.discover_once()

        self.assertTrue(dead.closed)
        self.assertIs(replacement, manager.sessions["target-1"])

    def test_401_refreshes_once_and_second_403_needs_human(self) -> None:
        class ApiPage:
            target_id = "target-1"

            def __init__(self, statuses: list[int]) -> None:
                self.statuses = statuses

            def browser_fetch_json(self, *args, **kwargs):
                status = self.statuses.pop(0)
                if status in {401, 403}:
                    raise ApiError("auth", status=status, path="/fixture")
                return {"success": True, "errorCode": 0, "result": {}}

        class ApiManager:
            def __init__(self, refreshed_page: ApiPage) -> None:
                self.refreshed_page = refreshed_page
                self.refresh_count = 0

            def get_dynamic_headers(self, url, target_id):
                return {"anti-content": "fixture"}

            def refresh_context(self, page):
                self.refresh_count += 1
                return self.refreshed_page

        first = ApiPage([401])
        second = ApiPage([403])
        manager = ApiManager(second)
        with self.assertRaises(NeedsHumanError):
            call_api(manager, first, "https://mms.pinduoduo.com/fixture", {}, "fixture")
        self.assertEqual(1, manager.refresh_count)

    def test_cashier_page_is_a_valid_starting_target_for_returning_home(self) -> None:
        class Session:
            target_id = "cashier-target"
            url = "https://cashier.pinduoduo.com/main/bills?tab=4001"
            ws_url = "ws://fixture/cashier"
            started_at = 0.0
            closed = False

            def is_alive(self) -> bool:
                return True

            def close(self) -> None:
                self.closed = True

        manager = BrowserManager(60120, 1, 2, "对账报表")
        manager._fetch_targets = lambda: [  # type: ignore[method-assign]
            {
                "id": "cashier-target",
                "type": "page",
                "url": Session.url,
                "webSocketDebuggerUrl": Session.ws_url,
            }
        ]
        with patch.object(order_module, "PageSession", return_value=Session()):
            manager.discover_once()

        self.assertIsNotNone(manager.find_any_pdd_page())


if __name__ == "__main__":
    unittest.main()
