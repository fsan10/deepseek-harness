# -*- coding: utf-8 -*-
"""拼多多订单日期时间戳的无网络回归测试。

真实 CDP 探针和响应只能放在 ``.codex_tmp/``；永久测试不得在导入时连接
Profile，也不得保存真实 wsEndpoint。
"""

from __future__ import annotations

import unittest

from ReverseAPI.Formal_Script.pdd_order_export_download import (
    date_to_end_ts,
    date_to_start_ts,
    validate_date_range,
)


class PddApiDateTests(unittest.TestCase):
    def test_china_timezone_day_boundaries(self) -> None:
        self.assertEqual(1788624000, date_to_start_ts("2026-09-06"))
        self.assertEqual(1788710399, date_to_end_ts("2026-09-06"))

    def test_date_range_rejects_reverse_order(self) -> None:
        with self.assertRaisesRegex(ValueError, "开始日期不能晚于结束日期"):
            validate_date_range("2026-09-07", "2026-09-06")


if __name__ == "__main__":
    unittest.main()
