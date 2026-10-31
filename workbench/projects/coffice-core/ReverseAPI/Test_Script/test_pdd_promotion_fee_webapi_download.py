# -*- coding: utf-8 -*-
"""拼多多推广费 WebAPI 下载脚本的纯逻辑测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

try:
    from ReverseAPI.Formal_Script.pdd_promotion_fee_webapi_download import (
        ApiResponse,
        EXPORT_URL,
        QUERY_URL,
        date_to_timestamp,
        execute_api_chain,
        extract_export_url,
        natural_date_to_iso,
        replace_date_fields,
        result_count,
    )
except ModuleNotFoundError:
    from Formal_Script.pdd_promotion_fee_webapi_download import (
        ApiResponse,
        EXPORT_URL,
        QUERY_URL,
        date_to_timestamp,
        execute_api_chain,
        extract_export_url,
        natural_date_to_iso,
        replace_date_fields,
        result_count,
    )


class PddPromotionFeeWebApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_zero_rows_does_not_call_export_or_download(self) -> None:
        calls: list[str] = []

        async def post(url: str, payload: dict[str, Any]) -> ApiResponse:
            calls.append(url)
            self.assertEqual(payload["startDate"], "2026-09-08")
            self.assertEqual(payload["endDate"], "2026-09-08")
            return ApiResponse(
                status=200,
                body={
                    "success": True,
                    "errorCode": 1000,
                    "result": {"total": 0, "result": []},
                },
            )

        async def download(*args: Any) -> Path:
            raise AssertionError("0 条结果不应下载文件")

        with tempfile.TemporaryDirectory() as directory:
            result = await execute_api_chain(
                post,
                download,
                {
                    "crawlerInfo": "runtime-only",
                    "startDate": "2026-08-11",
                    "endDate": "2026-09-09",
                    "sortBy": 0,
                    "flowType": 2,
                    "fundType": 1,
                    "pageSize": 50,
                    "pageNumber": 1,
                },
                start_date="2026-09-08",
                end_date="2026-09-08",
                output_dir=Path(directory),
            )
        self.assertIsNone(result)
        self.assertEqual(calls, [QUERY_URL])

    async def test_nonzero_rows_calls_export_then_download(self) -> None:
        calls: list[str] = []

        async def post(url: str, payload: dict[str, Any]) -> ApiResponse:
            calls.append(url)
            if url == QUERY_URL:
                return ApiResponse(
                    status=200,
                    body={"success": True, "result": {"total": 2, "result": [{}, {}]}},
                )
            self.assertEqual(url, EXPORT_URL)
            return ApiResponse(
                status=200,
                body={
                    "success": True,
                    "errorCode": 1000,
                    "result": "https://pfs.pinduoduo.com/account-invoice/2026-09-09/file.xls?sign=runtime-only",
                },
            )

        async def download(
            signed_url: str,
            start_date: str,
            end_date: str,
            output_dir: Path,
        ) -> Path:
            self.assertIn("sign=runtime-only", signed_url)
            self.assertEqual((start_date, end_date), ("2026-09-01", "2026-09-08"))
            self.assertTrue(output_dir.is_absolute() or not output_dir.exists())
            return output_dir / "raw.xls"

        with tempfile.TemporaryDirectory() as directory:
            result = await execute_api_chain(
                post,
                download,
                {
                    "crawlerInfo": "runtime-only",
                    "startDate": "2026-08-11",
                    "endDate": "2026-09-09",
                    "sortBy": 0,
                    "flowType": 2,
                    "fundType": 1,
                    "pageSize": 50,
                    "pageNumber": 1,
                },
                start_date="2026-09-01",
                end_date="2026-09-08",
                output_dir=Path(directory),
            )
        self.assertEqual(result, Path(directory) / "raw.xls")
        self.assertEqual(calls, [QUERY_URL, EXPORT_URL])

    def test_replace_date_fields_preserves_other_natural_fields(self) -> None:
        natural = {
            "crawlerInfo": "runtime-only",
            "startDate": "2026-08-11",
            "endDate": "2026-09-09",
            "sortBy": 0,
            "flowType": 2,
            "fundType": 1,
            "pageSize": 50,
            "pageNumber": 1,
        }
        replaced = replace_date_fields(natural, "2026-09-01", "2026-09-08")
        self.assertEqual(replaced["startDate"], "2026-09-01")
        self.assertEqual(replaced["endDate"], "2026-09-08")
        self.assertEqual(replaced["crawlerInfo"], natural["crawlerInfo"])
        self.assertEqual(replaced["flowType"], 2)
        self.assertEqual(replaced["fundType"], 1)
        self.assertEqual(natural["startDate"], "2026-08-11")

    def test_replace_date_fields_supports_natural_unix_timestamps(self) -> None:
        natural = {
            "startDate": date_to_timestamp("2026-08-11", end_of_day=False, milliseconds=False),
            "endDate": date_to_timestamp("2026-09-09", end_of_day=True, milliseconds=False),
            "flowType": 2,
            "fundType": 1,
        }
        replaced = replace_date_fields(natural, "2026-09-01", "2026-09-08")
        self.assertEqual(
            replaced["startDate"],
            date_to_timestamp("2026-09-01", end_of_day=False, milliseconds=False),
        )
        self.assertEqual(
            replaced["endDate"],
            date_to_timestamp("2026-09-08", end_of_day=True, milliseconds=False),
        )

    def test_natural_numeric_date_can_be_used_for_default_filename_range(self) -> None:
        start = date_to_timestamp("2026-08-11", end_of_day=False, milliseconds=True)
        end = date_to_timestamp("2026-09-09", end_of_day=True, milliseconds=True)
        self.assertEqual(natural_date_to_iso(start, field_name="自然开始日期"), "2026-08-11")
        self.assertEqual(natural_date_to_iso(end, field_name="自然结束日期"), "2026-09-09")

    def test_result_count_and_export_url(self) -> None:
        self.assertEqual(
            result_count({"result": {"total": 0, "result": []}, "success": True}),
            0,
        )
        self.assertEqual(
            result_count({"result": {"result": [{"id": 1}, {"id": 2}]} }),
            2,
        )
        self.assertEqual(
            extract_export_url(
                {"result": "https://pfs.pinduoduo.com/account-invoice/file.xls"}
            ),
            "https://pfs.pinduoduo.com/account-invoice/file.xls",
        )


if __name__ == "__main__":
    unittest.main()
