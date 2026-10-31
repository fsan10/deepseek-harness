from __future__ import annotations

import argparse
import unittest
from unittest.mock import Mock

from apps.automation_center.module import AutomationCenterModule
from apps.identity_access.authorization import AuthorizationError, required_permission


class Context:
    def __init__(self, *permissions):
        self.permissions = set(permissions)

    def can(self, permission):
        return permission in self.permissions


class ModulePermissionTests(unittest.TestCase):
    def setUp(self):
        args = argparse.Namespace(host="localhost", pg_port=5432, dbname="db", user="u", password=None)
        self.module = AutomationCenterModule(args)
        self.module.service = Mock()

    def test_verification_routes_are_not_claimed(self):
        self.assertIsNone(self.module.dispatch("GET", "/api/automation/verification/challenges/id"))

    def test_view_permission_can_read_jobs(self):
        self.module.service.list_jobs.return_value = {"items": []}
        result, status = self.module.dispatch("GET", "/api/automation/jobs", context=Context("automation.jobs.view"))
        self.assertEqual(200, status)
        self.assertEqual([], result["items"])

    def test_view_only_cannot_execute_retry_or_manage(self):
        context = Context("automation.jobs.view", "automation.runs.view", "automation.results.view")
        with self.assertRaises(AuthorizationError):
            self.module.dispatch("POST", "/api/automation/jobs/1/run", payload={}, context=context)
        with self.assertRaises(AuthorizationError):
            self.module.dispatch("POST", "/api/automation/runs/00000000-0000-0000-0000-000000000001/retry", payload={}, context=context)
        with self.assertRaises(AuthorizationError):
            self.module.dispatch("PUT", "/api/automation/jobs/1", payload={}, context=context)

    def test_central_permissions_cover_mutating_routes(self):
        self.assertEqual("automation.runs.execute", required_permission("POST", "/api/automation/jobs/1/run"))
        self.assertEqual("automation.runs.retry", required_permission("POST", "/api/automation/runs/00000000-0000-0000-0000-000000000001/retry"))
        self.assertEqual("automation.jobs.manage", required_permission("PUT", "/api/automation/jobs/1"))
        self.assertIsNone(required_permission("POST", "/api/automation/verification/challenges"))

    def test_jobs_runs_results_and_health_api_contracts(self):
        context = Context(
            "automation.workbench.view", "automation.jobs.view",
            "automation.runs.view", "automation.results.view",
        )
        self.module.service.list_jobs.return_value = {"items": [], "total": 0}
        self.module.service.list_runs.return_value = {"items": [], "total": 0}
        self.module.service.daily_results.return_value = {"items": [], "total": 0}
        self.module.service.health.return_value = {"database_ready": True}
        cases = [
            ("/api/automation/jobs", "list_jobs"),
            ("/api/automation/runs", "list_runs"),
            ("/api/automation/daily-results", "daily_results"),
            ("/api/automation/health", "health"),
        ]
        for path, method_name in cases:
            with self.subTest(path=path):
                _, status = self.module.dispatch("GET", path, context=context)
                self.assertEqual(200, status)
                getattr(self.module.service, method_name).assert_called()


if __name__ == "__main__":
    unittest.main()
