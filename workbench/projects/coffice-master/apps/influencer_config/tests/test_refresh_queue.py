from __future__ import annotations

import threading
import unittest

from apps.influencer_config.refresh_queue import CoalescingRefreshWorker


class CoalescingRefreshWorkerTests(unittest.TestCase):
    def test_burst_requests_are_coalesced_and_observable(self):
        release = threading.Event()
        started = threading.Event()
        calls = []

        def runner():
            calls.append(1)
            started.set()
            release.wait(2)
            return {"ok": True}

        worker = CoalescingRefreshWorker("test", runner, debounce_seconds=0.05)
        try:
            first = worker.request("first")
            worker.request("second")
            worker.request("third")
            self.assertEqual(first["requested_revision"], 1)
            self.assertTrue(started.wait(1))
            release.set()
            self.assertTrue(worker.wait_until_idle(2))
            status = worker.status()
            self.assertEqual(len(calls), 1)
            self.assertEqual(status["status"], "succeeded")
            self.assertEqual(status["requested_revision"], 3)
            self.assertEqual(status["completed_revision"], 3)
            self.assertEqual(status["last_result"], {"ok": True})
        finally:
            release.set()
            worker.close()

    def test_request_during_refresh_schedules_one_follow_up(self):
        first_started = threading.Event()
        first_release = threading.Event()
        calls = []

        def runner():
            calls.append(1)
            if len(calls) == 1:
                first_started.set()
                first_release.wait(2)

        worker = CoalescingRefreshWorker("test", runner, debounce_seconds=0)
        try:
            worker.request("first")
            self.assertTrue(first_started.wait(1))
            worker.request("during-first")
            first_release.set()
            self.assertTrue(worker.wait_until_idle(2))
            self.assertEqual(len(calls), 2)
            self.assertEqual(worker.status()["completed_revision"], 2)
        finally:
            first_release.set()
            worker.close()

    def test_failure_is_retained_without_silent_retry_loop(self):
        def runner():
            raise RuntimeError("refresh boom")

        worker = CoalescingRefreshWorker("test", runner, debounce_seconds=0)
        try:
            worker.request("failure")
            self.assertTrue(worker.wait_until_idle(2))
            status = worker.status()
            self.assertEqual(status["status"], "failed")
            self.assertIn("refresh boom", status["last_error"])
            self.assertEqual(status["completed_revision"], 0)
        finally:
            worker.close()

    def test_durable_pending_work_is_discovered_without_an_in_memory_request(self):
        pending = threading.Event()
        finished = threading.Event()

        def runner():
            pending.clear()
            finished.set()

        worker = CoalescingRefreshWorker('recovery', runner, debounce_seconds=0,
            pending_check=pending.is_set, poll_seconds=0.05)
        try:
            pending.set()
            self.assertTrue(finished.wait(2))
            self.assertTrue(worker.wait_until_idle(2))
            self.assertEqual(worker.status()['status'], 'succeeded')
        finally:
            worker.close()


if __name__ == "__main__":
    unittest.main()
