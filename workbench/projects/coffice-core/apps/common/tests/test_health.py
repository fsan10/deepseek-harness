from __future__ import annotations

import unittest

from apps.common.health import HealthAggregator


class _Service:
    def __init__(self, result):
        self.result = result

    def health(self):
        return dict(self.result)


class _Module:
    pass


class HealthAggregatorTests(unittest.TestCase):
    def build(self, *, worker_count=1, target_ready=True, refresh_failed=False):
        database = _Service({"ods_ready": True, "dwd_ready": True, "operation_ready": True})
        influencer = _Module()
        influencer.database = _Service({
            "assignment_ready": True,
            "target_ready": target_ready,
            "ads_ready": True,
            "metrics_refresh": {
                "status": "failed" if refresh_failed else "succeeded",
                "last_error": "RuntimeError: refresh boom" if refresh_failed else None,
            },
        })
        influencer.product_categories = _Service({
            "product_category_ready": True, "product_ready": True, "product_mapping_ready": True,
        })
        ingest = _Module()
        ingest.service = _Service({
            "ingest_ready": True, "etl_ready": True, "fee_mapping_ready": True,
            "worker_heartbeat_ready": True, "active_worker_count": worker_count,
            "worker_last_seen_at": "2026-08-08T12:00:00+08:00",
        })
        proxy = _Service({"proxy_ready": True, "proxy_port": 8101})
        return HealthAggregator(
            database, influencer, ingest, proxy,
            application_version="test", features=["unified_health"], cache_seconds=0,
        )

    def test_ready_snapshot_has_stable_module_shape_and_flat_compatibility(self):
        result = self.build().snapshot()
        self.assertTrue(result["ready"])
        self.assertEqual(set(result["modules"]), {"bank", "influencer", "ingest", "worker", "dashboard", "automation"})
        self.assertTrue(result["ods_ready"])
        self.assertEqual(result["active_worker_count"], 1)

    def test_failures_prioritize_migration_before_worker(self):
        result = self.build(worker_count=0, target_ready=False).snapshot()
        self.assertFalse(result["ready"])
        self.assertEqual(result["failed"][0]["kind"], "migration")
        self.assertEqual(result["failed"][-1]["kind"], "worker")
        legacy = self.build(worker_count=0).legacy_ingest()
        self.assertTrue(legacy["deprecated"])
        self.assertEqual(legacy["replacement"], "/api/health")

    def test_background_refresh_failure_is_visible_in_health(self):
        result = self.build(refresh_failed=True).snapshot()
        self.assertFalse(result["ready"])
        failure = next(item for item in result["failed"] if item["code"] == "influencer.metrics_refresh.failed")
        self.assertEqual(failure["kind"], "service")
        self.assertIn("refresh boom", failure["detail"])


if __name__ == "__main__":
    unittest.main()
