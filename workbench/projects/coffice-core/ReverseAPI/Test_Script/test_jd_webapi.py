# -*- coding: utf-8 -*-
"""京东资金、结算、推广费 WebAPI 的纯契约测试。

测试只使用内存 fixture 和假的 HTTP/浏览器对象，不启动 Profile、不访问京东
页面，也不把真实 Cookie、签名头或短效下载地址写入 fixture。
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

from ReverseAPI.Formal_Script import jd_fund_webapi_download as fund
from ReverseAPI.Formal_Script import jd_promotion_fee_webapi_download as promotion
from ReverseAPI.Formal_Script import jd_settlement_webapi_download as settlement
from ReverseAPI.Formal_Script import jd_webapi_common as common
from ReverseAPI.Formal_Script import jd_webapi_download as unified
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


class JdWebApiCommonTests(unittest.TestCase):
    def test_dynamic_headers_exclude_short_lived_security_values(self) -> None:
        headers = common.dynamic_fetch_headers(
            {
                "h5st": "secret-fixture-value",
                "dsm-trace-id": "trace-fixture-value",
                "dsm-file-path": "lineation-price",
                "dsm-lang": "zh-CN",
                "loginMode": "0",
                "x-requested-with": "XMLHttpRequest",
                "Referer": "https://shop.jd.com/jdm/home",
            }
        )
        self.assertEqual("lineation-price", headers["dsm-file-path"])
        self.assertEqual("zh-CN", headers["dsm-lang"])
        self.assertEqual("0", headers["loginmode"])
        self.assertNotIn("h5st", headers)
        self.assertNotIn("dsm-trace-id", headers)
        self.assertNotIn("referer", headers)

    def test_download_is_atomic_unique_and_cleans_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            existing = output_dir / "JD_fund_2026-09-11_to_2026-09-11.csv"
            existing.write_bytes(b"old")
            session = FakeSession(FakeResponse([b"csv-data"]))
            with patch.object(common.requests, "Session", return_value=session):
                output = common.download_original_file(
                    "https://download.example/fund.csv?signature=fixture",
                    output_dir,
                    existing.name,
                )
            self.assertEqual(b"old", existing.read_bytes())
            self.assertEqual(b"csv-data", output.read_bytes())
            self.assertEqual("JD_fund_2026-09-11_to_2026-09-11_1.csv", output.name)
            self.assertFalse(Path(str(output) + ".part").exists())
            self.assertTrue(session.closed)

    def test_empty_and_403_downloads_leave_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            empty = FakeSession(FakeResponse([]))
            with patch.object(common.requests, "Session", return_value=empty):
                with self.assertRaisesRegex(RuntimeError, "下载为空"):
                    common.download_original_file(
                        "https://download.example/empty.zip",
                        output_dir,
                        "JD_settlement_2026-09-11_to_2026-09-11.zip",
                    )
            self.assertEqual([], list(output_dir.iterdir()))
            denied = FakeSession(FakeResponse([], 403))
            with patch.object(common.requests, "Session", return_value=denied):
                with self.assertRaises(common.NeedsHumanError):
                    common.download_original_file(
                        "https://download.example/denied.xls",
                        output_dir,
                        "JD_tong_promotion_fee_2026-09-01_to_2026-09-11.xls",
                    )

    def test_collector_is_bound_to_target_and_keeps_payload_template(self) -> None:
        first_page = object()
        second_page = object()
        collector = common.NaturalRequestCollector()
        collector._records = [
            common.ObservedRequest(
                host="sff.jd.com",
                path="/api",
                page_url="https://shop.jd.com/jdm/finance/billManage/foundFlow",
                page_key=id(first_page),
                headers={"dsm-file-path": "first"},
                post_data={"capitalFlowQueryMo": {"orgCode": "first-shop"}},
                observed_at=time.monotonic(),
                api_name="target-api",
            ),
            common.ObservedRequest(
                host="sff.jd.com",
                path="/api",
                page_url="https://shop.jd.com/jdm/finance/billManage/foundFlow",
                page_key=id(first_page),
                headers={"dsm-file-path": "wrong-api"},
                post_data={"capitalFlowQueryMo": {"orgCode": "wrong-api"}},
                observed_at=time.monotonic(),
                api_name="other-api",
            ),
            common.ObservedRequest(
                host="sff.jd.com",
                path="/api",
                page_url="https://shop.jd.com/jdm/finance/billManage/foundFlow",
                page_key=id(second_page),
                headers={"dsm-file-path": "second"},
                post_data={"capitalFlowQueryMo": {"orgCode": "second-shop"}},
                observed_at=time.monotonic(),
                api_name="target-api",
            ),
        ]
        headers = asyncio.run(
            collector.wait_for_context(
                "sff.jd.com",
                "/api",
                "/jdm/finance/billManage/foundFlow",
                first_page,
                api_name="target-api",
            )
        )
        payload = asyncio.run(
            collector.wait_for_payload(
                "sff.jd.com",
                "/api",
                "/jdm/finance/billManage/foundFlow",
                first_page,
                api_name="target-api",
            )
        )
        self.assertEqual("first", headers["dsm-file-path"])
        self.assertEqual("first-shop", payload["capitalFlowQueryMo"]["orgCode"])

    def test_401_retry_refreshes_context_once_and_second_403_needs_human(self) -> None:
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
            common.ApiError("expired", status=401, path="/api"),
            {"code": 200, "data": {}},
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
            page_route="/jdm/finance/billManage/foundFlow",
            refresh=refresh,
        )
        with patch.object(common, "browser_post_json", new=post):
            body = asyncio.run(
                api.post_json(
                    "https://sff.jd.com/api?fixture=1",
                    {},
                    label="fixture",
                    timeout=1,
                )
            )
        self.assertEqual(200, body["code"])
        self.assertEqual(1, refresh_count)
        self.assertEqual(2, len(collector.calls))
        self.assertGreater(collector.calls[1]["observed_after"], 0)

        async def denied(*args, **kwargs):
            raise common.ApiError("denied", status=403, path="/api")

        with patch.object(common, "browser_post_json", new=denied):
            with self.assertRaises(common.NeedsHumanError):
                asyncio.run(
                    api.post_json(
                        "https://sff.jd.com/api?fixture=1",
                        {},
                        label="fixture",
                        timeout=1,
                    )
                )


class JdPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = date(2026, 9, 11)
        self.end = date(2026, 9, 11)

    def test_fund_keeps_dynamic_org_code_and_exact_export_condition(self) -> None:
        template = {
            "capitalFlowQueryMo": {
                "pageNo": 1,
                "pageSize": 10,
                "orgCode": "fixture-shop-code",
                "outTradeNo": None,
                "tradeNo": None,
            },
            "accessContext": {"source": "web"},
        }
        query = fund.build_query_payload(template, self.start, self.end)
        create = fund.build_create_payload(query, self.start, self.end)
        condition = json.loads(create["request"]["data"]["conditionBody"])
        self.assertEqual("fixture-shop-code", condition["orgCode"])
        self.assertEqual("13", condition["exportType"])
        self.assertEqual("2026-09-11 00:00:00", condition["startTime"])
        self.assertEqual(
            ["2026-09-10T16:00:00.000Z", "2026-09-11T15:59:59.999Z"],
            condition["beginEndDate"],
        )
        self.assertEqual(13, create["request"]["data"]["taskType"])

    def test_fund_task_matching_is_exact(self) -> None:
        rows = [
            {"id": "other", "taskType": 13, "conditionBody": "fixture"},
            {"id": "wanted", "taskType": 13, "conditionBody": "fixture"},
        ]
        self.assertEqual(
            "wanted",
            fund.select_task(rows, task_id="wanted", condition_body="fixture")["id"],
        )

    def test_settlement_selects_exact_business_day_or_latest(self) -> None:
        rows = [
            {"id": 1, "accDate": "20260909"},
            {"id": 2, "accDate": "20260911"},
            {"id": 3, "accDate": "20260910"},
        ]
        self.assertEqual(2, settlement.select_settlement_row(rows, self.start)["id"])
        self.assertEqual(2, settlement.select_settlement_row(rows, None)["id"])
        payload = settlement.build_detail_payload(
            {"daybillMo": {"secAccountNo": "fixture"}},
            2,
            date(2026, 9, 9),
            date(2026, 9, 12),
        )
        self.assertEqual([2], payload["daybillMo"]["ids"])
        self.assertEqual("fixture", payload["daybillMo"]["secAccountNo"])

    def test_promotion_payloads_and_precise_task_matching(self) -> None:
        union_template = {
            "dateType": 1,
            "billStatus": 2,
            "withDailyData": 0,
        }
        union_query = promotion.build_union_query_payload(
            union_template, date(2026, 8, 14), self.end
        )
        self.assertEqual(2, union_query["dateType"])
        self.assertEqual("2026-09-11", union_query["endDateForSubmit"])
        self.assertEqual(
            "结算信息",
            promotion.build_union_generate_payload(
                date(2026, 8, 14), self.end
            )["reportName"],
        )
        now_ms = int(time.time() * 1000)
        union_row = {
            "pk": 123,
            "reportName": "结算信息",
            "moduleType": 2,
            "generateStatus": 2,
            "insertTime": now_ms,
        }
        self.assertIsNotNone(
            promotion.select_union_task([union_row], submitted_after_ms=now_ms)
        )

        tong_query = promotion.build_tong_query_payload(
            {"orderTypes": [2201], "timeFilterType": 0},
            date(2026, 8, 14), self.end,
        )
        self.assertEqual(1, tong_query["timeFilterType"])
        self.assertEqual("2026-08-14", tong_query["beginDate"])
        self.assertEqual(
            promotion.TONG_REPORT_NAME,
            promotion.build_tong_export_payload(tong_query)["downloadName"],
        )
        tong_row = {
            "reportName": promotion.TONG_REPORT_NAME,
            "type": 24,
            "startDay": "2026-08-14",
            "endDay": "2026-09-11",
            "createdTime": "2026-09-12 00:20:00",
            "status": 2,
            "downloadUrl": "https://download.example/tong.xls?fixture=1",
        }
        self.assertEqual(
            tong_row,
            promotion.select_tong_report(
                [tong_row],
                start=date(2026, 8, 14),
                end=self.end,
                submitted_after_ms=int(
                    date(2026, 9, 12).strftime("%s") if False else 1789143600000
                ),
            ),
        )


class JdUnifiedTests(unittest.TestCase):
    def test_plans_are_chinese_and_serial(self) -> None:
        plans = unified.build_download_plans(
            None,
            None,
            today=date(2026, 9, 12),
        )
        self.assertEqual([unified.FUND, unified.SETTLEMENT, unified.PROMOTION], [p.report_type for p in plans])
        self.assertEqual("2026-09-11", plans[0].date_text)
        self.assertIsNone(plans[1].date_text)
        self.assertIsNone(plans[2].date_text)
        self.assertEqual((unified.FUND,), unified.normalize_report_type("资金"))
        with self.assertRaisesRegex(ValueError, "不支持"):
            unified.normalize_report_type("fund")

    def test_unified_resolves_once_and_reuses_same_endpoint_serially(self) -> None:
        calls: list[tuple[str, str]] = []
        connection = ProfileConnection(
            profile_name="JD-京东-MOCK饮品旗舰店",
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

        async def fake_promotion(args, endpoint):
            calls.append(("推广费", endpoint))
            return [Path("union.xlsx"), Path("tong.xls")]

        args = SimpleNamespace(
            profile="JD-京东-MOCK饮品旗舰店",
            report_type="全部",
            date="2026-09-11",
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
        ), patch.object(
            promotion, "run_all_with_endpoint", new=fake_promotion
        ):
            outputs = asyncio.run(unified.run_async(args, resolver=resolver))
        self.assertEqual(1, len(resolver_calls))
        self.assertEqual(
            [
                ("资金", connection.endpoint),
                ("结算", connection.endpoint),
                ("推广费", connection.endpoint),
            ],
            calls,
        )
        self.assertEqual(4, len(outputs))

    def test_exit_codes_keep_needs_human_and_interrupt_distinct(self) -> None:
        cli = ["--profile", "JD-京东-MOCK饮品旗舰店", "--report-type", "资金"]
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
