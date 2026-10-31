from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from openpyxl import Workbook

from etl.xhs.load_xhs_order_ods import EXPECTED_COLUMNS
from scripts.auto_download.playwright.xiaohongshu_download_common import (
    _click_ad_close,
    is_probable_ad_popup,
)
from scripts.auto_download.playwright.xiaohongshu_order_download import (
    DATE_POPUP_XPATH,
    EXPORT_BUTTON_XPATH,
    NOTICE_CONFIRM_XPATH,
    ORDER_MENU_XPATH,
    XHS_ORDER_HEADERS,
    _date_value_contains,
    _parse_iso_date,
    validate_order_report,
)


class XiaohongshuOrderDownloadTests(unittest.TestCase):
    def test_user_supplied_xpath_contract_is_first_class(self):
        self.assertIn('root-menu-wrapper', ORDER_MENU_XPATH)
        self.assertEqual('xpath=/html/body/div[38]', DATE_POPUP_XPATH)
        self.assertIn('button[2]', NOTICE_CONFIRM_XPATH)
        self.assertIn('new_order_manage_step_second', EXPORT_BUTTON_XPATH)

    def test_ad_popup_classifier_does_not_close_business_dialog(self):
        self.assertTrue(is_probable_ad_popup('activity-popup', ''))
        self.assertTrue(is_probable_ad_popup('portal', '限时优惠'))
        self.assertFalse(is_probable_ad_popup('modal', '订单导出提示 确定'))
        self.assertFalse(is_probable_ad_popup('picker', '近30天'))

    def test_ad_popup_close_rescans_after_candidate_disappears(self):
        async def close_stale_candidate():
            with (
                patch(
                    'scripts.auto_download.playwright.xiaohongshu_download_common.click_compat',
                    new=AsyncMock(side_effect=TimeoutError('stale popup locator')),
                ),
                patch(
                    'scripts.auto_download.playwright.xiaohongshu_download_common._is_visible',
                    new=AsyncMock(return_value=False),
                ),
            ):
                return await _click_ad_close(object())

        self.assertFalse(asyncio.run(close_stale_candidate()))

    def test_archive_returns_monthly_path_directly(self):
        from scripts.auto_download.move_report import archive_report
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.xlsx'
            source.write_bytes(b'fixture')
            target = archive_report(source,'小红书','公司','店铺','订单','2026-08-27',root)
            self.assertEqual(root/'小红书'/'订单'/'2026.08'/'20260827_小红书_公司_店铺_订单.xlsx',target)

    def test_validate_order_workbook_matches_ods_loader_header(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'orders.xlsx'
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(EXPECTED_COLUMNS)
            sheet.append([''] * len(EXPECTED_COLUMNS))
            workbook.save(report)
            validate_order_report(report)

    def test_validate_order_workbook_rejects_changed_header(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'orders.xlsx'
            workbook = Workbook()
            workbook.active.append(list(XHS_ORDER_HEADERS[:-1]) + ['错误字段'])
            workbook.save(report)
            with self.assertRaisesRegex(RuntimeError, '小红书订单表头异常'):
                validate_order_report(report)

    def test_custom_order_date_range_helpers(self):
        self.assertEqual("2026-08-01", _parse_iso_date("2026-08-01", "--start-date").isoformat())
        self.assertTrue(
            _date_value_contains("2026/08/01 00:00:00 ~ 2026/08/31 23:59:59", "2026-08-31")
        )
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            _parse_iso_date("2026/08/01", "--start-date")


if __name__ == '__main__':
    unittest.main()
