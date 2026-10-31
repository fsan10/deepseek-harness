from __future__ import annotations

import inspect
import unittest
from datetime import date
from unittest.mock import Mock, patch

from apps.automation_center.service import AutomationService
from apps.automation_center.worker import AutomationWorker
from scripts.auto_download.run_all_platform_downloads import DownloadStepError


class WorkerService:
    def __init__(self, claim):
        self.claim = claim
        self.finished = []

    def resume_answered_runs(self, **kwargs):
        return []

    def sync_report_journals(self):
        return 0

    def claim_run(self, worker_id):
        result, self.claim = self.claim, None
        return result

    def finish_run(self, run_id, status, **kwargs):
        self.finished.append((run_id, status, kwargs))

    def heartbeat_run(self, run_id, worker_id):
        return False

    def run_has_unanswered_human(self, run_id):
        return getattr(self, "human_waiting", False)


class WorkerContractTests(unittest.TestCase):
    def worker(self, service):
        worker = object.__new__(AutomationWorker)
        worker.service = service
        worker.worker_id = "worker-1"
        worker.worker_name = "test"
        worker._heartbeat = Mock()
        return worker

    def test_scheduled_sunday_runs_without_calendar_dependency(self):
        for job_code, method in (("platform_download_overnight", "_run_download"),
                                 ("flow_overnight", "_run_flow")):
            with self.subTest(job_code=job_code):
                claim = {"automation_run_id": "sunday-run", "trigger_type": "schedule",
                         "business_date": date(2026, 10, 18),
                         "job": {"job_code": job_code, "schedule_config": {"workdays_only": True}}}
                service = WorkerService(claim)
                worker = self.worker(service)
                executor = Mock()
                setattr(worker, method, executor)
                with patch.dict("sys.modules", {"chinese_calendar": None}):
                    worker._execute_claimed(claim)
                executor.assert_called_once_with(claim)
                self.assertEqual([], service.finished)

    def test_success_path_leaves_executor_to_finalize(self):
        service = WorkerService({"automation_run_id": "run-1"})
        worker = self.worker(service)
        worker._execute_claimed = Mock()
        self.assertTrue(worker.run_once())
        self.assertEqual([], service.finished)

    def test_failure_is_persisted(self):
        service = WorkerService({"automation_run_id": "run-1"})
        worker = self.worker(service)
        worker._execute_claimed = Mock(side_effect=RuntimeError("boom"))
        worker.run_once()
        self.assertEqual("failed", service.finished[0][1])

    def test_needs_human_exit_code_is_not_failed(self):
        service = WorkerService({"automation_run_id": "run-1"})
        worker = self.worker(service)
        worker._execute_claimed = Mock(side_effect=DownloadStepError("verification", return_code=2, result={}))
        worker.run_once()
        self.assertEqual("needs_human", service.finished[0][1])

    def test_verification_child_exit_one_is_paused_when_human_waits(self):
        service = WorkerService({"automation_run_id": "run-1"})
        service.human_waiting = True
        worker = self.worker(service)
        worker._execute_claimed = Mock(side_effect=DownloadStepError("验证码等待超时", return_code=1, result={}))
        worker.run_once()
        self.assertEqual("needs_human", service.finished[0][1])

    def test_child_exit_one_without_human_wait_is_failed(self):
        service = WorkerService({"automation_run_id": "run-1"})
        worker = self.worker(service)
        worker._execute_claimed = Mock(side_effect=DownloadStepError("任务报错", return_code=1, result={}))
        worker.run_once()
        self.assertEqual("failed", service.finished[0][1])

    def test_claim_and_stale_recovery_are_database_driven(self):
        claim_source = inspect.getsource(AutomationService.claim_run)
        recovery_source = inspect.getsource(AutomationService.recover_stale)
        self.assertIn("FOR UPDATE SKIP LOCKED", claim_source)
        self.assertIn("automation_resource_lock", claim_source)
        self.assertIn("resource_key", claim_source)
        self.assertIn("heartbeat_at", recovery_source)
        self.assertIn("automation_resource_lock", recovery_source)

    def test_worker_checks_answered_challenges_before_claiming(self):
        source = inspect.getsource(AutomationWorker.run_once)
        self.assertIn("resume_answered_runs", source)
        self.assertLess(source.index("resume_answered_runs"), source.index("claim_run"))


if __name__ == "__main__":
    unittest.main()
