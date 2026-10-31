from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from automation.collection_accounts import batch_configure, initialize_accounts
from automation.collection_events import link_run, record, recover_auth, recover_run
from automation.review_errors import ContractError


class CollectionEventsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = sqlite3.connect(Path(self.directory.name) / "events.sqlite")
        self.db.row_factory = sqlite3.Row
        initialize_accounts(self.db)
        self.db.execute("""INSERT INTO metric_profiles(profile_id,profile_name,platform,company,expected_shop_name,shop_name,
            review_enabled,reception_enabled,score_enabled,last_seen_at) VALUES
            ('p1','账号一','douyin','公司','店一','店一',1,1,1,'2026-10-01T00:00:00+00:00'),
            ('p2','账号二','douyin','公司','店二','店二',1,0,1,'2026-10-01T00:00:00+00:00')""")
        self.db.execute("INSERT INTO metric_profiles(profile_id,profile_name,platform,company,expected_shop_name,shop_name,excluded,exclusion_reason,last_seen_at) VALUES('p3','账号三','douyin','公司','店三','店三',1,'已关店','2026-10-01T00:00:00+00:00')")
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def events(self, where=""):
        return self.db.execute(f"SELECT * FROM collection_events {where} ORDER BY id").fetchall()

    def auth_event(self, profile_id="p1"):
        return record(self.db, dedupe_key="auth:" + profile_id, source="service", category="auth_required",
                      severity="danger", message="登录失效，请重新登录", profile_id=profile_id)

    def test_schema_version_four_is_idempotent(self):
        initialize_accounts(self.db)
        versions = [row[0] for row in self.db.execute("SELECT version FROM collection_schema ORDER BY version")]
        self.assertEqual(versions, [1, 2, 3, 4, 5, 6, 7])

    def test_same_shop_failure_merges_into_one_open_event(self):
        first = self.auth_event()
        second = self.auth_event()
        self.assertEqual(first, second)
        row = self.events()[0]
        self.assertEqual(row["occurrences"], 2)
        self.assertEqual(row["status"], "open")
        self.assertEqual(row["shop_name"], "店一")
        self.assertEqual(row["platform"], "douyin")
        self.assertEqual(json.loads(row["sources"]), ["service"])

    def test_failed_runs_attach_without_inflating_occurrences(self):
        self.auth_event()
        link_run(self.db, dedupe_key="auth:p1", run_id="run-1", task_kind="reception")
        link_run(self.db, dedupe_key="auth:p1", run_id="run-2", task_kind="reception")
        link_run(self.db, dedupe_key="auth:p1", run_id="run-2", task_kind="reception")
        row = self.events()[0]
        self.assertEqual(row["occurrences"], 1)
        self.assertEqual(row["task_count"], 2)
        self.assertEqual(json.loads(row["run_ids"]), ["run-1", "run-2"])
        self.assertEqual(json.loads(row["sources"]), ["service"])

    def test_task_event_merges_with_service_event(self):
        self.auth_event()
        record(self.db, dedupe_key="auth:p1", source="run", category="auth_required", severity="danger",
               message="采集时登录失效", profile_id="p1", task_kind="reception", run_id="run-9")
        row = self.events()[0]
        self.assertEqual(json.loads(row["sources"]), ["service", "run"])
        self.assertEqual(row["task_count"], 1)
        self.assertEqual(row["message"], "采集时登录失效")

    def test_recovery_keeps_history_and_new_failure_opens_new_event(self):
        self.auth_event()
        self.assertEqual(recover_auth(self.db, "p1"), 1)
        self.assertEqual(self.events("WHERE status='open'"), [])
        self.auth_event()
        rows = self.events()
        self.assertEqual([row["status"] for row in rows], ["recovered", "open"])
        self.assertIsNotNone(rows[0]["recovered_at"])

    def test_run_recovery_only_matches_same_kind(self):
        record(self.db, dedupe_key="run:p1:reception:HTTP_500", source="run", category="run_failed",
               message="接口 500", profile_id="p1", task_kind="reception", run_id="r1")
        record(self.db, dedupe_key="run:p1:score:HTTP_500", source="run", category="run_failed",
               message="接口 500", profile_id="p1", task_kind="score", run_id="r2")
        self.assertEqual(recover_run(self.db, "p1", "reception"), 1)
        statuses = {row["task_kind"]: row["status"] for row in self.events()}
        self.assertEqual(statuses, {"reception": "recovered", "score": "open"})

    def test_recovery_without_target_is_noop(self):
        self.assertEqual(recover_auth(self.db, "p1"), 0)
        self.assertEqual(recover_run(self.db, "p1", "reviews"), 0)

    def test_batch_configure_skips_unsupported_kinds(self):
        result = batch_configure(self.db, {"profileIds": ["p1", "p2"], "scope": {"reviews": "off", "reception": "on", "score": "keep"}}, [])
        self.assertEqual(result, {"updated": 2, "skipped": 1, "total": 2})
        rows = {row["profile_id"]: dict(row) for row in self.db.execute("SELECT profile_id,collect_reviews,collect_reception,collect_score FROM metric_profiles WHERE profile_id IN('p1','p2')")}
        self.assertEqual((rows["p1"]["collect_reviews"], rows["p1"]["collect_reception"], rows["p1"]["collect_score"]), (0, 1, 1))
        self.assertEqual((rows["p2"]["collect_reviews"], rows["p2"]["collect_reception"], rows["p2"]["collect_score"]), (0, 0, 1))

    def test_batch_configure_requires_explicit_change(self):
        with self.assertRaises(ContractError):
            batch_configure(self.db, {"profileIds": ["p1"], "scope": {"reviews": "keep", "reception": "keep", "score": "keep"}}, [])

    def test_batch_configure_rejects_unavailable_shop(self):
        with self.assertRaises(ContractError):
            batch_configure(self.db, {"profileIds": ["p3"], "scope": {"reviews": "on"}}, [])

    def test_batch_configure_rejects_unknown_choice(self):
        with self.assertRaises(ContractError):
            batch_configure(self.db, {"profileIds": ["p1"], "scope": {"reviews": "maybe"}}, [])


if __name__ == "__main__":
    unittest.main()
