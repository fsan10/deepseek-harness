# -*- coding: utf-8 -*-
"""快手资金、结算单 WebAPI 的纯契约测试。

测试只使用内存 fixture 和假的 HTTP/浏览器对象，不启动 Profile、不访问
快手页面，也不保存真实 Cookie、动态头或短效下载地址。
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from ReverseAPI.Formal_Script import kuaishou_fund_webapi_download as fund
from ReverseAPI.Formal_Script import kuaishou_settlement_webapi_download as settlement
from ReverseAPI.Formal_Script import kuaishou_webapi_common as common
from ReverseAPI.Formal_Script import kuaishou_webapi_download as unified
from ReverseAPI.Formal_Script.profile_cdp import ProfileConnection


class FakeResponse:
    def __init__(self, chunks: list[bytes], status_code: int = 200) -> None:
        self.chunks = chunks
        self.status_code = status_code

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield from self.chunks


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.closed = False
        self.cookies = SimpleNamespace(set=lambda *args, **kwargs: None)

    def get(self, *args: object, **kwargs: object) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


class KuaishouCommonTests(unittest.TestCase):
    def test_dynamic_headers_exclude_short_lived_values(self) -> None:
        headers = common.dynamic_fetch_headers(
            {
                "kpf": "PC_WEB",
                "kpn": "KWAIXIAODIAN",
                "ktrace-str": "short-lived-fixture",
                "merchantSessionKey": "session-fixture",
                "Trace-Id": "trace-fixture",
                "Cookie": "cookie-fixture",
                "Referer": "https://s.kwaixiaodian.com/zone/fund/accounting/account-bill",
            }
        )
        self.assertEqual("PC_WEB", headers["kpf"])
        self.assertEqual("KWAIXIAODIAN", headers["kpn"])
        self.assertNotIn("ktrace-str", headers)
        self.assertNotIn("merchantsessionkey", headers)
        self.assertNotIn("trace-id", headers)
        self.assertNotIn("cookie", headers)
        self.assertNotIn("referer", headers)

    def test_result_one_is_success_and_non_one_is_business_error(self) -> None:
        common.ensure_api_success({"result": 1, "code": "", "error_msg": "成功"}, label="fixture")
        with self.assertRaisesRegex(common.ApiError, "6个月"):
            common.ensure_api_success(
                {"result": 21010, "error_msg": "当前只支持6个月范围查询，请重新筛选时间"},
                label="fixture",
            )
        with self.assertRaises(common.NeedsHumanError):
            common.ensure_api_success(
                {"result": 1001, "error_msg": "请完成安全验证"},
                label="fixture",
            )

    def test_download_is_atomic_unique_and_cleans_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            existing = output_dir / "KS_fund_day_2026-09-11.csv"
            existing.write_bytes(b"old")
            session = FakeSession(FakeResponse([b"csv-fixture"]))
            with patch.object(common.requests, "Session", return_value=session):
                output = common.download_original_file(
                    "https://s.kwaixiaodian.com/fixture/fund.csv",
                    output_dir,
                    existing.name,
                )
            self.assertEqual(b"old", existing.read_bytes())
            self.assertEqual(b"csv-fixture", output.read_bytes())
            self.assertEqual("KS_fund_day_2026-09-11_1.csv", output.name)
            self.assertFalse(Path(str(output) + ".part").exists())
            self.assertTrue(session.closed)

    def test_403_download_requires_human_and_leaves_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = FakeSession(FakeResponse([], 403))
            with patch.object(common.requests, "Session", return_value=session):
                with self.assertRaises(common.NeedsHumanError):
                    common.download_original_file(
                        "https://s.kwaixiaodian.com/fixture/denied.zip",
                        Path(directory),
                        "KS_settlement_fixture.zip",
                    )
            self.assertEqual([], list(Path(directory).iterdir()))

    def test_collector_is_bound_to_target_and_exact_endpoint(self) -> None:
        first_page = object()
        second_page = object()
        collector = common.NaturalRequestCollector()
        now = time.monotonic()
        collector._records = [
            common.ObservedRequest(
                host="s.kwaixiaodian.com",
                path=fund.STATISTIC_PATH,
                page_url="https://s.kwaixiaodian.com/zone/fund/accounting/account-bill",
                page_key=id(first_page),
                headers={"kpf": "first"},
                post_data={"subMchId": "first-account"},
                observed_at=now,
            ),
            common.ObservedRequest(
                host="s.kwaixiaodian.com",
                path=settlement.QUERY_PATH,
                page_url="https://s.kwaixiaodian.com/zone/fund/accounting/payment-bill",
                page_key=id(first_page),
                headers={"kpf": "wrong-report"},
                post_data={"accountChannel": ["wrong"]},
                observed_at=now,
            ),
            common.ObservedRequest(
                host="s.kwaixiaodian.com",
                path=fund.STATISTIC_PATH,
                page_url="https://s.kwaixiaodian.com/zone/fund/accounting/account-bill",
                page_key=id(second_page),
                headers={"kpf": "second"},
                post_data={"subMchId": "second-account"},
                observed_at=now,
            ),
        ]
        headers = asyncio.run(
            collector.wait_for_context(
                "s.kwaixiaodian.com",
                fund.STATISTIC_PATH,
                fund.FUND_PAGE_ROUTE,
                first_page,
            )
        )
        payload = asyncio.run(
            collector.wait_for_payload(
                "s.kwaixiaodian.com",
                fund.STATISTIC_PATH,
                fund.FUND_PAGE_ROUTE,
                first_page,
            )
        )
        self.assertEqual("first", headers["kpf"])
        self.assertEqual("first-account", payload["subMchId"])

    def test_401_refreshes_context_once_and_second_403_needs_human(self) -> None:
        class Collector:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            async def wait_for_context(self, *args, **kwargs):
                self.calls.append(kwargs)
                return {"content-type": "application/json"}

            def target_for(self, *args, **kwargs):
                return None

        collector = Collector()
        refresh_count = 0
        responses: list[object] = [
            common.ApiError("expired", status=401, path="/fixture"),
            {"result": 1, "data": {}},
        ]

        async def refresh() -> None:
            nonlocal refresh_count
            refresh_count += 1

        async def post(*args, **kwargs):
            result = responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        api = common.BrowserApiSession(
            object(),
            collector,  # type: ignore[arg-type]
            page_route=fund.FUND_PAGE_ROUTE,
            refresh=refresh,
        )
        with patch.object(common, "browser_post_json", new=post):
            body = asyncio.run(
                api.post_json(
                    "https://s.kwaixiaodian.com/fixture",
                    {},
                    label="fixture",
                    timeout=1,
                )
            )
        self.assertEqual({}, body["data"])
        self.assertEqual(1, refresh_count)
        self.assertEqual(2, len(collector.calls))

        async def denied(*args, **kwargs):
            raise common.ApiError("denied", status=403, path="/fixture")

        with patch.object(common, "browser_post_json", new=denied):
            with self.assertRaises(common.NeedsHumanError):
                asyncio.run(
                    api.post_json(
                        "https://s.kwaixiaodian.com/fixture",
                        {},
                        label="fixture",
                        timeout=1,
                    )
                )


class KuaishouFundTests(unittest.TestCase):
    def test_day_and_month_windows_match_service_limits(self) -> None:
        self.assertEqual(
            (date(2026, 8, 12), date(2026, 9, 11)),
            fund.fund_query_window("day", date(2026, 9, 11)),
        )
        self.assertEqual(
            (date(2026, 3, 1), date(2026, 8, 31)),
            fund.fund_query_window("month", date(2026, 8, 1)),
        )

    def test_statistic_and_create_payloads_keep_exact_period(self) -> None:
        template = {"billType": "BY_DAY", "requestContext": "fixture"}
        query = fund.build_statistic_payload(
            template,
            "day",
            date(2026, 8, 12),
            date(2026, 9, 11),
            "fixture-sub-mch",
        )
        self.assertEqual("BY_DAY", query["billType"])
        self.assertEqual("fixture-sub-mch", query["subMchId"])
        self.assertEqual("fixture", query["requestContext"])
        create = fund.build_create_task_payload(
            {"subMchId": "fixture-sub-mch"},
            "fixture-operator",
            date(2026, 9, 11),
            date(2026, 9, 11),
            "day",
        )
        config = json.loads(create["exportConfig"])
        self.assertEqual("20260911", fund.fund_period_key(date(2026, 9, 11), "day"))
        self.assertEqual(1, config["dateType"])
        self.assertEqual("fixture-sub-mch", config["subMchId"])
        month_create = fund.build_create_task_payload(
            {"subMchId": "fixture-sub-mch"},
            "fixture-operator",
            date(2026, 8, 1),
            date(2026, 8, 31),
            "month",
        )
        self.assertEqual(2, json.loads(month_create["exportConfig"])["dateType"])

    def test_account_and_row_selection_never_silently_chooses_multiple_accounts(self) -> None:
        accounts = [
            {"subMchId": "fixture-a", "bindState": "ENABLE", "accountState": "NORMAL"},
            {"subMchId": "fixture-b", "bindState": "DISABLE", "accountState": "NORMAL"},
        ]
        self.assertEqual("fixture-a", fund.select_account(accounts)["subMchId"])
        self.assertEqual("fixture-b", fund.select_account(accounts, "fixture-b")["subMchId"])
        with self.assertRaisesRegex(common.ApiError, "不存在"):
            fund.select_account(accounts, "fixture-missing")
        rows = [{"date": "202608"}, {"date": "202607"}]
        self.assertEqual("202608", fund.select_fund_row(rows, "month", None)["date"])
        self.assertIsNone(fund.select_fund_row(rows, "month", date(2026, 9, 1)))

    def test_task_matching_is_exact_and_ignores_old_or_pending_records(self) -> None:
        now_ms = int(time.time() * 1000)
        records = [
            {
                "taskKind": fund.TASK_KIND,
                "status": 2,
                "createTime": now_ms - 600_000,
                "exportConfig": json.dumps({"startTime": "20260911", "endTime": "20260911"}),
            },
            {
                "taskKind": fund.TASK_KIND,
                "status": 1,
                "createTime": now_ms,
                "exportConfig": json.dumps({"startTime": "20260911", "endTime": "20260911"}),
            },
            {
                "taskKind": fund.TASK_KIND,
                "status": 2,
                "createTime": now_ms,
                "exportConfig": json.dumps({"startTime": "202608", "endTime": "202608"}),
            },
        ]
        self.assertIsNone(
            fund.select_fund_task(records, "20260911", submitted_after_ms=now_ms - 1_000)
        )
        records[1]["status"] = 2
        self.assertEqual(
            2,
            fund.select_fund_task(records, "20260911", submitted_after_ms=now_ms - 1_000)["status"],
        )


class KuaishouSettlementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = date(2026, 8, 1)
        self.end = date(2026, 8, 31)

    def test_query_bounds_and_no_record_short_circuit_shape(self) -> None:
        payload = settlement.build_query_payload(
            {"settlementStatus": ["OTHER"], "accountChannel": ["OTHER"]},
            self.start,
            self.end,
        )
        self.assertEqual(1785513600000, payload["settlementTimeGte"])
        self.assertEqual(1788191999000, payload["settlementTimeLte"])
        self.assertEqual(list(settlement.CHANNELS), payload["accountChannel"])
        self.assertFalse(
            settlement.has_settlement_rows(
                {"result": 1, "data": {"total": 0, "orders": []}}
            )
        )

    def test_create_payload_and_task_selection_match_exact_ext_param(self) -> None:
        query = settlement.build_query_payload({}, self.start, self.end)
        create = settlement.build_create_payload(query)
        ext = json.loads(create["extParams"])
        self.assertEqual(1785513600000, ext["settlementTimeGte"])
        self.assertEqual(",".join(settlement.CHANNELS), ext["accountChannel"])
        now_ms = int(time.time() * 1000)
        items = [
            {
                "bizSubType": settlement.SETTLEMENT_TYPE,
                "status": 30,
                "createTime": now_ms - 600_000,
                "id": "fixture-old",
                "extParam": json.dumps(ext),
            },
            {
                "bizSubType": settlement.SETTLEMENT_TYPE,
                "status": 30,
                "createTime": now_ms,
                "id": "fixture-current",
                "extParam": json.dumps(ext),
            },
            {
                "bizSubType": "OTHER_TYPE",
                "status": 30,
                "createTime": now_ms,
                "id": "fixture-wrong",
                "extParam": json.dumps(ext),
            },
        ]
        selected = settlement.select_settlement_task(
            items,
            query,
            submitted_after_ms=now_ms - 1_000,
        )
        self.assertEqual("fixture-current", selected["id"])

    def test_download_url_requires_numeric_file_id(self) -> None:
        self.assertIn("fileId=123", settlement.build_download_url("123"))
        with self.assertRaises(common.ApiError):
            settlement.build_download_url("fixture-signed-id")


class KuaishouUnifiedTests(unittest.TestCase):
    def test_plans_are_chinese_and_month_is_explicit(self) -> None:
        plans = unified.build_download_plans(
            "资金",
            "2026-08",
            mode="month",
            today=date(2026, 9, 12),
        )
        self.assertEqual([(unified.FUND, "2026-08", "month")], [(p.report_type, p.date_text, p.mode) for p in plans])
        plans = unified.build_download_plans(
            None,
            None,
            today=date(2026, 9, 12),
        )
        self.assertEqual([unified.FUND, unified.SETTLEMENT], [p.report_type for p in plans])
        self.assertEqual("2026-09-11", plans[0].date_text)
        with self.assertRaisesRegex(ValueError, "不支持"):
            unified.normalize_report_type("fund")
        with self.assertRaisesRegex(ValueError, "结算单"):
            unified.build_download_plans("结算", "2026-08", mode="month")

    def test_unified_resolves_once_and_runs_serially(self) -> None:
        calls: list[tuple[str, str]] = []
        connection = ProfileConnection(
            profile_name="KS-fixture-profile",
            profile_id="fixture-profile",
            endpoint="ws://127.0.0.1:45678/devtools/browser/fixture",
            started_by_this_run=False,
        )
        resolver_calls: list[dict[str, object]] = []

        def resolver(**kwargs):
            resolver_calls.append(kwargs)
            return connection

        async def fake_fund(args, endpoint):
            calls.append(("资金", endpoint))
            return Path("fund.csv")

        async def fake_settlement(args, endpoint):
            calls.append(("结算", endpoint))
            return Path("settlement.zip")

        args = SimpleNamespace(
            profile="KS-fixture-profile",
            report_type="全部",
            date="2026-09-11",
            mode="day",
            sub_mch_id=None,
            output_dir="downloads",
            timeout=1.0,
            poll_interval=0.01,
            mcp_url=None,
            ws_endpoint=None,
            debug_port=None,
            profile_timeout=1.0,
            profile_poll_interval=0.01,
        )
        with patch.object(fund, "run_with_endpoint", new=fake_fund), patch.object(
            settlement, "run_with_endpoint", new=fake_settlement
        ):
            outputs = asyncio.run(unified.run_async(args, resolver=resolver))
        self.assertEqual(1, len(resolver_calls))
        self.assertEqual(
            [("资金", connection.endpoint), ("结算", connection.endpoint)],
            calls,
        )
        self.assertEqual(2, len(outputs))

    def test_exit_codes_keep_needs_human_and_interrupt_distinct(self) -> None:
        cli = ["--profile", "KS-fixture-profile", "--report-type", "资金"]
        with patch.object(
            unified,
            "run_async",
            new=AsyncMock(side_effect=common.NeedsHumanError("fixture")),
        ):
            self.assertEqual(2, unified.main(cli))
        with patch.object(
            unified,
            "run_async",
            new=AsyncMock(side_effect=KeyboardInterrupt()),
        ):
            self.assertEqual(130, unified.main(cli))


if __name__ == "__main__":
    unittest.main()
