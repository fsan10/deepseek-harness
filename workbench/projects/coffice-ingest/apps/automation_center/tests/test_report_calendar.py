from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from apps.automation_center.report_center import ReportCenterMixin
from apps.automation_center.flow_runner import FlowRunner
from apps.automation_center.report_plan import consecutive_ranges, historical_step, selected_dates, step_reports
from scripts.auto_download.move_report import archive_report
from scripts.auto_download.ledger import RunJournal, read_receipts
from scripts.auto_download.playwright.historical_bill import bill_target, locate_bill


class ReportPlanningTests(unittest.TestCase):
    def test_discontinuous_selection_never_downloads_unselected_dates_or_crosses_months(self):
        days = [date(2026,8,30),date(2026,8,31),date(2026,9,1),date(2026,9,3)]
        self.assertEqual([(days[0],days[1]),(days[2],days[2]),(days[3],days[3])], consecutive_ranges(days))

    def test_entire_historical_month_includes_last_day(self):
        days = selected_dates({"month":"2026-08"})
        self.assertEqual((date(2026,8,1),date(2026,8,31),31),(days[0],days[-1],len(days)))

    def test_invalid_dates_future_and_oversized_requests_are_rejected(self):
        for payload in ({"dates":[]},{"month":"2026-13"},{"dates":["2099-01-01"]},
                        {"start_date":"2025-01-01","end_date":"2026-08-31"}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                selected_dates(payload)

    def test_historical_plan_replaces_defaults_and_keeps_account_selection(self):
        step={"module":"qianchuan_promotion_fee_download","args":["--aavid","auto","--start-date","2026-09-01","--end-date","2026-09-30"]}
        result=historical_step(step,"千川推广费",date(2026,8,1),date(2026,8,7))
        self.assertEqual(["--aavid","auto","--start-date","2026-08-01","--end-date","2026-08-07"],result["args"])

    def test_combined_jd_step_expands_into_registered_reports(self):
        reports=step_reports("京东",{"module":"jd_promotion_fee_download","args":["--report","all"]})
        self.assertEqual(["京东联盟推广费","京东通推广费"],[r.report_name for r in reports])

    def test_combined_step_failure_is_visible_for_each_expected_report(self):
        definition={'module':'jd_promotion_fee_download','name':'京东联盟和京东通推广费'}
        step={'profile_name':'p','module_name':definition['module'],'step_name':definition['name'],
              'status':'failed','business_date_start':date(2026,8,1),'business_date_end':date(2026,8,7)}
        for name in ('京东联盟推广费','京东通推广费'):
            target={'profile_name':'p','report_name':name,'report_type':name,'enabled':True,'step':definition}
            self.assertEqual('failed',ReportCenterMixin._report_outcome(target,date(2026,8,3),[],[step])[0])

    def test_daily_bill_refuses_accidental_range(self):
        with self.assertRaises(ValueError):
            historical_step({"module":"jd_settlement_download"},"结算",date(2026,8,1),date(2026,8,7))

    def test_outcome_preserves_verified_success_after_a_later_failed_attempt(self):
        target={"profile_name":"p","report_type":"r","report_name":"订单","enabled":True,"step":{"module":"m"}}
        artifact={"profile_name":"p","report_type":"r","coverage_verified":True,"business_date_start":date(2026,8,1),
                  "business_date_end":date(2026,8,7),"step_status":"success","file_exists":True,"period_type":"date_range"}
        self.assertEqual("success",ReportCenterMixin._report_outcome(target,date(2026,8,3),[artifact],[])[0])
        artifact["period_type"]="month"
        self.assertEqual("monthly_only",ReportCenterMixin._report_outcome(target,date(2026,8,3),[artifact],[])[0])
        artifact["file_exists"]=False
        self.assertEqual("missing_file",ReportCenterMixin._report_outcome(target,date(2026,8,3),[artifact],[])[0])

    def test_outcome_trusts_the_archived_file_even_when_legacy_mapping_flag_is_false(self):
        """旧实现把 coverage_verified 与 DIM 绑定；全/半角括号导致的误判不能继续吞噬已下载状态。"""

        target={"profile_name":"p","report_type":"r","report_name":"订单","enabled":True,"step":{"module":"m"}}
        artifact={"profile_name":"p","report_type":"r","coverage_verified":False,"business_date_start":date(2026,8,1),
                  "business_date_end":date(2026,8,7),"step_status":"success","file_exists":True,"period_type":"date_range"}
        self.assertEqual("success",ReportCenterMixin._report_outcome(target,date(2026,8,3),[artifact],[])[0])


class ArchiveReceiptTests(unittest.TestCase):
    def test_flow_resume_requires_every_archived_file_and_restores_pending_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);files=[root/'one.csv',root/'two.csv']
            for path in files:path.write_text('a\nb',encoding='utf-8')
            runner=FlowRunner.__new__(FlowRunner);runner.runtime={};runner.destination=root
            values={'pending_artifact':{'source_path':str(files[-1])},
                    'pending_artifacts':[{'source_path':str(path)} for path in files],
                    'artifact_receipts':[{'relative_path':path.name,'file_size_bytes':path.stat().st_size} for path in files]}
            checkpoint={'component_code':'report.archive','output_snapshot':{'runtime':values}}
            self.assertTrue(runner._checkpoint_can_skip({'component_code':'report.archive'},checkpoint))
            self.assertIsInstance(runner.runtime['pending_artifacts'][0]['source_path'],Path)
            files[0].unlink()
            self.assertFalse(runner._checkpoint_can_skip({'component_code':'report.archive'},checkpoint))

    def test_month_receipt_keeps_month_granularity_with_explicit_dates(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.csv';source.write_text('a\nb',encoding='utf-8')
            receipt=root/'receipt.json'
            archive_report(source,'京东','公司','店铺','结算','2026-08',root,
                           period_start='2026-08-01',period_end='2026-08-31',receipt_path=receipt)
            self.assertEqual('month',read_receipts(receipt)[0]['period_type'])

    def test_empty_download_cannot_be_archived_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'empty.csv';source.touch()
            with self.assertRaises(ValueError):
                archive_report(source,'京东','公司','店铺','结算','2026-08-01',root)
            self.assertTrue(source.exists())

    def test_cross_month_download_archives_by_business_month_and_records_range(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/"source.csv";source.write_text("header\nvalue",encoding="utf-8")
            receipt=root/"receipt.json"
            target=archive_report(source,"抖音","公司","店铺","订单","2026-08-07",root,
                                  period_start="2026-08-01",period_end="2026-08-07",receipt_path=receipt)
            self.assertEqual("2026.08",target.parent.name)
            row=read_receipts(receipt)[0]
            self.assertEqual(("2026-08-01","2026-08-07","date_range"),
                             (row["business_date_start"],row["business_date_end"],row["period_type"]))
            self.assertFalse(source.exists());self.assertTrue(row["coverage_verified"])

    def test_wrong_period_is_rejected_before_moving_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/"source.csv";source.write_text("a",encoding="utf-8")
            with self.assertRaises(ValueError):
                archive_report(source,"抖音","公司","店铺","订单","2026-08-09",root,
                               period_start="2026-08-01",period_end="2026-08-07")
            self.assertTrue(source.exists())

    def test_journal_omits_sensitive_payload_and_keeps_gate_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=RunJournal(Path(directory),"test-run","overnight")
            journal.emit("gate",{"status":"skip_non_workday","reason":"holiday","password":"sensitive","args":["secret"],"output_summary":"secret"})
            value=journal.path.read_text(encoding="utf-8")
            self.assertNotIn("sensitive",value);self.assertNotIn("secret",value)
            self.assertEqual("holiday",json.loads(value)["events"][0]["payload"]["reason"])


class ExactBillLookupTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_target_never_returns_latest_bill(self):
        page=Mock();rows=Mock();rows.first.wait_for=AsyncMock();rows.all_inner_texts=AsyncMock(return_value=["2026-09-30 下载"])
        page.locator.return_value=rows
        buttons=Mock();buttons.count=AsyncMock(return_value=0);buttons.locator.return_value=buttons;page.get_by_role.return_value=buttons
        with patch.object(page,"locator",side_effect=[rows,buttons,buttons]):
            buttons.last=buttons
            with self.assertRaisesRegex(RuntimeError,"REPORT_NOT_READY"):
                await locate_bill(page,"rows","2026-08-01","day",lambda text,mode:text[:10],lambda row:None)

    async def test_matching_target_returns_that_row(self):
        page=Mock();rows=Mock();rows.first.wait_for=AsyncMock();rows.all_inner_texts=AsyncMock(return_value=["2026-09-30","2026-08-01"])
        page.locator.return_value=rows;action=Mock();action.count=AsyncMock(return_value=1)
        row,_=await locate_bill(page,"rows","2026-08-01","day",lambda text,mode:text,lambda row:action)
        self.assertIs(row,rows.nth.return_value);rows.nth.assert_called_once_with(1)

    def test_bill_target_rejects_mismatched_granularity(self):
        with self.assertRaises(ValueError):bill_target("month","2026-08-01")
