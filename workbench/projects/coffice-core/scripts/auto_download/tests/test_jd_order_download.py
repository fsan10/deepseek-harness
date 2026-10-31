from __future__ import annotations

import asyncio
import tempfile
import unittest
import zipfile
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from openpyxl import Workbook, load_workbook

from scripts.auto_download.playwright.jd_order_download import (
    _date_range_matches,
    _parse_created,
    _task_range_matches,
    _request_stateful_answer,
    decrypt_xlsx,
    extract_order_report,
    recent_month_range,
    validate_xlsx,
)


class JdOrderDownloadTests(unittest.TestCase):
    def test_recent_month_is_thirty_calendar_days_including_end(self) -> None:
        self.assertEqual(
            ("2026-07-29", "2026-08-27"),
            recent_month_range(today=date(2026, 8, 27)),
        )

    def test_history_range_requires_both_order_dates(self) -> None:
        text = "订单明细信息\n订单时间：2026-07-29 00:00:00 - 2026-08-27 23:59:59"
        self.assertTrue(_date_range_matches(text, "2026-07-29", "2026-08-27"))
        self.assertFalse(_date_range_matches(text, "2026-07-28", "2026-08-27"))

    def test_history_accepts_jd_rolling_shortcut_start_day_only(self) -> None:
        text = "订单明细信息\n订单时间：2026-07-28 12:00:37 - 2026-08-27 12:00:37"
        self.assertTrue(_task_range_matches(text, "2026-07-29", "2026-08-27"))
        self.assertFalse(_task_range_matches(text, "2026-07-30", "2026-08-27"))
        self.assertFalse(_task_range_matches(text, "2026-07-29", "2026-08-26"))

    def test_created_time_is_sortable(self) -> None:
        self.assertEqual(datetime(2026, 8, 26, 17, 49, 44), _parse_created("2026-08-26 17:49:44"))

    def test_extracts_unique_excel_file_and_ignores_txt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "orders.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("nested/订单明细信息.xlsx", b"xlsx-data")
                bundle.writestr("说明.txt", b"ignored")
            result = extract_order_report(archive, root / "extracted")
            self.assertEqual("xlsx-data", result.read_bytes().decode())

    def test_rejects_multiple_excel_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "orders.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("a.xlsx", b"a")
                bundle.writestr("b.xlsx", b"b")
            with self.assertRaisesRegex(RuntimeError, "未找到唯一报表"):
                extract_order_report(archive, root / "extracted")

    def test_rejects_unsafe_zip_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "orders.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../outside.xlsx", b"bad")
            with self.assertRaisesRegex(RuntimeError, "不安全路径"):
                extract_order_report(archive, root / "extracted")

    def test_plain_xlsx_is_copied_and_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.xlsx"
            target = root / "decrypted.xlsx"
            workbook = Workbook()
            workbook.active.append(["订单号", "金额"])
            workbook.active.append(["JD-1", 99])
            workbook.save(source)
            decrypt_xlsx(source, "ignored-for-plain-file", target)
            validate_xlsx(target)
            loaded = load_workbook(target, read_only=True)
            try:
                self.assertEqual(("订单号", "金额"), list(loaded.active.values)[0])
            finally:
                loaded.close()

    def test_challenge_id_survives_transient_wait_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.auto_download.playwright.jd_order_download.create_challenge",
            new=AsyncMock(
                return_value={
                    "challenge_id": "00000000-0000-0000-0000-000000000011",
                    "timeout_seconds": 30,
                }
            ),
        ), patch(
            "scripts.auto_download.playwright.jd_order_download.probe_relay"
        ), patch(
            "scripts.auto_download.playwright.jd_order_download.wait_answer",
            new=AsyncMock(side_effect=TimeoutError("relay temporarily unavailable")),
        ):
            state: dict[str, object] = {}
            state_path = Path(directory) / "jd_order_task.json"
            with self.assertRaises(TimeoutError):
                asyncio.run(
                    _request_stateful_answer(
                        challenge_key="file_password_challenge_id",
                        platform="京东",
                        company="公司",
                        shop="店铺",
                        purpose="订单报表文件提取码",
                        page_url="",
                        state_path=state_path,
                        state=state,
                    )
                )
            self.assertEqual(
                "00000000-0000-0000-0000-000000000011",
                state.get("file_password_challenge_id"),
            )


if __name__ == "__main__":
    unittest.main()
