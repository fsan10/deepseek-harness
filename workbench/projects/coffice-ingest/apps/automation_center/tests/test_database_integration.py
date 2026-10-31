from __future__ import annotations

import argparse
import os
import unittest
import uuid
from datetime import date

from apps.automation_center.service import AutomationService
from apps.fund_split_adjust.server import load_project_env


@unittest.skipUnless(os.getenv("RUN_AUTOMATION_DB_TESTS") == "1", "set RUN_AUTOMATION_DB_TESTS=1")
class AutomationDatabaseIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_project_env()
        args = argparse.Namespace(
            host=os.getenv("PGHOST", "192.168.77.111"),
            pg_port=int(os.getenv("PGPORT", "5432")),
            dbname=os.getenv("PGDATABASE", "mock_coffice"),
            user=os.getenv("PGUSER", "postgres"),
            password=os.getenv("PGPASSWORD"),
        )
        cls.service = AutomationService(args)
        cls.run_ids: list[str] = []
        with cls.service.transaction() as cursor:
            cursor.execute("SELECT job_id FROM ops.automation_job WHERE job_code='platform_download_overnight'")
            cls.job_id = int(cursor.fetchone()["job_id"])

    @classmethod
    def tearDownClass(cls):
        if not cls.run_ids:
            return
        with cls.service.transaction() as cursor:
            cursor.execute("DELETE FROM ops.operation_log WHERE target_type='automation_run' AND target_key=ANY(%s)", (cls.run_ids,))
            cursor.execute("DELETE FROM ops.automation_run WHERE automation_run_id=ANY(%s::uuid[])", (cls.run_ids,))

    @classmethod
    def remember(cls, run):
        run_id = str(run["automation_run_id"])
        cls.run_ids.append(run_id)
        return run_id

    def test_schedule_idempotency_statuses_retry_and_stale_recovery(self):
        key = f"integration:{uuid.uuid4()}"
        first, created = self.service.create_scheduled_run(self.job_id, key, date.today(), "integration-test")
        first_id = self.remember(first)
        second, duplicate_created = self.service.create_scheduled_run(self.job_id, key, date.today(), "integration-test")
        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(first_id, str(second["automation_run_id"]))

        cancelled = self.service.cancel_run(first_id, "integration-test")
        self.assertEqual("cancelled", cancelled["status"])
        retried = self.service.retry_run(first_id, "integration-test")
        retry_id = self.remember(retried)
        self.service.cancel_run(retry_id, "integration-test")

        no_data = self.service.create_run(self.job_id, trigger_type="manual", operator="integration-test")
        no_data_id = self.remember(no_data)
        step_id = self.service.start_step(no_data_id, {
            "metadata": {"platform": "不存在的平台", "company": "测试公司", "shop": "测试店铺"},
            "profile_name": "test-profile", "step_name": "空结果", "module_name": "test_module",
            "execution_lane": "overnight",
            "business_period": {"business_date_start": date.today().isoformat(), "business_date_end": date.today().isoformat(), "period_type": "day"},
        })
        self.service.finish_step(step_id, "no_data", {"exit_code": 0})
        self.service.finish_run(no_data_id, "no_data")
        self.assertEqual("no_data", self.service.get_run(no_data_id)["status"])

        needs_human = self.service.create_run(self.job_id, trigger_type="manual", operator="integration-test")
        needs_human_id = self.remember(needs_human)
        human_step = self.service.start_step(needs_human_id, {
            "metadata": {"platform": "不存在的平台", "company": "测试公司", "shop": "测试店铺"},
            "profile_name": "test-profile", "step_name": "登录验证", "module_name": "test_module",
            "execution_lane": "overnight", "business_period": {"period_type": "unknown"},
        })
        self.service.finish_step(human_step, "needs_human", {"exit_code": 2, "error_message": "等待人工处理"})
        self.service.finish_run(needs_human_id, "needs_human")
        self.assertEqual("needs_human", self.service.get_run(needs_human_id)["steps"][0]["status"])

        stale = self.service.create_run(self.job_id, trigger_type="manual", operator="integration-test")
        stale_id = self.remember(stale)
        with self.service.transaction() as cursor:
            cursor.execute("UPDATE ops.automation_run SET status='running',started_at=NOW()-INTERVAL '2 hours',heartbeat_at=NOW()-INTERVAL '2 hours' WHERE automation_run_id=%s", (stale_id,))
        recovered = self.service.recover_stale(15)
        self.assertGreaterEqual(recovered["runs"], 1)
        self.assertEqual("failed", self.service.get_run(stale_id)["status"])


if __name__ == "__main__":
    unittest.main()
