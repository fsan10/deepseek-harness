from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts.auto_download.playwright.tmall_alipay_fund_download import (
    extract_business_date,
    extract_batch_reports,
    bill_days,
    unique_download_path,
)
from scripts.auto_download.playwright.login_extensions.tmall_finance_login import (
    _judge_slider_text,
    _read_environment_value,
    _type_credentials,
)


class FakeInput:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def click(self) -> None:
        self.calls.append(("click", None))

    async def press(self, key: str) -> None:
        self.calls.append(("press", key))

    async def type(self, value: str, delay: int) -> None:
        self.calls.append(("type", (value, delay)))


class TmallAlipayFundDownloadTests(unittest.TestCase):
    def test_batch_keeps_each_days_original_detail_and_discards_summaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'batch.zip'
            content = '账务明细,原始内容'.encode('gbk')
            with zipfile.ZipFile(archive, 'w') as bundle:
                for day in ('20261001', '20261002'):
                    bundle.writestr(f'12345_{day}_账务明细.csv', content)
                    bundle.writestr(f'12345_{day}_账务明细(汇总).csv', b'summary')
            reports = extract_batch_reports(archive, root/'extracted', '2026-10-01', '2026-10-02')
            self.assertEqual([day for day, _ in reports], ['2026-10-01', '2026-10-02'])
            self.assertTrue(all(path.read_bytes() == content for _, path in reports))
            self.assertEqual(len(list((root/'extracted').iterdir())), 2)
            self.assertFalse(archive.exists())

    def test_incomplete_duplicate_foreign_account_or_extra_day_batch_is_not_extracted(self):
        first = '12345_20261001_账务明细.csv'
        second = '12345_20261002_账务明细.csv'
        for names in ([first], [first, second, '12345_20261001_账务明细_1.csv'],
                      [first, '67890_20261002_账务明细.csv'], [first, second, '12345_20261003_账务明细.csv']):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive = root / 'batch.zip'
                with zipfile.ZipFile(archive, 'w') as bundle:
                    for name in names:
                        bundle.writestr(name, b'detail')
                with self.assertRaises(RuntimeError):
                    extract_batch_reports(archive, root/'extracted', '2026-10-01', '2026-10-02')
                self.assertTrue(archive.exists())
                self.assertFalse((root/'extracted').exists())

    def test_batch_dates_reject_reversed_and_future_ranges(self):
        self.assertEqual(bill_days('2026-10-01', '2026-10-02'), ['2026-10-01', '2026-10-02'])
        with self.assertRaises(ValueError):
            bill_days('2026-10-02', '2026-10-01')
        future = (date.today()+timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):
            bill_days(future, future)

    def test_extracts_day_and_month_dates(self) -> None:
        self.assertEqual("2026-08-13", extract_business_date("2026-08-13（周四）", "day"))
        self.assertEqual("2026-07", extract_business_date("2026-07", "month"))

    def test_download_path_does_not_overwrite_existing_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bill.zip").touch()

            self.assertEqual(root / "bill_002.zip", unique_download_path(root, "bill.zip"))

    def test_credentials_are_retyped_with_playwright_keyboard_events(self) -> None:
        account = FakeInput()
        password = FakeInput()

        asyncio.run(_type_credentials(account, password, "MOCK旗舰店", "secret-value"))

        self.assertEqual(
            [("click", None), ("press", "Control+A"), ("type", ("MOCK旗舰店", 50))],
            account.calls,
        )
        self.assertEqual(
            [("click", None), ("press", "Control+A"), ("type", ("secret-value", 50))],
            password.calls,
        )

    def test_process_environment_value_takes_precedence(self) -> None:
        with patch.dict(os.environ, {"TEST_TMALL_PASSWORD": "process-value"}):
            self.assertEqual("process-value", _read_environment_value("TEST_TMALL_PASSWORD"))

    @unittest.skipUnless(os.name == "nt", "Windows current-user environment fallback")
    def test_reads_fresh_windows_user_environment_when_process_is_stale(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("winreg.OpenKey") as open_key,
            patch("winreg.QueryValueEx", return_value=("user-value", 1)),
        ):
            open_key.return_value.__enter__.return_value = object()
            self.assertEqual("user-value", _read_environment_value("TEST_TMALL_PASSWORD"))

    def test_slider_text_judgement_uses_required_priority(self) -> None:
        self.assertEqual("pass", _judge_slider_text("验证成功 请点我重试"))
        self.assertEqual("fail", _judge_slider_text("请点我重试"))
        self.assertEqual("unknown", _judge_slider_text("向右滑动验证"))


if __name__ == "__main__":
    unittest.main()
