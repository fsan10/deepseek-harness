# -*- coding: utf-8 -*-
"""Cloak CDP 参数解析的无网络回归测试。"""

from __future__ import annotations

import unittest

from ReverseAPI.Formal_Script.profile_cdp import (
    endpoint_from_debug_port,
    validate_endpoint,
)


class CloakPddTests(unittest.TestCase):
    def test_fixture_endpoint_is_valid_without_connecting_browser(self) -> None:
        endpoint = "ws://127.0.0.1:45678/devtools/browser/fixture"
        self.assertEqual(endpoint, validate_endpoint(endpoint))

    def test_debug_port_keeps_legacy_http_compatibility(self) -> None:
        self.assertEqual(
            "http://127.0.0.1:45678",
            endpoint_from_debug_port(45678),
        )


if __name__ == "__main__":
    unittest.main()
