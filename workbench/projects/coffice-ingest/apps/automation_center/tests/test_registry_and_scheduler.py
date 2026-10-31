from __future__ import annotations

import unittest
from contextlib import contextmanager
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

from apps.automation_center.registry import business_period, refine_business_period, require_job_spec
from apps.automation_center.scheduler import AutomationScheduler
from apps.automation_center.service import AutomationService
from apps.automation_center.worker import AutomationWorker


class RegistryTests(unittest.TestCase):
    def test_registry_rejects_arbitrary_job(self):
        with self.assertRaisesRegex(ValueError, "白名单"):
            require_job_spec("arbitrary_shell")

    def test_business_period_keeps_execution_date_separate(self):
        result = business_period("jd_order_download", [], date(2026, 9, 21))
        self.assertEqual("rolling_30_days", result["period_type"])
        self.assertEqual("2026-08-23", result["business_date_start"])
        self.assertEqual("2026-09-21", result["business_date_end"])

    def test_explicit_range_wins(self):
        result = business_period(
            "pinduoduo_order_download",
            ["--start-date", "2026-08-01", "--end-date", "2026-08-31"],
            date(2026, 9, 21),
        )
        self.assertEqual("date_range", result["period_type"])
        self.assertEqual("2026-08-01", result["business_date_start"])

    def test_archive_filename_refines_actual_business_date(self):
        result = refine_business_period(
            [{"file_name": "2026-09-19_京东_测试公司_测试店_资金.xlsx"}],
            {"business_date_start": "2026-09-20", "business_date_end": "2026-09-20", "period_type": "day"},
        )
        self.assertEqual("2026-09-19", result["business_date_start"])

    def test_daily_schedule_validation_and_deduplication(self):
        self.assertEqual(
            {"times": ["05:00", "09:20"]},
            AutomationService._validate_schedule("daily", {"times": ["09:20", "05:00", "05:00"]}),
        )

    def test_full_etl_cannot_be_changed_to_a_daily_schedule(self):
        before = {
            "job_id": 1,
            "job_code": "full_etl",
            "enabled": True,
            "schedule_type": "manual",
            "schedule_config": {},
            "timezone": "Asia/Shanghai",
            "retry_policy": {"max_attempts": 1},
            "timeout_seconds": 21600,
            "description": "全量 ETL",
        }

        class Cursor:
            def __init__(self):
                self.statements = []
                self.result = None

            def execute(self, statement, _params=None):
                self.statements.append(statement)
                if statement.lstrip().startswith("SELECT"):
                    self.result = before
                else:
                    self.result = {
                        **before,
                        "schedule_type": "daily",
                        "schedule_config": {"times": ["02:00"]},
                    }

            def fetchone(self):
                return self.result

        cursor = Cursor()
        service = AutomationService.__new__(AutomationService)

        @contextmanager
        def transaction():
            yield cursor

        service.transaction = transaction
        service._audit = lambda *_args, **_kwargs: None
        with self.assertRaisesRegex(ValueError, '只允许人工'):
            service.update_job(1, {"schedule_type": "daily", "schedule_config": {"times": ["02:00"]}}, "test")
        self.assertEqual(1, len(cursor.statements))

    def test_worker_rejects_a_previously_queued_scheduled_full_refresh(self):
        worker = AutomationWorker.__new__(AutomationWorker)
        worker.service = MagicMock()
        with self.assertRaisesRegex(ValueError, '只允许人工'):
            worker._run_full_etl({'trigger_type':'schedule'})
        worker.service.start_step.assert_not_called()
        worker.service.file_ingest.create_manual_etl.assert_not_called()


class FakeSchedulerService:
    def __init__(self):
        self.calls = []

    def sync_report_journals(self):
        return 0

    def due_jobs(self, now):
        return [{"job_id": 1, "schedule_key": "job:2026-09-21:05:00", "local_date": date(2026, 9, 21)}]

    def create_scheduled_run(self, job_id, schedule_key, business_date, operator):
        self.calls.append(schedule_key)
        return ({"automation_run_id": "run-1"}, len(self.calls) == 1)




class FakeFlowSchedulerService:
    def sync_report_journals(self):
        return 0

    def __init__(self):
        self.calls = []

    def due_jobs(self, now):
        return [{
            "source_kind": "flow",
            "flow_id": "11111111-1111-1111-1111-111111111111",
            "schedule_key": "flow:11111111-1111-1111-1111-111111111111:2026-09-21:05:00",
            "local_date": date(2026, 9, 21),
        }]

    def create_scheduled_flow_run(self, flow_id, schedule_key, business_date, operator):
        self.calls.append((flow_id, schedule_key))
        return ({"automation_run_id": "flow-run-1"}, True)

class SchedulerTests(unittest.TestCase):
    def test_published_flow_is_dispatched_through_flow_scheduler_path(self):
        service = FakeFlowSchedulerService()
        scheduler = AutomationScheduler(service, clock=lambda: datetime(2026, 9, 21, 5, 1, tzinfo=timezone.utc))
        runs = scheduler.run_once()
        self.assertEqual("flow-run-1", runs[0]["automation_run_id"])
        self.assertEqual("11111111-1111-1111-1111-111111111111", service.calls[0][0])

    def test_duplicate_schedule_scan_returns_only_first_created_run(self):
        service = FakeSchedulerService()
        scheduler = AutomationScheduler(service, clock=lambda: datetime(2026, 9, 21, 5, 1, tzinfo=timezone.utc))
        self.assertEqual(1, len(scheduler.run_once()))
        self.assertEqual([], scheduler.run_once())
        self.assertEqual(["job:2026-09-21:05:00"] * 2, service.calls)


if __name__ == "__main__":
    unittest.main()
