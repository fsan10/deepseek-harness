# -*- coding: utf-8 -*-
"""小红书共享原始文件下载契约测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ReverseAPI.Formal_Script import xhs_webapi_common as common


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


class XhsWebApiCommonTests(unittest.TestCase):
    def test_download_uses_unique_name_and_atomic_nonempty_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            existing = output_dir / "XHS_order_2026-09-09_to_2026-09-09.xlsx"
            existing.write_bytes(b"old")
            session = FakeSession(FakeResponse([b"xlsx-data"]))
            with patch.object(common.requests, "Session", return_value=session):
                output = common.download_file(
                    "https://download.example/report.xlsx?signature=fixture",
                    output_dir,
                    existing.name,
                )

            self.assertEqual(b"old", existing.read_bytes())
            self.assertEqual(b"xlsx-data", output.read_bytes())
            self.assertEqual("XHS_order_2026-09-09_to_2026-09-09_1.xlsx", output.name)
            self.assertFalse(Path(str(output) + ".part").exists())
            self.assertTrue(session.closed)

    def test_empty_download_removes_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            session = FakeSession(FakeResponse([]))
            with patch.object(common.requests, "Session", return_value=session):
                with self.assertRaisesRegex(RuntimeError, "下载文件为空"):
                    common.download_file(
                        "https://download.example/report.xlsx",
                        output_dir,
                        "XHS_fund_day_2026-09-09.xlsx",
                    )
            self.assertEqual([], list(output_dir.iterdir()))
            self.assertTrue(session.closed)

    def test_download_403_is_needs_human(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = FakeSession(FakeResponse([], 403))
            with patch.object(common.requests, "Session", return_value=session):
                with self.assertRaises(common.NeedsHumanError):
                    common.download_file(
                        "https://download.example/report.xlsx",
                        Path(directory),
                        "XHS_settlement_day_2026-09-09.xlsx",
                    )


if __name__ == "__main__":
    unittest.main()
