# -*- coding: utf-8 -*-
"""抖音资金/结算 WebAPI 的离线契约测试。"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from ReverseAPI.Formal_Script import douyin_fund_webapi_download as fund_download
from ReverseAPI.Formal_Script import douyin_settlement_webapi_download as settlement_download
from ReverseAPI.Formal_Script import douyin_webapi_common as common
from ReverseAPI.Formal_Script import douyin_webapi_download as unified_download
from ReverseAPI.Formal_Script.profile_cdp import ProfileConnection


CN_TZ = timezone(timedelta(hours=8))


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

    def get(self, *args: object, **kwargs: object) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


def history_row(
    *,
    status: str = "SUCCESS",
    download_id: str = "DL-fixture",
    create_time: str = "2026-09-11 11:00:00",
    start_time: str = "2026-09-10 00:00:00",
    end_time: str = "2026-09-10 23:59:59",
    download_type: str = "CHARGE_BILL_ITEM",
    time_type: str = "BILL_TIME",
    shop_id: str = "289407271",
) -> dict[str, str]:
    return {
        "status": status,
        "download_id": download_id,
        "create_time": create_time,
        "start_time": start_time,
        "end_time": end_time,
        "download_type": download_type,
        "time_type": time_type,
        "shop_id": shop_id,
    }


class DouyinWebApiTests(unittest.TestCase):
    def test_fund_payload_matches_captured_interface(self) -> None:
        query = fund_download.build_query_payload(
            "2026-09-10 00:00:00", "2026-09-10 23:59:59"
        )
        self.assertEqual(
            {
                "start_time": "2026-09-10 00:00:00",
                "end_time": "2026-09-10 23:59:59",
                "page": 0,
                "size": 50,
                "account_type": "",
                "request_type": 1,
                "query_type": "CHARGE_BILL",
            },
            query,
        )
        self.assertEqual(
            {
                "start_time": "2026-09-10 00:00:00",
                "end_time": "2026-09-10 23:59:59",
                "download_type": "CHARGE_BILL_ITEM",
                "time_type": "BILL_TIME",
                "account_type": "",
            },
            fund_download.build_export_payload(
                "2026-09-10 00:00:00", "2026-09-10 23:59:59"
            ),
        )

    def test_settlement_payload_matches_captured_interface(self) -> None:
        self.assertEqual(
            {
                "start_time": "2026-09-10 00:00:00",
                "end_time": "2026-09-10 23:59:59",
                "request_type": 1,
                "page": 0,
                "size": 50,
                "query_type": "SHOP_SETTLE_BILLS",
            },
            settlement_download.build_query_payload(
                "2026-09-10 00:00:00", "2026-09-10 23:59:59"
            ),
        )
        self.assertEqual(
            {
                "start_time": "2026-09-10 00:00:00",
                "end_time": "2026-09-10 23:59:59",
                "download_type": "SHOP_SETTLE_ORDERS",
                "time_type": "SETTLE",
            },
            settlement_download.build_export_payload(
                "2026-09-10 00:00:00", "2026-09-10 23:59:59"
            ),
        )

    def test_date_and_report_plans_use_cn_yesterday_and_serial_order(self) -> None:
        plans = unified_download.build_download_plans(
            None, None, today=date(2026, 9, 11)
        )
        self.assertEqual(
            [unified_download.FUND, unified_download.SETTLEMENT],
            [plan.report_type for plan in plans],
        )
        self.assertEqual((date(2026, 9, 10), date(2026, 9, 10)), (plans[0].start, plans[0].end))
        self.assertIn("默认昨天", plans[0].period_text)

        selected = unified_download.build_download_plans(
            "结算", "2026-09-01~2026-09-06"
        )
        self.assertEqual(1, len(selected))
        self.assertEqual((date(2026, 9, 1), date(2026, 9, 6)), (selected[0].start, selected[0].end))
        self.assertEqual((date(2026, 9, 1), date(2026, 9, 6)), common.parse_date_range("2026/09/01 至 2026/09/06"))
        with self.assertRaisesRegex(ValueError, "不能晚于"):
            common.parse_date_range("2026-09-06~2026-09-01")

    def test_response_and_shop_parsers_are_strict(self) -> None:
        body = {
            "code": "100000",
            "data": ['{"bill_date":"2026-09-10"}'],
            "total": 1,
        }
        self.assertEqual([{"bill_date": "2026-09-10"}], common.parse_data_rows(body, label="fixture"))
        self.assertEqual(1, common.read_total(body, label="fixture"))
        self.assertEqual("289407271", common.extract_shop_id({"code": 0, "data": {"SettleDayCategoryConfigInfoList": [{"ShopID": 289407271}]}}))
        self.assertEqual("DL-fixture", common.extract_download_id({"code": "100000", "download_id": "DL-fixture"}, label="fixture"))
        self.assertEqual("https://download.example/fixture.csv", common.extract_signed_url({"data": {"url": "https://download.example/fixture.csv"}}, label="fixture"))
        with self.assertRaises(common.ApiError):
            common.parse_data_rows({"code": "100000", "data": ["not-json"]}, label="fixture")
        with self.assertRaises(common.ApiError):
            common.ensure_success({"code": "500000", "msg": "failed"}, label="fixture", path="/fixture", expected_codes={"100000"})
        with self.assertRaises(common.NeedsHumanError):
            common.ensure_success({"code": "401", "msg": "请先登录"}, label="fixture", path="/fixture", expected_codes={"100000"})

    def test_history_matching_rejects_old_wrong_and_failed_tasks(self) -> None:
        created_after = datetime(2026, 9, 11, 10, 59, 55, tzinfo=CN_TZ)
        self.assertTrue(
            common.history_record_matches(
                history_row(),
                start_time="2026-09-10 00:00:00",
                end_time="2026-09-10 23:59:59",
                download_type="CHARGE_BILL_ITEM",
                time_type="BILL_TIME",
                download_id="DL-fixture",
                shop_id="289407271",
                created_after=created_after,
                status={"SUCCESS"},
            )
        )
        for row in (
            history_row(create_time="2026-09-11 10:00:00"),
            history_row(download_id="DL-old"),
            history_row(download_type="SHOP_SETTLE_ORDERS"),
            history_row(status="FAIL"),
            history_row(shop_id="other-shop"),
        ):
            self.assertFalse(
                common.history_record_matches(
                    row,
                    start_time="2026-09-10 00:00:00",
                    end_time="2026-09-10 23:59:59",
                    download_type="CHARGE_BILL_ITEM",
                    time_type="BILL_TIME",
                    download_id="DL-fixture",
                    shop_id="289407271",
                    created_after=created_after,
                    status={"SUCCESS"},
                )
            )

    def test_history_polling_waits_for_success_without_logging_task_id(self) -> None:
        pending = history_row(status="PROCESSING")
        success = history_row(status="SUCCESS")

        class FakeApi:
            def __init__(self) -> None:
                self.calls = 0

            async def get_json(self, *args: object, **kwargs: object) -> dict[str, object]:
                self.calls += 1
                return {
                    "code": 0,
                    "data": [pending if self.calls == 1 else success],
                    "total": 1,
                    "size": 20,
                }

        api = FakeApi()
        with patch.object(common.asyncio, "sleep", new=AsyncMock()):
            result = asyncio.run(
                common.wait_for_history_task(
                    api,  # type: ignore[arg-type]
                    label="资金",
                    start_time="2026-09-10 00:00:00",
                    end_time="2026-09-10 23:59:59",
                    download_type="CHARGE_BILL_ITEM",
                    time_type="BILL_TIME",
                    download_id="DL-fixture",
                    shop_id="289407271",
                    created_after=datetime(2026, 9, 11, 10, 59, 55, tzinfo=CN_TZ),
                    timeout=1,
                    poll_interval=0.01,
                )
            )
        self.assertEqual("DL-fixture", result["download_id"])
        self.assertEqual(2, api.calls)

    def test_401_refreshes_once_and_second_denial_needs_human(self) -> None:
        refresh = AsyncMock()
        api = common.BrowserApiSession(object(), refresh=refresh)
        responses: list[object] = [
            common.ApiError("expired", status=401, path="/fixture"),
            {"code": 0, "data": []},
        ]

        async def fake_fetch(*args: object, **kwargs: object) -> dict[str, object]:
            value = responses.pop(0)
            if isinstance(value, Exception):
                raise value
            return value  # type: ignore[return-value]

        with patch.object(common, "browser_fetch_json", new=fake_fetch):
            result = asyncio.run(
                api.get_json("/fixture", label="fixture", expected_codes={0})
            )
        self.assertEqual(0, result["code"])
        refresh.assert_awaited_once()

        denial = AsyncMock(side_effect=common.ApiError("denied", status=403, path="/fixture"))
        with patch.object(common, "browser_fetch_json", new=denial):
            with self.assertRaises(common.NeedsHumanError):
                asyncio.run(api.get_json("/fixture", label="fixture", expected_codes={0}))

    def test_download_is_atomic_unique_and_cleans_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            existing = output_dir / "DY_fund_20260910_to_20260910.csv"
            existing.write_bytes(b"old")
            session = FakeSession(FakeResponse([b"csv-data"]))
            with patch.object(common.requests, "Session", return_value=session):
                output = common.download_file(
                    "https://download.example/fixture.csv?signature=fixture",
                    output_dir,
                    existing.name,
                )
            self.assertEqual(b"old", existing.read_bytes())
            self.assertEqual(b"csv-data", output.read_bytes())
            self.assertEqual("DY_fund_20260910_to_20260910_1.csv", output.name)
            self.assertFalse(Path(str(output) + ".part").exists())
            self.assertTrue(session.closed)

        with tempfile.TemporaryDirectory() as directory:
            session = FakeSession(FakeResponse([]))
            with patch.object(common.requests, "Session", return_value=session):
                with self.assertRaisesRegex(RuntimeError, "下载文件为空"):
                    common.download_file(
                        "https://download.example/fixture.csv",
                        Path(directory),
                        "DY_settlement_20260910_to_20260910.csv",
                    )
            self.assertEqual([], list(Path(directory).iterdir()))

    def test_unified_resolves_once_and_reuses_endpoint_serially(self) -> None:
        calls: list[tuple[str, str, str, str]] = []

        class FakeModule:
            def __init__(self, name: str) -> None:
                self.name = name

            async def run_async(self, args: SimpleNamespace) -> Path:
                calls.append((self.name, args.ws_endpoint, args.start, args.end))
                return Path(f"{self.name}.csv")

        connection = ProfileConnection(
            profile_name="DY-抖音-测试店",
            profile_id="fixture-profile",
            endpoint="ws://127.0.0.1:45678/devtools/browser/fixture",
            started_by_this_run=False,
        )
        resolver_calls: list[dict[str, object]] = []

        def resolver(**kwargs: object) -> ProfileConnection:
            resolver_calls.append(kwargs)
            return connection

        args = SimpleNamespace(
            profile="DY-抖音-测试店",
            ws_endpoint=None,
            debug_port=None,
            mcp_url=None,
            report_type="全部",
            date="2026-09-10",
            shop="",
            company="",
            output_dir="downloads",
            timeout=10,
            poll_interval=0.01,
            profile_timeout=1,
            profile_poll_interval=0.01,
        )
        with patch.object(unified_download, "fund_download", FakeModule("fund")), patch.object(
            unified_download, "settlement_download", FakeModule("settlement")
        ):
            outputs = asyncio.run(unified_download.run_async(args, resolver=resolver))
        self.assertEqual(1, len(resolver_calls))
        self.assertEqual(
            [
                ("fund", connection.endpoint, "2026-09-10", "2026-09-10"),
                ("settlement", connection.endpoint, "2026-09-10", "2026-09-10"),
            ],
            calls,
        )
        self.assertEqual(2, len(outputs))

    def test_unified_exit_codes_include_needs_human_and_interrupt(self) -> None:
        cli = ["--profile", "DY-抖音-测试店", "--report-type", "资金"]
        with patch.object(
            unified_download,
            "run_async",
            new=AsyncMock(side_effect=common.NeedsHumanError("fixture")),
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
