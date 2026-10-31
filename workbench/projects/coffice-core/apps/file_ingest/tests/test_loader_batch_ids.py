from __future__ import annotations

import unittest

from apps.file_ingest.service import FileIngestWorker


class LoaderBatchIdsTests(unittest.TestCase):
    def test_parse_single_and_multi_sheet_batch_ids(self):
        self.assertEqual([101], FileIngestWorker._parse_loader_batch_ids("导入批次ID：101"))
        self.assertEqual(
            [101, 102],
            FileIngestWorker._parse_loader_batch_ids("导入批次ID：101,102\n工作表完成"),
        )

    def test_reject_output_without_batch_id(self):
        self.assertEqual([], FileIngestWorker._parse_loader_batch_ids("工作表完成"))


if __name__ == "__main__":
    unittest.main()
