from __future__ import annotations

import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]


class AutomationV2ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = (APP_ROOT / "service.py").read_text(encoding="utf-8")
        cls.runner = (APP_ROOT / "flow_runner.py").read_text(encoding="utf-8")
        cls.scheduler = (APP_ROOT / "scheduler.py").read_text(encoding="utf-8")
        cls.worker = (APP_ROOT / "worker.py").read_text(encoding="utf-8")
        cls.module = (APP_ROOT / "module.py").read_text(encoding="utf-8")
        cls.report_center = (APP_ROOT / "report_center.py").read_text(encoding="utf-8")
        cls.feishu = (PROJECT_ROOT / "apps/feishu_ai/service.py").read_text(encoding="utf-8")
        cls.authorization = (PROJECT_ROOT / "apps/identity_access/authorization.py").read_text(encoding="utf-8")
        cls.schema = (PROJECT_ROOT / "sql/common/430_automation_center_postgres.sql").read_text(encoding="utf-8")

    def test_published_flows_have_immutable_snapshot_storage(self):
        for fragment in (
            "CREATE TABLE IF NOT EXISTS ops.automation_flow_version",
            "flow_version_id UUID",
            "uq_ops_automation_flow_version",
            "INSERT INTO ops.automation_flow_version",
        ):
            self.assertIn(fragment, self.schema, fragment)
        self.assertIn("get_flow_version", self.service)
        self.assertIn('claim.get("flow_version_id")', self.runner)

    def test_flow_tasks_are_schedulable(self):
        for fragment in (
            "schedule_type VARCHAR(16)",
            "schedule_config JSONB",
            "default_profile_name VARCHAR(200)",
        ):
            self.assertIn(fragment, self.schema, fragment)
        self.assertIn("create_scheduled_flow_run", self.service)
        self.assertIn('job.get("source_kind") == "flow"', self.scheduler)

    def test_runs_use_resource_locks(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS ops.automation_resource_lock", self.schema)
        self.assertIn("resource_key VARCHAR(240)", self.schema)
        self.assertIn("automation_resource_lock", self.service)
        self.assertIn("DELETE FROM ops.automation_resource_lock", self.service)

    def test_human_gated_runs_are_resumable_in_place(self):
        for fragment in (
            "waiting_since TIMESTAMPTZ",
            "resumed_at TIMESTAMPTZ",
            "resume_count INTEGER",
            "resume_reason VARCHAR",
        ):
            self.assertIn(fragment, self.schema, fragment)
        self.assertIn("def resume_run", self.service)
        self.assertIn("def resume_answered_runs", self.service)
        self.assertIn("resume_count=resume_count+1", self.service)
        self.assertIn("resume_answered_runs", self.worker)
        self.assertIn("/resume", self.module)

    def test_flow_version_history_diff_and_rollback_are_exposed(self):
        for fragment in ("def list_flow_versions", "def rollback_flow_version", "_flow_definition_diff"):
            self.assertIn(fragment, self.service, fragment)
        self.assertIn("/versions", self.module)
        self.assertIn("/rollback", self.module)
        self.assertIn("'published'::varchar AS status", self.service)

    def test_fault_and_resource_centers_are_database_backed(self):
        self.assertIn("def fault_center", self.service)
        self.assertIn("def runtime_resources", self.service)
        self.assertIn("automation_resource_lock", self.service)
        self.assertIn("/api/automation/faults", self.authorization)
        self.assertIn("/api/automation/runtime-resources", self.authorization)

    def test_manual_inventory_refresh_is_removed(self):
        self.assertIn("def report_targets(self) -> dict:", self.report_center)
        self.assertNotIn("def report_targets(self, refresh", self.report_center)
        self.assertIn("return self.service.report_targets(), 200", self.module)
        self.assertNotIn('query.get("refresh")', self.module)

    def test_stalled_runs_can_enqueue_a_notification(self):
        self.assertIn("def enqueue_stalled_notifications", self.service)
        self.assertIn("enqueue_stalled_notifications", self.worker)
        self.assertIn('"stalled"', self.service)
        self.assertIn("长时间运行", self.feishu)

    def test_notification_outbox_keeps_feishu_credentials_out_of_worker(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS ops.automation_notification_outbox", self.schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS ops.automation_notification_policy", self.schema)
        self.assertIn("_enqueue_notification_cursor", self.service)
        self.assertIn("dispatch_automation_notifications", self.feishu)
        self.assertIn("_select_verification_relay", self.feishu)
        self.assertNotIn("open.feishu.cn", self.worker)

    def test_history_and_repair_context_prefer_run_snapshot(self):
        self.assertGreaterEqual(self.service.count("LEFT JOIN ops.automation_flow_version fv"), 4)
        self.assertIn("COALESCE(fv.version,f.version) AS flow_version", self.service)
        self.assertIn('"date_semantics": "business_date"', self.service)


if __name__ == "__main__":
    unittest.main()
