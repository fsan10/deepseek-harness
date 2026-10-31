from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from ReverseAPI.Formal_Script import pinduoduo_webapi_download as unified_download
from ReverseAPI.Formal_Script.profile_cdp import ProfileConnection
from ReverseAPI.Formal_Script import pdd_promotion_fee_webapi_download as promotion_download
from ReverseAPI.Formal_Script.pdd_webapi_common import NeedsHumanError


class PinduoduoWebApiTests(unittest.TestCase):
    def test_default_plan_is_order_30_days_and_yesterday_for_other_reports(self) -> None:
        plans = unified_download.build_download_plans(
            None,
            None,
            today=date(2026, 9, 10),
        )
        self.assertEqual(
            [unified_download.ORDER, unified_download.SETTLEMENT, unified_download.PROMOTION],
            [plan.report_type for plan in plans],
        )
        self.assertEqual((date(2026, 8, 12), date(2026, 9, 10)), (plans[0].start, plans[0].end))
        self.assertEqual((date(2026, 9, 9), date(2026, 9, 9)), (plans[1].start, plans[1].end))
        self.assertEqual((date(2026, 9, 9), date(2026, 9, 9)), (plans[2].start, plans[2].end))
        self.assertIn("默认近30天", plans[0].period_text)
        self.assertIn("默认昨天", plans[1].period_text)
        self.assertIn("默认昨天", plans[2].period_text)

    def test_date_and_chinese_report_types_and_no_fund(self) -> None:
        plans = unified_download.build_download_plans(
            "推广费",
            "2026-09-01~2026-09-08",
            today=date(2026, 9, 10),
        )
        self.assertEqual(1, len(plans))
        self.assertEqual((date(2026, 9, 1), date(2026, 9, 8)), (plans[0].start, plans[0].end))
        self.assertEqual(
            (unified_download.ORDER, unified_download.SETTLEMENT, unified_download.PROMOTION),
            unified_download.normalize_report_type("全部"),
        )
        with self.assertRaisesRegex(ValueError, "没有资金报表"):
            unified_download.normalize_report_type("资金")
        with self.assertRaisesRegex(ValueError, "不支持的报表类型"):
            unified_download.normalize_report_type("promotion")
        with self.assertRaisesRegex(ValueError, "不支持的报表类型"):
            unified_download.normalize_report_type("推广")

    def test_unified_resolves_once_and_runs_reports_serially(self) -> None:
        calls: list[tuple[str, str, str, str]] = []

        class FakeOrder:
            def run(self, args):
                calls.append(("order", args.ws_endpoint, args.start, args.end))
                return Path("order.csv")

        class FakeSettlement:
            def run(self, args):
                calls.append(("settlement", args.ws_endpoint, args.start, args.end))
                return Path("settlement.zip")

        class FakePromotion:
            async def run_async(self, args):
                calls.append(("promotion", args.ws_endpoint, args.start_date, args.end_date))
                return Path("promotion.xls")

        connection = ProfileConnection(
            profile_name="PDD-拼多多-养颜轻食",
            profile_id="fixture-profile",
            endpoint="ws://127.0.0.1:45678/devtools/browser/fixture",
            started_by_this_run=False,
        )
        resolver_calls: list[dict[str, object]] = []

        def fake_resolver(**kwargs):
            resolver_calls.append(kwargs)
            return connection

        args = SimpleNamespace(
            profile="PDD-拼多多-养颜轻食",
            ws_endpoint=None,
            debug_port=None,
            mcp_url=None,
            report_type="全部",
            date="2026-09-09",
            output_dir="downloads",
            timeout=10,
            poll_interval=0.01,
            proxy=None,
            template="对账报表",
            manual_trigger=False,
            profile_timeout=1.0,
            profile_poll_interval=0.01,
        )
        with patch.object(unified_download, "order_download", FakeOrder()), patch.object(
            unified_download, "settlement_download", FakeSettlement()
        ), patch.object(
            unified_download, "promotion_download", FakePromotion()
        ):
            outputs = asyncio.run(unified_download.run_async(args, resolver=fake_resolver))

        self.assertEqual(1, len(resolver_calls))
        self.assertEqual(
            [
                ("order", connection.endpoint, "2026-09-09", "2026-09-09"),
                ("settlement", connection.endpoint, "2026-09-09", "2026-09-09"),
                ("promotion", connection.endpoint, "2026-09-09", "2026-09-09"),
            ],
            calls,
        )
        self.assertEqual(3, len(outputs))

    def test_promotion_standalone_defaults_to_yesterday(self) -> None:
        args = promotion_download.parse_args([])
        self.assertEqual("yesterday", args.date_mode)

    def test_unified_exit_codes_include_needs_human_and_interrupt(self) -> None:
        cli = ["--profile", "PDD-拼多多-测试店", "--report-type", "订单"]
        with patch.object(
            unified_download,
            "run_async",
            new=AsyncMock(side_effect=NeedsHumanError("fixture")),
        ):
            self.assertEqual(2, unified_download.main(cli))
        with patch.object(
            unified_download,
            "run_async",
            new=AsyncMock(side_effect=KeyboardInterrupt()),
        ):
            self.assertEqual(130, unified_download.main(cli))


if __name__ == "__main__":
    unittest.main()
