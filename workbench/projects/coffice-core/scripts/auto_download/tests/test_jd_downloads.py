from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.auto_download.playwright.jd_download_common import extract_nested_csv
from scripts.auto_download.playwright.jd_settlement_download import extract_business_date


class JdDownloadTests(unittest.TestCase):
    def test_extracts_settlement_dates(self) -> None:
        self.assertEqual("2026-08-17", extract_business_date("2026-08-17\n2026-08-16", "day"))
        self.assertEqual("2026-07", extract_business_date("2026-07\n12559.19", "month"))

    def test_extracts_day_zip_csv_and_ignores_txt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "day.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("结算明细.csv", "a,b\n1,2\n")
                bundle.writestr("说明.txt", "ignored")
            result = extract_nested_csv(archive, root / "out")
            self.assertEqual("a,b\n1,2\n", result.read_text(encoding="utf-8"))
            self.assertFalse(archive.exists())

    def test_extracts_month_nested_zip_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inner_bytes = io.BytesIO()
            with zipfile.ZipFile(inner_bytes, "w") as inner:
                inner.writestr("月结算明细.csv", "x,y\n3,4\n")
            archive = root / "month.zip"
            with zipfile.ZipFile(archive, "w") as outer:
                outer.writestr("detail.zip", inner_bytes.getvalue())
            result = extract_nested_csv(archive, root / "out")
            self.assertEqual("x,y\n3,4\n", result.read_text(encoding="utf-8"))
            self.assertFalse(archive.exists())


if __name__ == "__main__":
    unittest.main()
