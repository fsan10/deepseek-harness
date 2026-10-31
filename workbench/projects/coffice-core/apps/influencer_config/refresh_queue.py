"""Small, observable background queue for coalescing metric refresh requests."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any


LOGGER = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CoalescingRefreshWorker:
    """Run one refresh at a time and merge bursts into the smallest safe number of runs."""

    def __init__(self, task_name: str, runner: Callable[[], Any], *, debounce_seconds: float = 0.2,
                 pending_check: Callable[[], bool] | None = None, poll_seconds: float = 5.0):
        self.task_name = task_name
        self.runner = runner
        self.debounce_seconds = max(0.0, float(debounce_seconds))
        self.pending_check = pending_check
        self.poll_seconds = max(0.05, poll_seconds)
        self._next_recovery_check = 0.0
        self._condition = threading.Condition()
        self._requested_revision = 0
        self._completed_revision = 0
        self._pending = False
        self._running = False
        self._stopping = False
        self._drain_on_stop = True
        self._status = "idle"
        self._last_reason = ""
        self._last_error = ""
        self._last_result: Any = None
        self._requested_at: str | None = None
        self._started_at: str | None = None
        self._finished_at: str | None = None
        self._duration_seconds: float | None = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"{task_name}-refresh-worker",
            daemon=True,
        )
        self._thread.start()

    def request(self, reason: str) -> dict:
        with self._condition:
            if self._stopping:
                raise RuntimeError(f"{self.task_name}刷新队列正在关闭")
            self._requested_revision += 1
            self._pending = True
            self._last_reason = str(reason or "configuration_changed")[:200]
            self._requested_at = _utc_now()
            if not self._running:
                self._status = "queued"
            self._condition.notify_all()
            return self._snapshot_unlocked()

    def status(self) -> dict:
        with self._condition:
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self) -> dict:
        return {
            "task_name": self.task_name,
            "status": self._status,
            "requested_revision": self._requested_revision,
            "completed_revision": self._completed_revision,
            "pending": self._pending,
            "running": self._running,
            "last_reason": self._last_reason,
            "last_error": self._last_error or None,
            "last_result": self._last_result,
            "requested_at": self._requested_at,
            "started_at": self._started_at,
            "finished_at": self._finished_at,
            "duration_seconds": self._duration_seconds,
        }

    def wait_until_idle(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while self._pending or self._running:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def close(self, *, drain: bool = True, timeout: float = 30.0) -> bool:
        with self._condition:
            self._stopping = True
            self._drain_on_stop = bool(drain)
            if not drain:
                self._pending = False
            self._condition.notify_all()
        self._thread.join(max(0.0, timeout))
        return not self._thread.is_alive()

    def _run(self) -> None:
        while True:
            # Durable recovery runs outside the condition lock so status/close
            # calls remain responsive even if the database is unavailable.
            if self.pending_check and time.monotonic() >= self._next_recovery_check:
                try:
                    if self.pending_check():
                        with self._condition:
                            if not self._pending and not self._stopping:
                                self._requested_revision += 1
                                self._pending = True
                except Exception:
                    LOGGER.warning("%s pending refresh check failed", self.task_name, exc_info=True)
                self._next_recovery_check = time.monotonic() + self.poll_seconds
            with self._condition:
                while not self._pending and not self._stopping:
                    self._condition.wait(self.poll_seconds if self.pending_check else None)
                    if self.pending_check:
                        break
                if self._stopping and (not self._drain_on_stop or not self._pending):
                    self._status = "stopped"
                    self._condition.notify_all()
                    return
                if not self._pending:
                    continue
                observed_revision = self._requested_revision
                if self.debounce_seconds:
                    self._condition.wait(self.debounce_seconds)
                    observed_revision = self._requested_revision
                self._pending = False
                self._running = True
                self._status = "running"
                self._started_at = _utc_now()
                self._last_error = ""
                started = time.monotonic()
            try:
                result = self.runner()
            except Exception as exc:  # background failures must remain observable
                LOGGER.exception("%s background refresh failed", self.task_name)
                with self._condition:
                    self._running = False
                    self._status = "queued" if self._pending else "failed"
                    self._last_error = f"{type(exc).__name__}: {exc}"[:1000]
                    self._finished_at = _utc_now()
                    self._duration_seconds = round(time.monotonic() - started, 3)
                    self._condition.notify_all()
                self._next_recovery_check = time.monotonic() + max(30.0, self.poll_seconds)
            else:
                with self._condition:
                    self._running = False
                    self._completed_revision = max(self._completed_revision, observed_revision)
                    self._status = "queued" if self._pending else "succeeded"
                    self._last_result = result
                    self._finished_at = _utc_now()
                    self._duration_seconds = round(time.monotonic() - started, 3)
                    self._condition.notify_all()

