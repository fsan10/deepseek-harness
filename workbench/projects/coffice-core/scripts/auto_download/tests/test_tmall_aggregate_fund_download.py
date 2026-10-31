from __future__ import annotations

import unittest

from scripts.auto_download.playwright.tmall_aggregate_fund_download import extract_business_date


class TmallAggregateFundDownloadTests(unittest.TestCase):
    def test_extracts_day_date(self) -> None:
        self.assertEqual("2026-08-15", extract_business_date("20260815", "day"))

    def test_extracts_month_date(self) -> None:
        self.assertEqual("2026-07", extract_business_date("202607", "month"))

    def test_rejects_wrong_date_granularity(self) -> None:
        with self.assertRaises(RuntimeError):
            extract_business_date("202607", "day")


if __name__ == "__main__":
    unittest.main()
