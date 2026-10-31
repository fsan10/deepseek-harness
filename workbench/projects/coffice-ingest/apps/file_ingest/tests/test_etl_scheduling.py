from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from apps.file_ingest.registry import plan_etls
from apps.file_ingest.service import FileIngestService


class LegacyEtlSchedulerRetirementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parents[3]

    def test_legacy_scheduler_processes_and_api_are_removed(self):
        self.assertFalse((self.project_root / "apps/file_ingest/nightly_scheduler.py").exists())
        self.assertFalse((self.project_root / "apps/file_ingest/schedule_full_refresh.py").exists())
        self.assertNotIn("NightlyScheduler", (self.project_root / "apps/fund_split_adjust/server.py").read_text(encoding="utf-8"))
        self.assertNotIn("/api/etl/nightly-schedule", (self.project_root / "apps/file_ingest/module.py").read_text(encoding="utf-8"))

    def test_retirement_migration_disables_existing_legacy_row(self):
        migration = (self.project_root / "sql/common/431_retire_legacy_etl_nightly_schedule_postgres.sql").read_text(encoding="utf-8")
        self.assertIn("to_regclass('ops.etl_nightly_schedule')", migration)
        self.assertIn("SET enabled = FALSE", migration)
        self.assertIn("AND enabled IS DISTINCT FROM FALSE", migration)


class EtlSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.service = FileIngestService.__new__(FileIngestService)
        self.calls: list[tuple[set[str], dict]] = []

        def capture(keys, **kwargs):
            key_set = set(keys)
            self.calls.append((key_set, kwargs))
            return {"tasks": sorted(key_set)}

        self.service.create_etl_run = capture

    def test_manual_full_does_not_refresh_bank(self):
        result = self.service.create_manual_etl({"scope": "all"}, "tester")
        keys, kwargs = self.calls[-1]
        self.assertNotIn("bank_management", keys)
        self.assertNotIn("platform_bank_summary", keys)
        self.assertEqual("manual", kwargs["trigger_type"])
        self.assertNotIn("bank_management", result["tasks"])

    def test_manual_selected_bank_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "财务提交"):
            self.service.create_manual_etl(
                {"scope": "selected", "etls": ["bank_management"]},
                "tester",
            )
        self.assertFalse(self.calls)

    def test_automatic_full_refresh_is_rejected_before_database_access(self):
        service = FileIngestService.__new__(FileIngestService)
        with self.assertRaisesRegex(ValueError, '全量刷新只能由人工'):
            service.create_etl_run({'ks_settlement'}, trigger_type='nightly', scope='all', operator='test')

    def test_same_import_reuses_the_existing_refresh(self):
        service = FileIngestService.__new__(FileIngestService)
        cursor = MagicMock()
        keys = {'ks_settlement'}
        cursor.fetchone.return_value = {
            'etl_run_id': 'existing-run', 'status': 'success',
            'requested_etls': [spec.key for spec in plan_etls(keys)],
        }
        result = service.create_etl_run(keys, trigger_type='ingest_complete', scope='affected',
                                        operator='test', ingest_run_id='existing-import', cursor=cursor)
        self.assertTrue(result['reused'])
        self.assertEqual('existing-run', result['etl_run_id'])
        self.assertFalse(any('INSERT INTO' in call.args[0] for call in cursor.execute.call_args_list))

    def test_affected_run_keeps_platform_aggregators_runnable_when_sources_are_empty(self):
        service = FileIngestService.__new__(FileIngestService)

        def empty_relation(_cursor, relation):
            return 0 if relation.startswith(("ods.", "dws.", "ads.")) else None

        service._relation_count = empty_relation
        specs = plan_etls({"douyin_platform_expense", "douyin_main_business_income", "operating_sales"})
        reasons = service._deferred_etl_reasons(
            specs,
            trigger_type="ingest_complete",
            scope="affected",
            cursor=object(),
        )

        self.assertNotIn("operating_sales", reasons)
        self.assertNotIn("platform_main_business_income_shared_ads", reasons)
        self.assertNotIn("douyin_platform_expense", reasons)

    def test_manual_or_fee_mapping_run_does_not_defer_by_readiness(self):
        service = FileIngestService.__new__(FileIngestService)
        service._relation_count = lambda _cursor, _relation: 0
        specs = plan_etls({"operating_sales"})

        self.assertEqual(
            {},
            service._deferred_etl_reasons(
                specs,
                trigger_type="manual",
                scope="selected",
                cursor=object(),
            ),
        )

    def test_shared_ads_has_no_all_platform_readiness_gate(self):
        service = FileIngestService.__new__(FileIngestService)
        service._relation_count = lambda _cursor, _relation: 0
        specs = plan_etls(
            {
                "douyin_main_business_income",
                "ks_main_business_income",
                "jd_main_business_finance",
                "tmall_main_business_finance",
                "pdd_main_business_finance",
                "wechat_channels_main_business_finance",
                "xhs_main_business_finance",
            }
        )
        reasons = service._deferred_etl_reasons(
            specs,
            trigger_type="ingest_complete",
            scope="affected",
            cursor=object(),
        )

        self.assertEqual({}, reasons)


if __name__ == "__main__":
    unittest.main()
