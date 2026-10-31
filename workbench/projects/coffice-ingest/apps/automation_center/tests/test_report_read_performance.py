"""Prevent repeated history connections and preserve report outcomes."""
import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from apps.automation_center.report_center import ReportCenterMixin


class ReportReadPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service = ReportCenterMixin()
        self.service.archive_root = Path(self.directory.name)
        self.root = self.service.archive_root / '.automation_logs/report_ledger'
        self.root.mkdir(parents=True)
        self.cursor = Mock()
        self.transactions = 0

        @contextmanager
        def transaction():
            self.transactions += 1
            yield self.cursor
        self.service.transaction = transaction

    def journal(self, key):
        (self.root / (key + '.json')).write_text(json.dumps({'external': True, 'run_id': key,
            'events': [{'event': 'completed', 'payload': {'status': 'success'}}]}), encoding='utf-8')

    def test_completed_history_uses_one_connection_and_takes_no_per_journal_locks(self):
        for number in range(65):
            self.journal(str(number))
        self.cursor.fetchall.side_effect = [[{'journal_key': str(n), 'imported_events': 1} for n in range(65)], [], []]
        self.assertEqual(0, self.service.sync_report_journals())
        self.assertEqual(1, self.transactions)
        self.assertEqual(3, self.cursor.execute.call_count)
        self.assertTrue(all('pg_advisory' not in call.args[0] for call in self.cursor.execute.call_args_list))

    def test_changed_journal_rechecks_offset_after_lock_for_concurrent_importer(self):
        self.journal('changed')
        self.cursor.fetchall.side_effect = [[{'journal_key': 'changed', 'imported_events': 0}], [], []]
        self.cursor.fetchone.return_value = {'imported_events': 1}
        self.assertEqual(0, self.service.sync_report_journals())
        self.assertEqual(2, self.transactions)
        statements = [call.args[0] for call in self.cursor.execute.call_args_list]
        self.assertTrue(any('pg_advisory_xact_lock' in statement for statement in statements))
        self.assertFalse(any('INSERT' in statement or 'UPDATE' in statement for statement in statements))

    def test_empty_journal_directory_does_not_connect(self):
        self.assertEqual(0, self.service.sync_report_journals())
        self.assertEqual(0, self.transactions)

    def target(self):
        return dict(profile_name='shop', platform='拼多多', shop='店铺', company='公司',
            report_type='order', report_name='订单', enabled=True, profile_enabled=True, report_enabled=True,
            step={'module': 'orders', 'name': '订单'})

    def test_index_preserves_success_priority_over_newer_failed_attempt(self):
        target = self.target()
        artifacts = [dict(profile_name='shop', report_type='order', file_exists=True, period_type='date_range',
            business_date_start=date(2026, 10, 1), business_date_end=date(2026, 10, 7))]
        steps = [dict(profile_name='shop', module_name='orders', step_name='订单', status='failed',
            business_date_start=date(2026, 10, 1), business_date_end=date(2026, 10, 8))]
        indexed = self.service._index_report_evidence(artifacts, steps)
        for day in (date(2026, 10, 1), date(2026, 10, 8), date(2026, 10, 9)):
            self.assertEqual(self.service._report_outcome(target, day, artifacts, steps),
                self.service._report_outcome(target, day, *indexed))

    def prepare_report(self):
        self.service.sync_report_journals = Mock(return_value=0)
        self.service.report_targets = Mock(return_value={'items': [self.target()], 'updated_at': 'now', 'warning': None})
        self.service._report_evidence = Mock(return_value=([], [], []))

    def test_list_reads_the_seven_day_window_once(self):
        self.prepare_report()
        result = self.service.report_day({'date': '2026-10-19'})
        self.assertEqual(1, result['summary']['reports'])
        self.service._report_evidence.assert_called_once_with(date(2026, 10, 13), date(2026, 10, 19), include_executions=False)

    def test_compact_calendar_preserves_summaries_and_gap_selection_identities(self):
        self.prepare_report()
        full = self.service.report_calendar({'month': '2026-10'})
        compact = self.service.report_calendar({'month': '2026-10', 'compact': '1'})
        for original, small in zip(full['days'], compact['days']):
            self.assertEqual(original['summary'], small['summary'])
            self.assertEqual(original['counts'], small['counts'])
            self.assertNotIn('items', small)
            for shop, reduced in zip(original['shops'], small['shops']):
                for key in ('key', 'profile_name', 'shop', 'platform', 'enabled', 'state'):
                    self.assertEqual(shop[key], reduced[key])
                for report, reduced_report in zip(shop['reports'], reduced['reports']):
                    for key in ('report_type', 'report_name', 'enabled', 'status', 'upload_status', 'run_id'):
                        self.assertEqual(report[key], reduced_report[key])


if __name__ == '__main__':
    unittest.main()
