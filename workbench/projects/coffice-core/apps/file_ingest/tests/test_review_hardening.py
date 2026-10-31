"""Coverage proof, source observation and replay publication boundaries."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout,redirect_stderr
from datetime import date
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock,patch

from apps.file_ingest.errors import ShopCodeRequired
from apps.file_ingest.service import FileIngestService,FileIngestWorker,ConflictError
from apps.file_ingest.source_diagnostics import observe
from apps.file_ingest import refresh_scope
from apps.file_ingest.tests import test_coverage_workflow as fixtures
from etl.common.source_coverage import freeze_jd_fund_coverage,summarize_days
from etl.jd.wallet_reconciliation import expected_wallet_date,unmatched_status,validate


class WalletGuardTests(unittest.TestCase):
    def test_date_prefix_matches_original_ascii_20_rule(self):
        start=date(2026,10,20)
        for value in ('19990101x','21000101x','20260230x','20261301x','abcd','２０２６１０２１x','20',''):
            with self.subTest(value=value):
                self.assertEqual(expected_wallet_date(value,start),date(2026,10,21))
        self.assertEqual(expected_wallet_date('20240229valid',start),date(2024,2,29))

    def test_coverage_gaps_cannot_be_filled_by_min_and_max(self):
        coverage=summarize_days(['2026-10-01','2026-10-03'])
        self.assertEqual(len(coverage['intervals']),2)
        self.assertEqual(unmatched_status(date(2026,10,2),coverage,date(2026,10,21)),'uncovered_count')
        self.assertEqual(unmatched_status(date(2026,10,1),coverage,date(2026,10,21)),'missing_count')
        self.assertEqual(unmatched_status(date(2026,9,30),coverage,date(2026,10,21)),'uncovered_count')
        self.assertEqual(unmatched_status(date(2026,10,2),{},date(2026,10,21)),'coverage_unknown_count')
        self.assertEqual(unmatched_status(date(2026,10,21),{},date(2026,10,21)),'pending_count')

    def cursor(self, wallet=100):
        cur=Mock()
        cur.fetchall.side_effect=[
            [('jd|one','20261002x',date(2026,10,1),date(2026,10,1),100),
             ('jd|one','20261003x',date(2026,10,2),date(2026,10,2),20)],
            [('jd|one',7,date(2026,10,1),date(2026,10,2))],
            [('jd|one','20261002x',wallet),('jd|one','20261003x',20)] if wallet is not None else [],
            [('jd|one',date(2026,10,20),date(2026,10,20))]]
        return cur

    def test_groups_and_physical_source_batches_are_reported_separately(self):
        with redirect_stdout(io.StringIO()):result=validate(self.cursor(),{'as_of_date':'2026-10-21'})
        self.assertEqual(result['settlement_group_count'],2)
        self.assertEqual(result['settlement_batch_count'],2) # compatibility alias
        self.assertEqual(result['source_batch_count'],1)
        self.assertEqual(result['settlement_batches'][0]['date_to'],date(2026,10,2))

    def test_unknown_or_uncovered_fund_dates_still_block_publication(self):
        for coverage,marker in [({},'fund_coverage_unknown=2'),
                ({'jd|one':summarize_days(['2026-10-20'])},'fund_not_covered=2'),
                ({'jd|one':summarize_days(['2026-10-02','2026-10-03'])},'missing=2')]:
            with self.subTest(marker=marker),redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError,marker):
                    validate(self.cursor(None),{'as_of_date':'2026-10-21','fund_coverage':coverage})

    def test_shop_code_error_preserves_numeric_http_envelope(self):
        with self.assertRaises(ShopCodeRequired) as raised:
            FileIngestService._resolve_shop(None,None,None,{},'named-shop.csv')
        from apps.fund_split_adjust.server import ApplicationHandler
        handler=SimpleNamespace(send_json=Mock())
        ApplicationHandler.handle_error(handler,raised.exception)
        self.assertEqual(handler.send_json.call_args.kwargs['code'],400)
        self.assertEqual(handler.send_json.call_args.args[0]['details']['error_code'],'SHOP_CODE_REQUIRED')

    def test_replay_requires_explicit_publish_confirmation_before_database_access(self):
        service=FileIngestService.__new__(FileIngestService)
        with self.assertRaisesRegex(ConflictError,'并非只读诊断'):
            service.retry_etl_task('none','tester',None,snapshot_policy='replay')

    def test_cli_rejects_unconfirmed_replay_before_login(self):
        from apps.file_ingest.cli import main
        with patch('sys.argv',['ingest','retry','--task-id','test-only','--snapshot-policy','replay']),\
             patch('apps.file_ingest.cli.load_env'),patch('apps.file_ingest.cli.Client') as client,\
             redirect_stderr(io.StringIO()):
            self.assertEqual(main(),2)
            client.assert_not_called()

    def test_old_manual_manifest_is_rejected_before_database_access(self):
        from etl.common.settlement_sources import main
        with tempfile.TemporaryDirectory() as folder:
            manifest=Path(folder)/'manual.json'
            manifest.write_text(json.dumps([{'batch_id':1,'start':'2026-10-01','end':'2026-10-18','evidence':{'confirmation':'test'}}]),encoding='utf-8')
            with patch('sys.argv',['sources','--manifest',str(manifest)]),patch('etl.common.settlement_sources.load_pg_env'),\
                 patch('psycopg2.connect') as connect,redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:main()
                self.assertEqual(raised.exception.code,2);connect.assert_not_called()

    def test_wallet_structured_output_survives_metrics_extraction(self):
        metrics=FileIngestWorker._extract_metrics('[WALLET_RECONCILIATION] '+json.dumps({'coverage_unknown_count':2}))
        self.assertEqual(metrics['wallet_reconciliation']['coverage_unknown_count'],2)


class SourceObservationDatabaseTests(fixtures.CoverageDatabaseTests):
    def context(self, batch=0, selection=0):
        return {'version':1,'mode':'incremental','trigger_type':'ingest_complete','months':{'jd':['2026-10-01']},
            'shops':{'jd':['one']},'batch_cutoff':batch,'source_selection_cutoff':selection,'excluded_batch_ids':[]}

    def observation(self, context):
        with self.service.transaction() as cur:return observe(cur,context,['jd_main_business_finance'])

    def test_pending_latest_and_replay_cannot_be_reused_as_each_other(self):
        run_id,_=self.legacy_upload([('2026-10-01',10,'a')])
        task_id=self.failed_douyin_run(run_id)
        first=self.service.retry_etl_task(task_id,'tester',None)
        same=self.service.retry_etl_task(task_id,'tester',None)
        self.assertEqual(str(first['etl_run_id']),str(same['etl_run_id']));self.assertTrue(same['reused'])
        with self.assertRaisesRegex(ConflictError,'不同快照方式'):
            self.service.retry_etl_task(task_id,'tester',None,snapshot_policy='replay',confirm_replay_publish=True)

    def test_observation_ignores_unrelated_month_and_preserves_context(self):
        self.legacy_upload([('2026-09-01',10,'a')],report='jd_fund')
        context=self.context();before=copy.deepcopy(context)
        result=self.observation(context)
        self.assertFalse(result['snapshot_stale']);self.assertEqual(context,before)

    def test_observation_finds_late_completion_below_cutoff(self):
        _,batch=self.legacy_upload([('2026-10-11',10,'a')],report='jd_fund')
        context=self.context(batch+10);context['excluded_batch_ids']=[batch]
        result=self.observation(context)
        self.assertTrue(result['snapshot_stale'])
        self.assertEqual(result['relevant_batches'][0]['reason'],'completed_after_freeze')

    def test_observation_includes_next_day_wallet_dependency(self):
        self.legacy_upload([('2026-11-01',10,'a')],report='jd_fund')
        self.assertTrue(self.observation(self.context())['snapshot_stale'])

    def test_reselection_without_new_ods_batch_is_observed(self):
        run_id,batch=self.legacy_upload([('2026-10-10',10,'a')],report='jd_fund')
        draft=self.service.reuse_run_files(run_id,{'idempotency_key':'selection-only'},'tester',None)
        self.finish(str(draft['run']['run_id']))
        result=self.observation(self.context(batch))
        self.assertFalse(result['relevant_batches'])
        self.assertEqual(len(result['relevant_selection_changes']),1)

    def test_complete_fund_claim_freezes_zero_days_and_excludes_future_choices(self):
        run_id,_=self.upload([('2026-10-10',10,'a')],report='jd_fund',claim={
            'start':'2026-10-10','end':'2026-10-11','complete_export':True})
        self.finish(run_id)
        with self.service.transaction() as cur:
            cur.execute('SELECT batch_id FROM ops.ingest_file_task WHERE run_id=%s',(run_id,));batch=cur.fetchone()['batch_id']
            cur.execute('SELECT max(selection_id) revision FROM common.ingest_source_day_selection');revision=cur.fetchone()['revision']
            context=self.context(batch,revision)
            proven=freeze_jd_fund_coverage(cur,context)
            self.assertEqual(proven['jd|one']['verified_days'],['2026-10-10','2026-10-11'])
            self.assertEqual(freeze_jd_fund_coverage(cur,self.context(batch,0)),{})
            context['excluded_batch_ids']=[batch]
            self.assertEqual(freeze_jd_fund_coverage(cur,context),{})

    def test_content_dates_alone_do_not_prove_full_fund_range(self):
        run_id,_=self.upload([('2026-10-10',10,'a'),('2026-10-12',20,'b')],report='jd_fund')
        self.finish(run_id)
        with self.service.transaction() as cur:
            cur.execute('SELECT batch_id FROM ops.ingest_file_task WHERE run_id=%s',(run_id,));batch=cur.fetchone()['batch_id']
            cur.execute('SELECT max(selection_id) revision FROM common.ingest_source_day_selection');revision=cur.fetchone()['revision']
            self.assertEqual(freeze_jd_fund_coverage(cur,self.context(batch,revision)),{})

    def test_fill_that_keeps_old_rows_against_empty_export_is_not_complete_proof(self):
        first,_=self.upload([('2026-10-10',10,'a')],report='jd_fund');self.finish(first)
        second,_=self.upload([],report='jd_fund',claim={'start':'2026-10-10','end':'2026-10-10','complete_export':True})
        self.finish(second)
        with self.service.transaction() as cur:
            cur.execute('SELECT max(batch_id) b FROM ods.ods_file_ingest_log');batch=cur.fetchone()['b']
            cur.execute('SELECT max(selection_id) s FROM common.ingest_source_day_selection');selection=cur.fetchone()['s']
            self.assertEqual(freeze_jd_fund_coverage(cur,self.context(batch,selection)),{})

    def test_observation_ignores_another_shop(self):
        with self.service.transaction() as cur:
            self.seed_wallet_source(cur,'two','20261011other','2026-10-11',10)
        self.assertFalse(self.observation(self.context())['snapshot_stale'])

    def test_coverage_guard_rolls_back_staged_dwd_changes(self):
        with self.service.transaction() as cur:
            cur.execute("""INSERT INTO dwd.dwd_jd_platform_expense_source_detail VALUES
                ('jd|one','one','20261002missing','2026-10-01',1,100,'settlement','订单','2026-10-01')""")
        with self.assertRaisesRegex(RuntimeError,'fund_coverage_unknown=1'),redirect_stdout(io.StringIO()):
            with self.service.transaction() as cur:
                cur.execute("UPDATE dwd.dwd_jd_platform_expense_source_detail SET signed_amount=999")
                # Metric validators use tuple cursors, sharing the transaction.
                with cur.connection.cursor() as ledger:validate(ledger,{'as_of_date':'2026-10-21'})
        with self.service.transaction() as cur:
            cur.execute('SELECT signed_amount FROM dwd.dwd_jd_platform_expense_source_detail')
            self.assertEqual(cur.fetchone()['signed_amount'],100)

    def test_cross_month_wallet_uses_frozen_ods_without_publishing_another_month(self):
        from etl.common.refresh_runtime import connection_factory
        with self.service.transaction() as cur:
            batch=self.seed_wallet_source(cur,'one','20261101boundary','2026-11-01',100)
            cur.execute("""INSERT INTO dwd.dwd_jd_platform_expense_source_detail VALUES
                ('jd|one','one','20261101boundary','2026-10-31',1,100,'settlement','订单','2026-10-31')""")
        context=self.context(batch);context['as_of_date']='2026-11-02'
        conn=fixtures.psycopg2.connect(**self.service.connect_kwargs,connection_factory=connection_factory(context))
        try:
            with conn.cursor() as cur,redirect_stdout(io.StringIO()):
                result=validate(cur,context)
            self.assertEqual(result['matched_count'],1)
        finally:conn.close()

        with self.service.transaction() as cur:
            cur.execute("SELECT count(*) n FROM dwd.dwd_jd_platform_expense_source_detail WHERE stat_date>='2026-11-01'")
            self.assertEqual(cur.fetchone()['n'],0)
            # Even a later published wallet must not leak into an old replay.
            cur.execute("""INSERT INTO dwd.dwd_jd_platform_expense_source_detail VALUES
                ('jd|one','one','20261101boundary','2026-11-01',%s,100,'fund','商户结算','2026-11-01')""",(batch,))
        context['excluded_batch_ids']=[batch]
        conn=fixtures.psycopg2.connect(**self.service.connect_kwargs,connection_factory=connection_factory(context))
        try:
            with self.assertRaisesRegex(RuntimeError,'fund_coverage_unknown=1'),redirect_stdout(io.StringIO()):
                with conn.cursor() as cur:validate(cur,context)
        finally:conn.close()

    def test_frozen_wallet_preserves_native_dedup_and_existing_direction_formula(self):
        with self.service.transaction() as cur:
            self.seed_wallet_source(cur,'one','20261002signed','2026-10-02',100)
            outgoing=self.seed_wallet_source(cur,'one','20261002signed','2026-10-02',30)
            cur.execute('UPDATE ods.ods_jd_fund_raw SET "支出类型"=\'支出\' WHERE batch_id=%s',(outgoing,))
            self.seed_wallet_source(cur,'one','20261002signed','2026-10-02',100)
            cur.execute("""INSERT INTO dwd.dwd_jd_platform_expense_source_detail VALUES
                ('jd|one','one','20261002signed','2026-10-01',1,70,'settlement','订单','2026-10-01')""")
            with cur.connection.cursor() as ledger,redirect_stdout(io.StringIO()):
                result=validate(ledger,{'as_of_date':'2026-10-21'})
            self.assertEqual(result['matched_count'],1);self.assertEqual(result['fund_total'],70)

    def test_reconciliation_tool_accepts_already_approved_identical_old_day(self):
        from apps.file_ingest.coverage import load_file,business_day
        from etl.platform_finance.reconcile_settlement import _matches_approved_douyin_source
        first,_=self.upload([('2026-10-01',10,'a')]);self.finish(first)
        second,_=self.upload([('2026-10-01',10,'a'),('2026-10-02',20,'b')]);self.finish(second)
        with self.service.transaction() as cur:
            cur.execute('SELECT * FROM ops.ingest_file_task WHERE run_id=%s',(second,))
            _,rows=load_file(dict(cur.fetchone()),self.service.storage_root)
            local=[(n,date.fromisoformat(business_day(row['结算时间'])),row) for n,row in enumerate(rows)]
            entry={'start':'2026-10-01','end':'2026-10-02'}
            with cur.connection.cursor() as audit:
                self.assertFalse(_matches_approved_douyin_source(audit,'one',[],{'start':'2026-09-01','end':'2026-09-30'}))
                self.assertTrue(_matches_approved_douyin_source(audit,'one',local,entry))
                rows[0]['结算金额']='11'
                self.assertFalse(_matches_approved_douyin_source(audit,'one',local,entry))
