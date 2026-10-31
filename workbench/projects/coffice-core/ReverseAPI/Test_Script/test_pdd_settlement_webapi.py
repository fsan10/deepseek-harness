# -*- coding: utf-8 -*-
"""拼多多结算单 WebAPI 的 Target、自恢复和零数据契约测试。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from ReverseAPI.Formal_Script import pdd_settlement_webapi_download as settlement
from ReverseAPI.Formal_Script.pdd_webapi_common import ApiError


class PddSettlementWebApiTests(unittest.TestCase):
    def test_result_count_requires_authoritative_shape(self) -> None:
        self.assertEqual(0, settlement.result_count({"total": 0, "billList": []}))
        self.assertEqual(2, settlement.result_count({"billList": [{}, {}]}))
        with self.assertRaises(ApiError):
            settlement.result_count({"unexpected": []})

    def test_existing_target_with_dead_listener_is_reconnected(self) -> None:
        class Session:
            def __init__(self, alive: bool, websocket_url: str) -> None:
                self.target_id = "target-1"
                self.url = "https://cashier.pinduoduo.com/main/bills?tab=4001"
                self.websocket_url = websocket_url
                self.started_at = 0.0
                self._alive = alive
                self.closed = False

            def is_alive(self) -> bool:
                return self._alive and not self.closed

            def close(self) -> None:
                self.closed = True

        manager = settlement.BrowserManager(60120)
        dead = Session(False, "ws://fixture/dead")
        replacement = Session(True, "ws://fixture/live")
        manager.sessions["target-1"] = dead  # type: ignore[assignment]
        manager._fetch_targets = lambda: [  # type: ignore[method-assign]
            {
                "id": "target-1",
                "type": "page",
                "url": "https://cashier.pinduoduo.com/main/bills?tab=4001",
                "webSocketDebuggerUrl": "ws://fixture/live",
            }
        ]
        with patch.object(settlement, "PageSession", return_value=replacement):
            manager.discover_once()

        self.assertTrue(dead.closed)
        self.assertIs(replacement, manager.sessions["target-1"])

    def test_discovery_loop_survives_one_iteration_error(self) -> None:
        manager = settlement.BrowserManager(60120)
        calls = 0

        def discover() -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("fixture")
            manager.stop_event.set()

        manager.discover_once = discover  # type: ignore[method-assign]
        manager._discovery_loop()
        self.assertEqual(2, calls)

    def test_bills_page_must_come_from_current_home_menu_click(self) -> None:
        class Page:
            def __init__(self, target_id: str, url: str) -> None:
                self.target_id = target_id
                self.url = url
                self.clicked = False
                self.front = False

            def click_reconciliation_center(self) -> bool:
                self.clicked = True
                return True

            def bring_to_front(self) -> None:
                self.front = True

        home = Page("home", "https://mms.pinduoduo.com/home")
        old_bills = Page("old", "https://cashier.pinduoduo.com/main/bills?tab=4001")
        new_bills = Page("new", "https://cashier.pinduoduo.com/main/bills?tab=4001")

        class Manager:
            def find_home_page(self):
                return home

            def list_sessions(self):
                pages = [home, old_bills]
                if home.clicked:
                    pages.append(new_bills)
                return pages

            def clear_context(self, target_id):
                self.cleared = target_id

            def find_bills_page(self, target_ids):
                if "new" in target_ids:
                    return new_bills
                if "old" in target_ids:
                    return old_bills
                return None

        manager = Manager()
        selected = settlement.ensure_bills_page(manager)  # type: ignore[arg-type]
        self.assertIs(new_bills, selected)
        self.assertTrue(home.clicked)
        self.assertTrue(new_bills.front)


if __name__ == "__main__":
    unittest.main()
