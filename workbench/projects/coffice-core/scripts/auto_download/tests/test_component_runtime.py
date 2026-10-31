from __future__ import annotations

import asyncio
import contextlib
import io
import json
import unittest

from scripts.auto_download.playwright.component_runtime import (
    COMPONENT_EVENT_PREFIX,
    automation_component,
    classify_error,
    component_event,
)


def _events(output: str) -> list[dict]:
    result = []
    for line in output.splitlines():
        if line.startswith(COMPONENT_EVENT_PREFIX):
            result.append(json.loads(line[len(COMPONENT_EVENT_PREFIX) :]))
    return result


class ComponentRuntimeTests(unittest.TestCase):
    def test_sync_component_emits_started_and_success(self) -> None:
        @automation_component("test.component.sync", "同步测试", category="test")
        def sample(value: int) -> int:
            component_event("observation", "处理中")
            return value + 1

        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(2, sample(1))

        events = _events(stream.getvalue())
        self.assertEqual(
            ["component_started", "component_event", "component_succeeded"],
            [item["event"] for item in events],
        )
        self.assertEqual("test.component.sync", events[0]["component_code"])
        self.assertEqual(events[0]["component_run_key"], events[-1]["component_run_key"])

    def test_nested_component_started_event_contains_parent_key(self) -> None:
        @automation_component("test.component.child", "子组件", category="test")
        def child() -> None:
            return None

        @automation_component("test.component.parent", "父组件", category="test")
        def parent() -> None:
            child()

        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            parent()

        events = _events(stream.getvalue())
        parent_started = next(
            item for item in events
            if item["event"] == "component_started"
            and item["component_code"] == "test.component.parent"
        )
        child_started = next(
            item for item in events
            if item["event"] == "component_started"
            and item["component_code"] == "test.component.child"
        )
        self.assertEqual(
            parent_started["component_run_key"],
            child_started["parent_component_run_key"],
        )

    def test_async_component_redacts_secret_in_failure(self) -> None:
        @automation_component("test.component.async", "异步测试", category="test")
        async def sample() -> None:
            raise RuntimeError("password=super-secret token=abc123")

        stream = io.StringIO()
        with self.assertRaises(RuntimeError), contextlib.redirect_stdout(stream):
            asyncio.run(sample())

        events = _events(stream.getvalue())
        failed = events[-1]
        self.assertEqual("component_failed", failed["event"])
        self.assertNotIn("super-secret", failed["error_message"])
        self.assertNotIn("abc123", failed["error_message"])
        self.assertIn("<redacted>", failed["error_message"])

    def test_error_classifier_uses_stable_categories(self) -> None:
        self.assertEqual("TIMEOUT", classify_error(TimeoutError("slow")))
        self.assertEqual("SELECTOR_NOT_FOUND", classify_error(RuntimeError("未找到下载按钮")))
        self.assertEqual("LOGIN_EXPIRED", classify_error(RuntimeError("登录已失效")))


if __name__ == "__main__":
    unittest.main()
