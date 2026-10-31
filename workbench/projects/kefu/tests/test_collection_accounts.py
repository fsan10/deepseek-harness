import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from automation.collection_accounts import initialize_accounts, set_availability, configure_profile, batch_configure
from automation import metric_worker, review_worker
from automation.metric_profiles import sync_profiles
from automation.review_config import PROJECT
from automation.review_errors import AuthRequired, ContractError
from automation.review_session_store import SessionStore
from automation.commerce_cli import enqueue as enqueue_reviews


PROFILE = {"profile_id": "account-test", "profile_name": "DY-抖音-测试店", "platform": "douyin", "company": "测试公司",
           "expected_shop_name": "测试店", "excluded": 0, "exclusion_reason": ""}
SHOPS = [{"platform": "抖音", "name": "测试店", "score": True, "reception": True}]


def memory_db():
    db = sqlite3.connect(":memory:"); db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


class AccountMigrationTests(unittest.TestCase):
    def test_auth_check_migration_defaults_on_and_resync_preserves_manual_choice(self):
        from automation.collection_accounts import execute_schema
        db = memory_db()
        def previous_schema(target, name):
            if name != "collection-auth-check.sql": execute_schema(target, name)
        with patch("automation.collection_accounts.execute_schema", side_effect=previous_schema):
            initialize_accounts(db)
        sync_profiles(db, [PROFILE], SHOPS)
        initialize_accounts(db)
        self.assertEqual(db.execute("SELECT auth_check_enabled FROM metric_profiles").fetchone()[0], 1)
        configure_profile(db, {"profileId": PROFILE["profile_id"], "authCheckEnabled": False}, SHOPS)
        batch_configure(db, {"profileIds": [PROFILE["profile_id"]], "scope": {"score": "off"}}, SHOPS)
        set_availability(db, PROFILE["profile_id"], True)
        sync_profiles(db, [PROFILE], SHOPS)
        set_availability(db, PROFILE["profile_id"], False)
        configure_profile(db, {"profileId": PROFILE["profile_id"], "scope": {"reviews": True, "reception": True, "score": True}}, SHOPS)
        initialize_accounts(db)
        self.assertEqual(db.execute("SELECT auth_check_enabled FROM metric_profiles").fetchone()[0], 0)
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE metric_profiles SET auth_check_enabled=2")
        db.rollback()
        for value in (None, 0, 1, "false", []):
            with self.subTest(value=value), self.assertRaises(ContractError):
                configure_profile(db, {"profileId": PROFILE["profile_id"], "authCheckEnabled": value}, SHOPS)
        self.assertEqual(db.execute("SELECT auth_check_enabled FROM metric_profiles").fetchone()[0], 0)
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        db.close()

    def test_legacy_merge_keeps_mapping_newest_auth_and_business_history(self):
        db = memory_db()
        for name in ("reviews.sql", "metrics-collection.sql"):
            db.executescript((PROJECT / "db" / name).read_text(encoding="utf-8"))
        with db:
            db.execute("INSERT INTO review_profiles(profile_id,profile_name,shop_name,last_seen_at) VALUES('p','DY-抖音-测试店','实际店铺','2026-10-21')")
            db.execute("INSERT INTO metric_profiles(profile_id,profile_name,platform,expected_shop_name,shop_name,score_enabled,reception_enabled,last_seen_at) VALUES('p','DY-抖音-测试店','douyin','实际店铺','入库店铺',1,1,'2026-10-22')")
            db.execute("INSERT INTO review_auth_status(profile_id,state,message,checked_at) VALUES('p','valid','较新的登录','2026-10-22T09:00:00+00:00')")
            db.execute("INSERT INTO metric_auth_status(profile_id,state,message,checked_at) VALUES('p','auth_required','旧状态','2026-10-21T09:00:00Z')")
            db.execute("INSERT INTO review_runs(id,trigger_type,start_date,end_date,created_at,status) VALUES('old','manual','2026-10-20','2026-10-20','2026-10-21','success')")
            db.execute("INSERT INTO review_run_shops(run_id,profile_id,shop_name,status,collected_count) VALUES('old','p','历史店铺','success',1)")
            db.execute("INSERT INTO negative_reviews(profile_id,shop_name,comment_id,order_id,reviewed_at,review_date,review_level,content,product_id,product_name,collected_at,run_id) VALUES('p','历史店铺','review-1','01234567890123456789','2026-10-20 09:00','2026-10-20','差评','历史原文','p-1','原商品','2026-10-21','old')")
            db.execute("INSERT INTO metric_runs(id,kind,start_date,end_date,profile_ids,created_at,status) VALUES('metric-old','score','latest','latest','[\"p\"]','2026-10-21','success')")
            db.execute("INSERT INTO metric_run_items(run_id,profile_id,requested_date,status,record_count) VALUES('metric-old','p','latest','success',3)")
        initialize_accounts(db)
        self.assertEqual(db.execute("SELECT shop_name FROM metric_profiles").fetchone()[0], "入库店铺")
        self.assertEqual(db.execute("SELECT shop_name FROM review_profiles").fetchone()[0], "实际店铺")
        self.assertEqual(db.execute("SELECT state FROM metric_auth_status").fetchone()[0], "valid")
        self.assertEqual(db.execute("SELECT state FROM review_auth_status").fetchone()[0], "valid")
        before = tuple(db.execute("SELECT * FROM negative_reviews").fetchone())
        set_availability(db, "p", True)
        initialize_accounts(db)
        self.assertEqual(db.execute("SELECT excluded FROM review_profiles").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT disabled FROM metric_profiles").fetchone()[0], 1)
        self.assertEqual(tuple(db.execute("SELECT * FROM negative_reviews").fetchone()), before)
        self.assertEqual(db.execute("SELECT status FROM review_run_shops").fetchone()[0], "success")
        self.assertEqual(db.execute("SELECT record_count FROM metric_run_items").fetchone()[0], 3)
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(db.execute("SELECT type FROM sqlite_master WHERE name='review_profiles'").fetchone()[0], "view")
        db.close()

    def test_platform_conflict_rolls_back_without_dropping_legacy(self):
        db = memory_db()
        for name in ("reviews.sql", "metrics-collection.sql"):
            db.executescript((PROJECT / "db" / name).read_text(encoding="utf-8"))
        with db:
            db.execute("INSERT INTO review_profiles(profile_id,profile_name,shop_name,last_seen_at) VALUES('p','DY-抖音-测试店','测试店','2026-10-21')")
            db.execute("INSERT INTO metric_profiles(profile_id,profile_name,platform,last_seen_at) VALUES('p','JD-京东-测试店','jd','2026-10-22')")
        with self.assertRaises(ValueError): initialize_accounts(db)
        self.assertEqual(db.execute("SELECT type FROM sqlite_master WHERE name='review_profiles'").fetchone()[0], "table")
        self.assertNotIn("disabled", [r[1] for r in db.execute("PRAGMA table_info(metric_profiles)")])
        db.close()

    def test_manual_stop_survives_resync_and_blocks_all_three_queues(self):
        db = memory_db(); initialize_accounts(db); sync_profiles(db, [PROFILE], SHOPS)
        set_availability(db, PROFILE["profile_id"], True)
        sync_profiles(db, [PROFILE], SHOPS)
        self.assertEqual(db.execute("SELECT disabled FROM metric_profiles").fetchone()[0], 1)
        for kind in ("reception", "score"):
            with self.assertRaises(ContractError): metric_worker.enqueue(db, {"kind": kind, "profileIds": [PROFILE["profile_id"]]})
        with self.assertRaises(ContractError): enqueue_reviews(db, {"profileIds": [PROFILE["profile_id"]]})
        set_availability(db, PROFILE["profile_id"], False)
        self.assertEqual(db.execute("SELECT excluded FROM review_profiles").fetchone()[0], 0)
        with db: db.execute("UPDATE metric_profiles SET excluded=1,exclusion_reason='已关店'")
        with self.assertRaises(ContractError): set_availability(db, PROFILE["profile_id"], False)
        db.close()

    def test_shared_interval_can_be_updated_from_legacy_entry(self):
        db = memory_db(); initialize_accounts(db)
        with db: db.execute("UPDATE review_auth_settings SET check_interval_minutes=27 WHERE id=1")
        initialize_accounts(db)
        self.assertEqual(db.execute("SELECT auth_poll_minutes FROM metric_service_settings").fetchone()[0], 27)
        db.close()

    def test_scheduled_scope_skips_stopped_shop_without_expanding_to_other_shops(self):
        db = memory_db(); initialize_accounts(db)
        second = {**PROFILE, "profile_id": "second", "profile_name": "DY-抖音-第二店", "expected_shop_name": "第二店"}
        third = {**PROFILE, "profile_id": "third", "profile_name": "DY-抖音-第三店", "expected_shop_name": "第三店"}
        sync_profiles(db, [PROFILE, second, third], SHOPS + [{**SHOPS[0], "name": "第二店"}, {**SHOPS[0], "name": "第三店"}])
        set_availability(db, PROFILE["profile_id"], True)
        metric_worker.enqueue(db, {"kind": "score", "trigger_type": "scheduled", "profileIds": [PROFILE["profile_id"], "second"]})
        self.assertEqual([r[0] for r in db.execute("SELECT profile_id FROM metric_run_items")], ["second"])
        with self.assertRaises(ContractError):
            metric_worker.enqueue(db, {"kind": "reception", "trigger_type": "scheduled", "profileIds": [PROFILE["profile_id"]]})
        self.assertEqual(db.execute("SELECT COUNT(*) FROM metric_runs").fetchone()[0], 1)
        db.close()

    def test_encrypted_sessions_migrate_once_and_logout_cannot_resurrect_them(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); review = root / "reviews"; metric = root / "metrics"; common = root / "common"
            value = {"version": 1, "profile_id": "p", "session_id": "old", "cookies": [{"name": "test", "value": "synthetic"}], "user_agent": "test"}
            SessionStore(review).save("p", value)
            SessionStore(metric).save("p", {**value, "session_id": "new"})
            os.utime(review / "p.enc", (1, 1)); os.utime(metric / "p.enc", (2, 2))
            with patch.dict(os.environ, {"COLLECTION_AUTH_DIR": str(common), "REVIEWS_AUTH_DIR": str(review), "METRICS_AUTH_DIR": str(metric)}):
                store = SessionStore()
                self.assertEqual(store.load("p")["session_id"], "new")
                self.assertFalse(store.refresh("p", value))
                self.assertNotIn(b"synthetic", (common / "p.enc").read_bytes())
                store.delete("p")
                with self.assertRaises(AuthRequired): store.load("p")
                self.assertFalse((review / "p.enc").exists()); self.assertFalse((metric / "p.enc").exists())


class InFlightStopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"COLLECTION_ALERT_CONFIG_PATH": str(Path(self.folder.name) / "alerts.enc")})
        self.env.start()
        self.db = memory_db(); initialize_accounts(self.db); sync_profiles(self.db, [PROFILE], SHOPS)

    def tearDown(self):
        self.db.close(); self.env.stop(); self.folder.cleanup()

    async def test_stop_during_metric_fetch_prevents_import(self):
        metric_worker.enqueue(self.db, {"kind": "score"})
        async def fetch(*_):
            set_availability(self.db, PROFILE["profile_id"], True)
            return {"identity": {"shop_name": "测试店"}, "records": [{"value": 4.8}]}
        writer = AsyncMock()
        with patch("automation.metric_worker.fetch_metrics", new=fetch), patch("automation.metric_worker.import_records", new=writer):
            await metric_worker.execute_run(self.db, self.db.execute("SELECT * FROM metric_runs").fetchone())
        writer.assert_not_awaited()
        self.assertEqual(self.db.execute("SELECT status FROM metric_run_items").fetchone()[0], "skipped")
        self.assertIn("停用", self.db.execute("SELECT message FROM metric_run_items").fetchone()[0])

    async def test_stop_during_review_fetch_cannot_be_marked_no_data(self):
        enqueue_reviews(self.db, {})
        async def fetch(*_):
            set_availability(self.db, PROFILE["profile_id"], True)
            return []
        with patch("automation.review_worker.collect_shop", new=fetch):
            await review_worker.execute_run(self.db, self.db.execute("SELECT * FROM review_runs").fetchone())
        self.assertEqual(self.db.execute("SELECT status FROM review_run_shops").fetchone()[0], "skipped")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM negative_reviews").fetchone()[0], 0)

    async def test_inflight_stop_skips_only_the_stopped_shop_and_continues_others(self):
        second = {**PROFILE, "profile_id": "second", "profile_name": "DY-抖音-第二店", "expected_shop_name": "第二店"}
        sync_profiles(self.db, [PROFILE, second], SHOPS + [{**SHOPS[0], "name": "第二店"}])
        metric_worker.enqueue(self.db, {"kind": "score"})
        set_availability(self.db, PROFILE["profile_id"], True)
        fetch = AsyncMock(return_value={"identity": {"shop_name": "第二店"}, "records": [{"value": 4.9}], "report_date": "2026-10-22", "source_metric": "总分"})
        with patch("automation.metric_worker.fetch_metrics", new=fetch), patch("automation.metric_worker.import_records", new=AsyncMock(return_value=1)):
            await metric_worker.execute_run(self.db, self.db.execute("SELECT * FROM metric_runs").fetchone())
        fetch.assert_awaited_once()
        self.assertEqual(fetch.await_args.args[0]["profile_id"], "second")
        self.assertEqual(dict(self.db.execute("SELECT profile_id,status FROM metric_run_items").fetchall()), {PROFILE["profile_id"]: "skipped", "second": "success"})
        self.assertEqual(self.db.execute("SELECT status FROM metric_runs").fetchone()[0], "success")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM collection_notifications").fetchone()[0], 0)

    async def test_common_poll_skips_manually_disabled_accounts(self):
        from automation.metric_auth import poll_auth_status, record_auth
        record_auth(self.db, PROFILE, "valid", "test")
        with self.db: self.db.execute("UPDATE metric_auth_status SET checked_at='2000-01-01T00:00:00Z'")
        set_availability(self.db, PROFILE["profile_id"], True)
        check = AsyncMock()
        with patch("automation.metric_auth.check_profile", new=check):
            await poll_auth_status(self.db)
            check.assert_not_awaited()
            set_availability(self.db, PROFILE["profile_id"], False)
            await poll_auth_status(self.db)
            check.assert_awaited_once()

    async def test_auth_check_switch_skips_only_poll_and_manual_check_still_recovers(self):
        from automation.metric_auth import poll_auth_status, check_profile, record_auth
        configure_profile(self.db, {"profileId": PROFILE["profile_id"], "authCheckEnabled": False}, SHOPS)
        record_auth(self.db, PROFILE, "valid", "test")
        with self.db: self.db.execute("UPDATE metric_auth_status SET checked_at='2000-01-01T00:00:00Z'")
        with patch("automation.metric_auth.check_profile", new=AsyncMock()) as check:
            await poll_auth_status(self.db)
            check.assert_not_awaited()
        identity = {"shop_name": "测试店", "shop_id": "stable-test-id"}
        with patch("automation.metric_auth.client_for_profile", side_effect=[AuthRequired("expired"), AsyncMock()]), patch("automation.metric_auth.check_identity", new=AsyncMock(return_value=identity)), patch("automation.metric_auth.login_profile", new=AsyncMock()) as login:
            self.assertEqual(await check_profile(self.db, PROFILE), identity)
        login.assert_awaited_once()
        configure_profile(self.db, {"profileId": PROFILE["profile_id"], "authCheckEnabled": True}, SHOPS)
        with self.db: self.db.execute("UPDATE metric_auth_status SET checked_at='2000-01-01T00:00:00Z'")
        with patch("automation.metric_auth.check_profile", new=AsyncMock()) as check:
            await poll_auth_status(self.db)
            check.assert_awaited_once()

    async def test_unchecked_shop_obeys_switch_and_gets_first_poll_when_enabled(self):
        from automation.metric_auth import poll_auth_status
        configure_profile(self.db, {"profileId": PROFILE["profile_id"], "authCheckEnabled": False}, SHOPS)
        with patch("automation.metric_auth.check_profile", new=AsyncMock()) as check:
            await poll_auth_status(self.db)
            check.assert_not_awaited()
            configure_profile(self.db, {"profileId": PROFILE["profile_id"], "authCheckEnabled": True}, SHOPS)
            await poll_auth_status(self.db)
            check.assert_awaited_once()


if __name__ == "__main__": unittest.main()
