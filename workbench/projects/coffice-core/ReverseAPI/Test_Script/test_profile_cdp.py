# -*- coding: utf-8 -*-
"""Profile/CDP 自动获取解析器的纯逻辑回归测试。"""

from __future__ import annotations

import unittest

from ReverseAPI.Formal_Script.profile_cdp import (
    ProfileResolutionError,
    endpoint_from_debug_port,
    resolve_profile_connection,
    validate_endpoint,
)


PROFILE = "PDD-拼多多-养颜轻食"
PROFILE_ID = "fixture-profile-id"
ENDPOINT = "ws://127.0.0.1:45678/devtools/browser/fixture"


class FakeMcpClient:
    def __init__(self, url: str, timeout: float) -> None:
        self.url = url
        self.timeout = timeout
        self.tool_names = {
            "list_profiles",
            "list_active",
            "start_profile",
            "get_cdp_endpoint",
        }
        self.calls: list[str] = []
        self.active_calls = 0

    def initialize(self) -> None:
        self.calls.append("initialize")

    def call(self, name: str, arguments: dict[str, object]) -> object:
        self.calls.append(name)
        if name == "list_active":
            self.active_calls += 1
            if self.active_calls == 1:
                return []
            return [{"id": PROFILE_ID, "name": PROFILE, "wsEndpoint": ENDPOINT}]
        if name == "list_profiles":
            return [{"id": PROFILE_ID, "name": PROFILE}]
        if name == "start_profile":
            return {"id": PROFILE_ID}
        if name == "get_cdp_endpoint":
            return {"wsEndpoint": ENDPOINT}
        raise AssertionError(name)


class DuplicateProfileClient(FakeMcpClient):
    def call(self, name: str, arguments: dict[str, object]) -> object:
        self.calls.append(name)
        if name == "list_active":
            return []
        if name == "list_profiles":
            return [
                {"id": "one", "name": PROFILE},
                {"id": "two", "name": PROFILE},
            ]
        raise AssertionError(name)


class ActiveProfileClient(FakeMcpClient):
    def call(self, name: str, arguments: dict[str, object]) -> object:
        self.calls.append(name)
        if name == "list_active":
            return [{"id": PROFILE_ID, "name": PROFILE, "wsEndpoint": ENDPOINT}]
        raise AssertionError(name)


class ProfileCdpTests(unittest.TestCase):
    def test_explicit_endpoint_and_port_remain_supported(self) -> None:
        connection = resolve_profile_connection(
            profile_name=PROFILE,
            ws_endpoint=ENDPOINT,
        )
        self.assertEqual(connection.endpoint, ENDPOINT)
        self.assertIsNone(connection.profile_id)
        self.assertFalse(connection.started_by_this_run)
        self.assertEqual(connection.debug_port, 45678)
        self.assertEqual(endpoint_from_debug_port(52318), "http://127.0.0.1:52318")

    def test_auto_resolution_starts_unique_profile_and_waits_for_endpoint(self) -> None:
        client = FakeMcpClient("http://127.0.0.1:19610/mcp", 1.0)
        connection = resolve_profile_connection(
            profile_name=PROFILE,
            timeout=1.0,
            poll_interval=0.001,
            client_factory=lambda url, timeout: client,
        )
        self.assertEqual(connection.profile_id, PROFILE_ID)
        self.assertEqual(connection.endpoint, ENDPOINT)
        self.assertTrue(connection.started_by_this_run)
        self.assertEqual(client.calls[:3], ["initialize", "list_active", "list_profiles"])
        self.assertIn("start_profile", client.calls)

    def test_active_exact_profile_is_reused_without_starting(self) -> None:
        client = ActiveProfileClient("http://127.0.0.1:19610/mcp", 1.0)
        connection = resolve_profile_connection(
            profile_name=PROFILE,
            client_factory=lambda url, timeout: client,
        )
        self.assertEqual(connection.profile_id, PROFILE_ID)
        self.assertEqual(connection.endpoint, ENDPOINT)
        self.assertFalse(connection.started_by_this_run)
        self.assertNotIn("list_profiles", client.calls)
        self.assertNotIn("start_profile", client.calls)

    def test_duplicate_saved_profile_is_rejected(self) -> None:
        with self.assertRaises(ProfileResolutionError):
            resolve_profile_connection(
                profile_name=PROFILE,
                client_factory=lambda url, timeout: DuplicateProfileClient(url, timeout),
            )

    def test_endpoint_validation_rejects_missing_port(self) -> None:
        with self.assertRaises(ProfileResolutionError):
            validate_endpoint("ws://127.0.0.1/devtools/browser/fixture")
        with self.assertRaises(ProfileResolutionError):
            resolve_profile_connection(profile_name=PROFILE, debug_port=0)


if __name__ == "__main__":
    unittest.main()
