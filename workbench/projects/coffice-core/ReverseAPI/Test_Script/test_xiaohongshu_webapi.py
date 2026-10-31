from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from ReverseAPI.Formal_Script.xiaohongshu_fund_webapi_download import (
    build_period_payload as build_fund_period_payload,
    query_all_period_rows as query_all_fund_rows,
    query_range as fund_query_range,
    select_period_row as select_fund_row,
)
from ReverseAPI.Formal_Script.xiaohongshu_order_webapi_download import (
    build_export_condition,
    build_order_page_payload,
    build_start_export_payload,
)
from ReverseAPI.Formal_Script.xiaohongshu_settlement_webapi_download import (
    build_period_payload as build_settlement_period_payload,
    query_range as settlement_query_range,
    select_period_row as select_settlement_row,
)
from ReverseAPI.Formal_Script.profile_cdp import ProfileConnection
from ReverseAPI.Formal_Script import xiaohongshu_webapi_download as unified_download
from ReverseAPI.Formal_Script import xhs_webapi_common as xhs_common
from ReverseAPI.Formal_Script.xhs_webapi_common import (
    ApiError,
    BrowserApiSession,
    NaturalRequestCollector,
    NeedsHumanError,
    ObservedRequest,
    extract_download_url,
    parse_period_key,
)


class XiaohongshuWebApiTests(unittest.TestCase):
    def test_unified_default_plan_is_order_30_days_and_yesterday_bills(self):
        plans = unified_download.build_download_plans(
            None,
            None,
            today=date(2026, 9, 10),
        )
        self.assertEqual(
            [unified_download.ORDER, unified_download.FUND, unified_download.SETTLEMENT],
            [plan.report_type for plan in plans],
        )
        self.assertEqual((date(2026, 8, 12), date(2026, 9, 10)), (plans[0].start, plans[0].end))
        self.assertEqual((date(2026, 9, 9), date(2026, 9, 9)), (plans[1].start, plans[1].end))
        self.assertEqual((date(2026, 9, 9), date(2026, 9, 9)), (plans[2].start, plans[2].end))
        self.assertIn("默认近30天", plans[0].period_text)
        self.assertIn("默认昨天", plans[1].period_text)
        self.assertIn("默认昨天", plans[2].period_text)

    def test_unified_explicit_date_and_chinese_report_types(self):
        order_plans = unified_download.build_download_plans(
            "订单",
            "2026-08-01~2026-08-07",
            today=date(2026, 9, 10),
        )
        self.assertEqual(1, len(order_plans))
        self.assertEqual((date(2026, 8, 1), date(2026, 8, 7)), (order_plans[0].start, order_plans[0].end))

        fund_plans = unified_download.build_download_plans(
            "资金",
            "2026-08",
            today=date(2026, 9, 10),
        )
        self.assertEqual(1, len(fund_plans))
        self.assertEqual("month", fund_plans[0].mode)
        self.assertEqual("2026-08", fund_plans[0].requested)
        self.assertEqual(
            (unified_download.ORDER, unified_download.FUND, unified_download.SETTLEMENT),
            unified_download.normalize_report_type("全部"),
        )
        with self.assertRaisesRegex(ValueError, "不支持的报表类型"):
            unified_download.normalize_report_type("fund")

    def test_unified_resolves_profile_once_and_runs_reports_serially(self):
        calls: list[tuple[str, str, str | None]] = []

        class FakeModule:
            def __init__(self, report_type: str):
                self.report_type = report_type

            async def run_async(self, args):
                calls.append((self.report_type, args.ws_endpoint, getattr(args, "date", None)))
                return Path(f"{self.report_type}.xlsx")

        fake_connection = ProfileConnection(
            profile_name="XHS-小红书-MOCK旗舰店",
            profile_id="fixture-profile",
            endpoint="ws://127.0.0.1:45678/devtools/browser/fixture",
            started_by_this_run=False,
        )
        resolver_calls: list[dict[str, object]] = []

        def fake_resolver(**kwargs):
            resolver_calls.append(kwargs)
            return fake_connection

        args = SimpleNamespace(
            profile="XHS-小红书-MOCK旗舰店",
            report_type="全部",
            date="2026-09-09",
            output_dir="downloads",
            timeout=10.0,
            poll_interval=0.01,
            mcp_url=None,
            profile_timeout=1.0,
            profile_poll_interval=0.01,
        )
        with patch.object(unified_download, "order_download", FakeModule("order")), patch.object(
            unified_download, "fund_download", FakeModule("fund")
        ), patch.object(
            unified_download, "settlement_download", FakeModule("settlement")
        ):
            outputs = asyncio.run(
                unified_download.run_async(args, resolver=fake_resolver)
            )

        self.assertEqual(1, len(resolver_calls))
        self.assertEqual(
            [("order", fake_connection.endpoint, None),
             ("fund", fake_connection.endpoint, "2026-09-09"),
             ("settlement", fake_connection.endpoint, "2026-09-09")],
            calls,
        )
        self.assertEqual(3, len(outputs))

    def test_order_query_and_export_keep_business_payload_shapes(self):
        start = date(2026, 8, 12)
        end = date(2026, 9, 10)
        query = build_order_page_payload(start, end)
        self.assertEqual(3, query["time_range_list"][0]["time_type"])
        self.assertEqual(20, query["page_size"])
        self.assertEqual(1786464000000, query["time_range_list"][0]["start_time"])
        condition = build_export_condition(start, end)
        self.assertEqual("ordered", condition["time_range_list"][0]["timeType"])
        export = build_start_export_payload(start, end)
        decoded = json.loads(export["data_condition"])
        self.assertEqual(condition, decoded)
        self.assertEqual("OrderQueryPackageFileBuilder", export["source_data_bean"])

    def test_fund_selects_latest_successful_row_or_exact_day(self):
        rows = [
            {"periodType": "DAY", "startTime": "2026-09-08", "periodFundNo": "old", "processStatus": "SUCCESS"},
            {"periodType": "DAY", "startTime": "2026-09-09", "periodFundNo": "latest", "processStatus": "SUCCESS"},
            {"periodType": "DAY", "startTime": "2026-09-10", "periodFundNo": "running", "processStatus": "PROCESSING"},
        ]
        self.assertEqual("latest", select_fund_row(rows, "day", None)["periodFundNo"])
        self.assertEqual(
            "old",
            select_fund_row(rows, "day", date(2026, 9, 8))["periodFundNo"],
        )
        self.assertEqual(
            {"periodType": "DAY", "timeType": "COMPLETE_TIME", "pageNum": 1, "pageSize": 100},
            {
                key: value
                for key, value in build_fund_period_payload(
                    "day", "2026-09-01 00:00:00", "2026-09-10 00:00:00"
                ).items()
                if key in {"periodType", "timeType", "pageNum", "pageSize"}
            },
        )
        self.assertEqual(
            ("2026-09-09 00:00:00", "2026-09-10 00:00:00"),
            fund_query_range("day", date(2026, 9, 9)),
        )

    def test_settlement_month_matching_and_payload_time_type(self):
        rows = [
            {"periodType": "MONTH", "startTime": "2026-07-01", "periodSettleNo": "july", "processStatus": "SUCCESS"},
            {"periodType": "MONTH", "startTime": "2026-08-01", "periodSettleNo": "aug", "processStatus": "SUCCESS"},
        ]
        self.assertEqual(
            "aug",
            select_settlement_row(rows, "month", date(2026, 8, 1))["periodSettleNo"],
        )
        payload = build_settlement_period_payload(
            "month", "2026-08-01 00:00:00", "2026-09-01 00:00:00"
        )
        self.assertEqual("MONTH", payload["periodType"])
        self.assertEqual("SETTLE_TIME", payload["timeType"])
        self.assertEqual(
            ("2026-08-01 00:00:00", "2026-09-01 00:00:00"),
            settlement_query_range("month", date(2026, 8, 1)),
        )

    def test_shared_parsers_do_not_expose_signed_url_in_error_contract(self):
        self.assertEqual("2026-09-09", parse_period_key("2026-09-09 00:00:00"))
        self.assertEqual("2026-08-01", parse_period_key("2026/08/01"))
        self.assertEqual(
            "https://download.example/report.xlsx",
            extract_download_url(
                {"data": {"downloadUrl": "https://download.example/report.xlsx"}},
                label="fixture",
            ),
        )

    def test_period_pagination_over_safety_limit_is_not_truncated(self):
        class FakeApi:
            async def post_json(self, *args, **kwargs):
                return {
                    "success": True,
                    "code": 0,
                    "data": {"list": [], "totalPage": 21},
                }

        with self.assertRaisesRegex(ApiError, "超过安全上限"):
            asyncio.run(
                query_all_fund_rows(
                    FakeApi(),
                    "day",
                    "2026-09-01 00:00:00",
                    "2026-09-10 00:00:00",
                )
            )

    def test_dynamic_headers_are_bound_to_the_same_page_target(self):
        first_page = object()
        second_page = object()
        collector = NaturalRequestCollector()
        collector._records = [
            ObservedRequest(
                path="/api/fixture",
                page_url="https://ark.xiaohongshu.com/app-finance/bill/fund",
                page_key=id(first_page),
                headers={"authorization": "first"},
                observed_at=time.monotonic(),
            ),
            ObservedRequest(
                path="/api/fixture",
                page_url="https://ark.xiaohongshu.com/app-finance/bill/fund",
                page_key=id(second_page),
                headers={"authorization": "second"},
                observed_at=time.monotonic(),
            ),
        ]
        headers = collector.headers_for(
            "/api/fixture", "/app-finance/bill/fund", first_page
        )
        self.assertEqual("first", headers["authorization"])

    def test_unified_exit_codes_and_endpoint_compatibility(self):
        parser = unified_download.build_parser()
        args = parser.parse_args(
            [
                "--profile",
                "XHS-小红书-测试店",
                "--ws-endpoint",
                "ws://127.0.0.1:45678/devtools/browser/fixture",
            ]
        )
        self.assertEqual(45678, int(args.ws_endpoint.split(":")[2].split("/")[0]))

        cli = ["--profile", "XHS-小红书-测试店", "--report-type", "订单"]
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

    def test_401_retry_waits_for_fresh_context_once(self):
        class Collector:
            def __init__(self):
                self.calls = []

            async def wait_for_context(self, *args, **kwargs):
                self.calls.append(kwargs)
                return {"authorization": "fixture"}

        collector = Collector()
        refresh_count = 0
        responses = [
            ApiError("expired", status=401, path="/api/fixture"),
            {"success": True, "code": 0, "data": {}},
        ]

        async def refresh():
            nonlocal refresh_count
            refresh_count += 1

        async def post(*args, **kwargs):
            result = responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        api = BrowserApiSession(
            object(),
            collector,  # type: ignore[arg-type]
            page_route="/app-finance/bill/fund",
            refresh=refresh,
        )
        with patch.object(xhs_common, "browser_post_json", new=post):
            result = asyncio.run(
                api.post_json("/api/fixture", {}, label="fixture", timeout=1)
            )

        self.assertTrue(result["success"])
        self.assertEqual(1, refresh_count)
        self.assertEqual(2, len(collector.calls))
        self.assertGreater(collector.calls[1]["observed_after"], 0)

    def test_second_403_after_refresh_is_needs_human(self):
        class Collector:
            async def wait_for_context(self, *args, **kwargs):
                return {"authorization": "fixture"}

        async def refresh():
            return None

        async def denied(*args, **kwargs):
            raise ApiError("denied", status=403, path="/api/fixture")

        api = BrowserApiSession(
            object(),
            Collector(),  # type: ignore[arg-type]
            page_route="/app-finance/bill/fund",
            refresh=refresh,
        )
        with patch.object(xhs_common, "browser_post_json", new=denied):
            with self.assertRaises(NeedsHumanError):
                asyncio.run(
                    api.post_json("/api/fixture", {}, label="fixture", timeout=1)
                )


if __name__ == "__main__":
    unittest.main()
