from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.auto_download.extract_report import (
    extract_selected_report,
    repair_member_name,
)


class ExtractReportTests(unittest.TestCase):
    def test_repairs_gbk_name_decoded_as_cp437(self) -> None:
        expected = "20888415902369850156_20260813_账务明细.csv"
        mojibake = expected.encode("gbk").decode("cp437")

        self.assertEqual(expected, repair_member_name(mojibake, 0, "gbk"))

    def test_extracts_detail_only_and_deletes_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "bill.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("123_20260813_账务明细.csv", b"detail")
                bundle.writestr("123_20260813_账务明细(汇总).csv", b"summary")

            target = extract_selected_report(
                archive,
                root / "output",
                delete_archive=True,
            )

            self.assertEqual(b"detail", target.read_bytes())
            self.assertFalse(archive.exists())
            self.assertFalse((root / "output" / "123_20260813_账务明细(汇总).csv").exists())

    def test_extracts_monthly_detail_with_sequence_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "monthly.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("123_202608_账务明细_1.csv", b"monthly-detail")
                bundle.writestr("123_202608_账务明细(汇总)_1.csv", b"monthly-summary")

            target = extract_selected_report(
                archive,
                root / "output",
                include_text="账务明细",
                delete_archive=True,
            )

            self.assertEqual("123_202608_账务明细_1.csv", target.name)
            self.assertEqual(b"monthly-detail", target.read_bytes())
            self.assertFalse(archive.exists())


if __name__ == "__main__":
    unittest.main()
