from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

from apps.automation_center.checkpoint import restore_legacy_checkpoint
from apps.automation_center.flow_runner import FlowRunner
from apps.automation_center.service import AutomationService
from apps.automation_center.worker import AutomationWorker


class ResumeContractTests(unittest.TestCase):
    @staticmethod
    def fake_service(cursor):
        service = object.__new__(AutomationService)

        @contextmanager
        def transaction():
            yield cursor

        service.transaction = transaction
        service._audit = Mock()
        return service

    def test_failed_run_reopens_same_id_without_retry_run(self):
        cursor = Mock()
        cursor.fetchone.side_effect = [
            {"automation_run_id": "run-1", "status": "failed"},
            {"automation_run_id": "run-1", "status": "queued", "resume_count": 1},
        ]
        service = self.fake_service(cursor)
        result = service.resume_run("run-1", "tester", reason="manual_repair")
        self.assertEqual("run-1", result["automation_run_id"])
        self.assertEqual("queued", result["status"])
        self.assertEqual(1, result["resume_count"])
        self.assertTrue(any("resume_count=resume_count+1" in args[0]
                            for args, _ in cursor.execute.call_args_list))
        service._audit.assert_called_once()

    def test_cancelled_run_cannot_be_reopened_implicitly(self):
        cursor = Mock()
        cursor.fetchone.return_value = {"automation_run_id": "run-1", "status": "cancelled"}
        service = self.fake_service(cursor)
        with self.assertRaisesRegex(ValueError, "等待人工或失败"):
            service.resume_run("run-1", "tester")

    def test_acknowledgement_retains_failed_outcome(self):
        cursor = Mock()
        cursor.fetchone.side_effect = [
            {"automation_run_id": "run-1", "status": "failed"},
            {"automation_run_id": "run-1", "status": "failed", "attention_acknowledged_by": "tester"},
        ]
        service = self.fake_service(cursor)
        result = service.acknowledge_run("run-1", "tester", "已在新 Run 重做")
        self.assertEqual("failed", result["status"])
        self.assertTrue(any("attention_acknowledged_at=NOW()" in args[0]
                            for args, _ in cursor.execute.call_args_list))
        service._audit.assert_called_once()

    def test_checkpoint_never_persists_human_answer_or_cdp_endpoint(self):
        runner = object.__new__(FlowRunner)
        runner.runtime = {
            "cdp_url": "ws://secret-session",
            "_archive_password": "secret-pass",
            "pending_artifact": {"source_path": Path("/tmp/report.csv"), "password": "another-secret"},
        }
        state = runner._runtime_checkpoint()
        text = repr(state)
        self.assertNotIn("secret-pass", text)
        self.assertNotIn("ws://", text)
        self.assertNotIn("another-secret", text)
        self.assertIn("source_path", state["pending_artifact"])

    def test_flow_only_skips_verified_existing_artifacts(self):
        runner = object.__new__(FlowRunner)
        runner.runtime = {}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.csv"
            path.write_text("date,amount\\n2026-09-28,20", encoding="utf-8")
            checkpoint = {
                "component_code": "report.archive",
                "output_snapshot": {"runtime": {"pending_artifact": {"source_path": str(path)}}},
            }
            self.assertTrue(runner._checkpoint_can_skip({"component_code": "report.archive"}, checkpoint))
            self.assertEqual(path, runner.runtime["pending_artifact"]["source_path"])
            path.unlink()
            self.assertFalse(runner._checkpoint_can_skip({"component_code": "report.archive"}, checkpoint))

    def test_legacy_checkpoint_migration_imports_only_same_run_successes(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy = Path(directory) / "checkpoint_2026-09-28.json"
            dest = Path(directory) / "run-specific.json"
            legacy.write_text(json.dumps({
                "schema_version": 1, "scope": "2026-09-28",
                "config_fingerprint": "old", "profiles": {
                    "shop-a": {"steps": {
                        "key-a": {"name": "订单", "module": "order_script", "status": "success"},
                        "key-b": {"name": "财务", "module": "finance_script", "status": "success"},
                    }},
                    "shop-b": {"steps": {
                        "key-c": {"name": "订单", "module": "order_script", "status": "success"},
                    }},
                },
            }), encoding="utf-8")
            restored = restore_legacy_checkpoint(
                legacy, dest, scope="2026-09-28",
                successful_steps=[("shop-a", "order_script", "订单")],
            )
            self.assertEqual(1, restored)
            migrated = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(["shop-a"], list(migrated["profiles"]))
            self.assertEqual(["key-a"], list(migrated["profiles"]["shop-a"]["steps"]))
            self.assertEqual(0, restore_legacy_checkpoint(
                legacy, dest, scope="2026-09-28",
                successful_steps=[("shop-a", "finance_script", "财务")],
            ))

    def test_download_worker_scopes_checkpoint_to_run_and_classifies_human(self):
        source = inspect.getsource(AutomationWorker._run_download)
        self.assertIn("automation_run_{run_id}.json", source)
        self.assertIn("run_has_unanswered_human", source)
        self.assertIn("DISTINCT ON", source)

    def test_new_attempt_clock_does_not_reuse_original_claim_time(self):
        claim = inspect.getsource(AutomationService.claim_run)
        manual = inspect.getsource(AutomationService.resume_run)
        automatic = inspect.getsource(AutomationService.resume_answered_runs)
        dashboard = inspect.getsource(AutomationService.dashboard)
        recovery = inspect.getsource(AutomationService.recover_stale)
        self.assertIn("attempt_started_at=NOW()", claim)
        self.assertIn("attempt_started_at=NULL", manual)
        self.assertIn("attempt_started_at=NULL", automatic)
        self.assertIn("COALESCE(r.attempt_started_at,r.started_at)", dashboard)
        self.assertIn("COALESCE(heartbeat_at,attempt_started_at,started_at,queued_at)", recovery)

    def test_flow_preserves_failed_tab_and_reattaches_on_resume(self):
        run = inspect.getsource(FlowRunner._run_async)
        login = inspect.getsource(FlowRunner._handle_jd_login)
        self.assertIn('final_status not in {"failed", "needs_human"}', run)
        self.assertIn('self.claim.get("resume_count")', login)
        self.assertIn("reversed(context.pages)", login)
        self.assertIn("candidate.url.startswith(JD_PREFIX)", login)
        self.assertIn("new_authenticated_page(context)", login)

    def test_paused_browser_run_keeps_resource_but_releases_worker(self):
        cursor = Mock()
        cursor.fetchone.return_value = {
            "automation_run_id": "run-1", "execution_lane": "interactive",
            "trigger_type": "manual", "parent_run_id": None,
        }
        service = self.fake_service(cursor)
        service._enqueue_notification_cursor = Mock()
        service.finish_run("run-1", "needs_human", error="等待新验证码")
        sql = [args[0] for args, _ in cursor.execute.call_args_list]
        self.assertTrue(any("worker_id=NULL" in query for query in sql))
        self.assertTrue(any("lock_state='paused'" in query for query in sql))
        self.assertFalse(any("DELETE FROM ops.automation_resource_lock" in query for query in sql))

    def test_success_after_resume_releases_resource_reservation(self):
        cursor = Mock()
        cursor.fetchone.return_value = {
            "automation_run_id": "run-1", "execution_lane": "interactive",
            "trigger_type": "manual", "parent_run_id": None,
        }
        service = self.fake_service(cursor)
        service._enqueue_notification_cursor = Mock()
        service.finish_run("run-1", "success")
        sql = [args[0] for args, _ in cursor.execute.call_args_list]
        self.assertTrue(any("DELETE FROM ops.automation_resource_lock" in query for query in sql))

    def test_claim_and_recovery_preserve_only_owner_paused_lock(self):
        claim = inspect.getsource(AutomationService.claim_run)
        retry = inspect.getsource(AutomationService.retry_run)
        recovery = inspect.getsource(AutomationService.recover_stale)
        resources = inspect.getsource(AutomationService.runtime_resources)
        self.assertIn("l.automation_run_id=r.automation_run_id AND l.lock_state='paused'", claim)
        self.assertIn("lock_state='running',acquired_at=NOW()", claim)
        self.assertIn("AND lock_state='paused'", retry)
        self.assertIn("r.status IN ('needs_human','failed','queued')", recovery)
        self.assertIn("l.lock_state='paused'", resources)

    def test_auto_resume_matches_only_latest_unanswered_challenge(self):
        source = inspect.getsource(AutomationService.resume_answered_runs)
        self.assertIn("MAX(s2.sequence_no)", source)
        self.assertIn("e.event_type='human_answered'", source)
        self.assertIn("vc.challenge_uuid=COALESCE(", source)


if __name__ == "__main__":
    unittest.main()
