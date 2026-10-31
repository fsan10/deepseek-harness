from __future__ import annotations

import asyncio
import hashlib
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock, patch

from ReverseAPI.Formal_Script import tmall_webapi_download as unified
from ReverseAPI.Formal_Script import tmall_fund_webapi_download as fund
from ReverseAPI.Formal_Script import tmall_order_webapi_download as order
from ReverseAPI.Formal_Script import tmall_promotion_webapi_download as promotion
from ReverseAPI.Formal_Script.tmall_webapi_common import (
    ApiError,
    NeedsHumanError,
    build_mtop_url,
    parse_json_or_jsonp,
)
from ReverseAPI.Formal_Script.profile_cdp import ProfileConnection


class TmallWebApiTests(unittest.TestCase):
    def test_wanxiangtai_uses_booking_time_for_requested_date(self) -> None:
        target = "2026-10-07"
        params = promotion._wanxiang_params("https://example.invalid/list?timeType=trans", target)
        self.assertEqual("acount", params["timeType"])
        self.assertEqual(target, params["beginTime"])
        self.assertEqual(target, params["endTime"])
        query = parse_qs(urlsplit(promotion._wanxiang_target_url(target)).fragment.split("?", 1)[1])
        self.assertEqual(["acount"], query["time"])

    def test_mtop_sign_is_generated_from_runtime_cookie_and_data(self) -> None:
        cookies = [{"name": "_m_h5_tk", "value": "runtime-token_ignored"}]
        url = build_mtop_url(
            "https://h5api.m.taobao.com/h5/demo/1.0/?api=demo&appKey=12574478",
            {"page": 1},
            cookies,
            timestamp_ms=123,
            callback="mtopjsonp1",
        )
        self.assertIn("data=%7B%22page%22%3A1%7D", url)
        expected = hashlib.md5(b"runtime-token&123&12574478&{\"page\":1}").hexdigest()
        self.assertIn(f"sign={expected}", url)

    def test_jsonp_and_human_response_contracts(self) -> None:
        body = parse_json_or_jsonp(' mtopjsonp1({"ret":["SUCCESS::调用成功"],"data":{}})')
        self.assertEqual(["SUCCESS::调用成功"], body["ret"])
        with self.assertRaises(NeedsHumanError):
            from ReverseAPI.Formal_Script.tmall_webapi_common import ensure_api_success

            ensure_api_success({"ret": ["FAIL_SYS_SESSION_EXPIRED::请先登录"]}, label="fixture")

    def test_order_query_count_and_ready_record(self) -> None:
        self.assertEqual(3, order.order_count({"page": {"totalNumber": 3}}))
        self.assertEqual(0, order.order_count({"page": {"totalNumber": 0}, "mainOrders": []}))
        record = {
            "startTimeStr": "2026-09-01 00:00:00",
            "endTimeStr": "2026-09-10 23:59:59",
            "exportStatus": "exportSuccess",
            "orderEncrypterStr": "oss/tradeorderexport/orderExportData/demo-orders",
            "exportId": "123",
            "applyTime": "2026-09-11 10:00:00",
            "orderStatus": "全部",
        }
        body = {"data": {"detailList": [record]}}
        self.assertIs(order.ready_export_record(body, "2026-09-01", "2026-09-10"), record)
        self.assertIn("export_by_tfs.do", order.export_download_url(record))
        self.assertTrue(
            order.history_row_matches(
                "报表申请时间：2026-09-11 10:00:00\n"
                "报表类型：订单报表\n"
                "创建时间：2026-09-01 00:00:00 到 2026-09-10 23:59:59\n"
                "下载订单报表",
                "2026-09-01",
                "2026-09-10",
                "2026-09-11 10:00:00",
            )
        )
        self.assertFalse(
            order.history_row_matches(
                "报表申请时间：2026-09-11 10:00:00\n报表类型：宝贝销售明细报表",
                "2026-09-01",
                "2026-09-10",
                "2026-09-11 10:00:00",
            )
        )
        pending = dict(record)
        pending.update({"exportType": "1", "exportStatus": "exporting", "orderEncrypterStr": ""})
        pending_body = {"data": {"detailList": [pending]}}
        self.assertIs(
            order.matching_export_record(pending_body, "2026-09-01", "2026-09-10"),
            pending,
        )
        self.assertIsNone(order.ready_export_record(pending_body, "2026-09-01", "2026-09-10"))

    def test_union_record_filters_date_and_status(self) -> None:
        body = {
            "data": {
                "result": [
                    {
                        "id": 1,
                        "bizType": 96,
                        "status": 0,
                        "fileName": "2026-09-10 00:00:00~2026-09-10 23:59:59-demo",
                    },
                    {
                        "id": 2,
                        "bizType": 96,
                        "status": 1,
                        "fileName": "2026-09-10 00:00:00~2026-09-10 23:59:59-demo",
                    },
                ]
            }
        }
        self.assertEqual(2, promotion.union_record(body, "2026-09-10")["id"])
        self.assertIsNone(promotion.union_record({"data": {"result": []}}, "2026-09-10"))

    def test_fund_success_and_empty_row(self) -> None:
        body = {
            "status": "succeed",
            "success": "true",
            "result": {"dateDtls": [{"bizDate": "2026-09-10", "downloadable": True}]},
        }
        self.assertEqual(body, fund._alipay_success(body))
        with self.assertRaises(ApiError):
            fund._alipay_success({"status": "failed", "success": "false"})

    def test_unified_default_plan_routes_two_profiles_serially(self) -> None:
        connection_regular = ProfileConnection(
            profile_name=unified.REGULAR_PROFILE,
            profile_id="regular",
            endpoint="ws://127.0.0.1:45678/devtools/browser/regular",
            started_by_this_run=False,
        )
        connection_finance = ProfileConnection(
            profile_name=unified.FINANCE_PROFILE,
            profile_id="finance",
            endpoint="ws://127.0.0.1:45679/devtools/browser/finance",
            started_by_this_run=False,
        )
        resolver_calls: list[str] = []
        call_order: list[str] = []

        def resolver(**kwargs):
            resolver_calls.append(kwargs["profile_name"])
            return connection_regular if kwargs["profile_name"] == unified.REGULAR_PROFILE else connection_finance

        async def fake_order(endpoint: str, **kwargs):
            call_order.append(f"order:{endpoint}")
            return Path("order.xlsx")

        async def fake_fund(endpoint: str, **kwargs):
            call_order.append(f"fund:{kwargs['kind']}:{endpoint}")
            return Path(f"{kwargs['kind']}.xlsx")

        async def fake_promotion(endpoint: str, **kwargs):
            call_order.append(f"promotion:{kwargs['kind']}:{endpoint}")
            return Path(f"{kwargs['kind']}.csv")

        args = unified.parse_args(["--report-type", "全部", "--date", "2026-09-10"])
        with patch.object(order_download := unified.order_download, "run_with_endpoint", new=fake_order), patch.object(
            unified.fund_download, "run_with_endpoint", new=fake_fund
        ), patch.object(unified.promotion_download, "run_with_endpoint", new=fake_promotion):
            outputs = asyncio.run(unified.run_async(args, resolver=resolver))

        self.assertEqual([unified.REGULAR_PROFILE, unified.FINANCE_PROFILE], resolver_calls)
        self.assertEqual(5, len(outputs))
        self.assertEqual(5, len(call_order))
        self.assertTrue(call_order[0].startswith("order:"))
        self.assertEqual(2, call_order.count(f"fund:聚合账户资金:{connection_regular.endpoint}") + call_order.count(f"fund:支付宝账户资金:{connection_finance.endpoint}"))

    def test_unified_exit_code_for_human_gate(self) -> None:
        with patch.object(
            unified,
            "run_async",
            new=AsyncMock(side_effect=NeedsHumanError("fixture")),
        ):
            self.assertEqual(2, unified.main(["--report-type", "订单"]))


if __name__ == "__main__":
    unittest.main()
