from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.auto_download.move_report import target_path
from apps.file_ingest.naming import guess_filename


class MoveReportTests(unittest.TestCase):
    def test_douyin_reports_share_the_ingest_company_naming_contract(self):
        shop = {'platform_code':'douyin', 'company_name':'南京宁盏食品科技有限公司',
                'shop_name':'MOCK宁盏冲饮专卖店', 'shop_code':'219888797'}
        with tempfile.TemporaryDirectory() as directory:
            for report in ('订单', '资金', '结算', '千川推广费'):
                with self.subTest(report=report):
                    target = target_path(Path(directory), '抖音', ' 南京宁盏食品科技有限公司 ',
                                         shop['shop_name'], report, '20261009', '.CSV')
                    result = guess_filename(target.name, [shop])
                    self.assertTrue(result['matched'])
                    self.assertEqual(shop['shop_code'], result['shop_code'])
                    self.assertEqual(shop['company_name'], result['company_name'])

    def test_invalid_or_empty_components_follow_ingest_rules_before_creating_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                target_path(root, '抖音', ' ', '店铺', '订单', '20261009', '.csv')
            self.assertFalse(any(root.iterdir()))
            target = target_path(root, '抖音', '甲/乙', '店:铺', '订单', '20261009', '.csv')
            self.assertEqual('20261009_抖音_甲-乙_店-铺_订单.csv', target.name)

    def test_all_registry_report_names_are_available(self):
        cases = (
            ("抖音", "千川推广费"),
            ("京东", "京东联盟推广费"),
            ("天猫", "支付宝账户资金"),
            ("天猫", "聚合账户资金"),
            ("天猫", "结算收入"),
            ("天猫", "结算支出"),
            ("天猫", "淘宝联盟推广费"),
            ("天猫", "万相台推广费"),
            ("快手", "资金"),
            ("快手", "结算"),
            ("拼多多", "推广费"),
            ("拼多多", "结算"),
            ("视频号", "结算"),
            ("小红书", "资金"),
            ("小红书", "结算"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for platform, report in cases:
                with self.subTest(platform=platform, report=report):
                    target = target_path(
                        root, platform, "示例公司", "示例店铺", report, "20260814", ".xlsx"
                    )
                    self.assertEqual("2026.08", target.parent.name)
                    self.assertEqual(report, target.parent.parent.name)
                    self.assertEqual(
                        f"20260814_{platform}_示例公司_示例店铺_{report}.xlsx",
                        target.name,
                    )

    def test_month_prefix_and_sequence_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = target_path(root, "天猫", "示例公司", "示例店铺", "结算收入", "202608", ".csv")
            first.touch()
            second = target_path(root, "天猫", "示例公司", "示例店铺", "结算收入", "202608", ".csv")
            self.assertTrue(second.name.endswith("_002.csv"))

    def test_platform_report_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "可选标准报表"):
                target_path(
                    Path(directory), "天猫", "示例公司", "示例店铺", "资金", "20260814", ".xlsx"
                )

    def test_invalid_business_date_is_rejected_before_directory_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                target_path(Path(directory), "抖音", "公司", "店铺", "订单", "20260230", ".csv")
            self.assertFalse(any(Path(directory).iterdir()))


if __name__ == "__main__":
    unittest.main()
