# -*- coding: utf-8 -*-
"""拼多多共享下载契约的纯逻辑测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ReverseAPI.Formal_Script import pdd_webapi_common as common


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
        self.proxies: dict[str, str] = {}
        self.cookies = unittest.mock.Mock()
        self.closed = False

    def get(self, *args: object, **kwargs: object) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


class PddWebApiCommonTests(unittest.TestCase):
    def test_download_is_unique_atomic_and_nonempty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            existing = output_dir / "PDD_order_2026-09-09_to_2026-09-09.csv"
            existing.write_bytes(b"old")
            session = FakeSession(FakeResponse([b"new-data"]))
            with patch.object(common.requests, "Session", return_value=session):
                output = common.download_original_file(
                    "https://download.example/report.csv?signature=secret",
                    output_dir,
                    existing.name,
                )

            self.assertEqual(b"old", existing.read_bytes())
            self.assertEqual(b"new-data", output.read_bytes())
            self.assertEqual("PDD_order_2026-09-09_to_2026-09-09_1.csv", output.name)
            self.assertFalse(Path(str(output) + ".part").exists())
            self.assertTrue(session.closed)

    def test_empty_download_removes_part_and_keeps_no_final_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            session = FakeSession(FakeResponse([]))
            with patch.object(common.requests, "Session", return_value=session):
                with self.assertRaisesRegex(RuntimeError, "下载为空"):
                    common.download_original_file(
                        "https://download.example/report.zip",
                        output_dir,
                        "PDD_settlement_2026-09-09_to_2026-09-09.zip",
                    )

            self.assertEqual([], list(output_dir.iterdir()))
            self.assertTrue(session.closed)

    def test_download_403_is_needs_human(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = FakeSession(FakeResponse([], status_code=403))
            with patch.object(common.requests, "Session", return_value=session):
                with self.assertRaises(common.NeedsHumanError):
                    common.download_original_file(
                        "https://download.example/report.xls",
                        Path(directory),
                        "PDD_promotion_fee_2026-09-09_to_2026-09-09.xls",
                    )


if __name__ == "__main__":
    unittest.main()
