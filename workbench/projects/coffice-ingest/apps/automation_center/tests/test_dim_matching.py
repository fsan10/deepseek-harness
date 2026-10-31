from __future__ import annotations

import unittest
from datetime import date

from apps.automation_center.dim_matching import (
    MAPPING_AMBIGUOUS, MAPPING_COMPANY_MISMATCH, MAPPING_EXPIRED, MAPPING_INACTIVE,
    MAPPING_MATCHED, MAPPING_MISSING_METADATA, MAPPING_NOT_FOUND, resolve_dim,
)


def row(**overrides):
    base = {
        "platform_code": "DY", "platform_name": "抖音", "company_code": "C1",
        "company_name": "津果日记生物科技（南京）有限公司", "shop_code": "114877104",
        "shop_name": "MOCK冲饮旗舰店", "account_id": "114877104", "is_active": True,
        "valid_from": date(1900, 1, 1), "valid_to": None,
    }
    base.update(overrides)
    return base


class DimMatchingTests(unittest.TestCase):
    def test_half_width_parentheses_in_profile_note_still_match(self):
        """生产事故：note 写 (南京)，DIM 写（南京），旧实现直接判定未映射。"""

        result = resolve_dim([row()], {"platform": "抖音", "shop": "MOCK冲饮旗舰店",
                                       "company": "津果日记生物科技(南京)有限公司"})
        self.assertEqual(MAPPING_MATCHED, result["mapping_status"])
        self.assertEqual("114877104", result["shop_code"])
        self.assertTrue(result["mapping_ok"])

    def test_trailing_spaces_and_case_are_ignored(self):
        result = resolve_dim([row(shop_name="MOCK冲饮旗舰店 ")], {"platform": " 抖音 ", "shop": "mock冲饮旗舰店"})
        self.assertEqual(MAPPING_MATCHED, result["mapping_status"])

    def test_company_mismatch_maps_shop_but_keeps_a_warning(self):
        result = resolve_dim([row()], {"platform": "抖音", "shop": "MOCK冲饮旗舰店", "company": "另一家公司"})
        self.assertEqual(MAPPING_COMPANY_MISMATCH, result["mapping_status"])
        self.assertTrue(result["mapping_ok"])
        self.assertEqual("114877104", result["shop_code"])
        self.assertIn("公司名", result["mapping_reason"])

    def test_shop_code_wins_over_a_confusing_name(self):
        result = resolve_dim([row(), row(shop_code="999", shop_name="别的店", account_id="999")],
                             {"platform": "抖音", "shop": "写错的店名", "shop_code": "999"})
        self.assertEqual(MAPPING_MATCHED, result["mapping_status"])
        self.assertEqual("999", result["shop_code"])

    def test_same_name_multiple_codes_is_reported_as_ambiguous(self):
        rows = [row(shop_code="A", account_id="A"), row(shop_code="B", account_id="B")]
        result = resolve_dim(rows, {"platform": "抖音", "shop": "MOCK冲饮旗舰店", "company": "不存在"})
        self.assertEqual(MAPPING_AMBIGUOUS, result["mapping_status"])
        self.assertFalse(result["mapping_ok"])
        self.assertEqual(2, len(result["mapping_candidates"]))

    def test_company_narrows_ambiguous_rows(self):
        rows = [row(shop_code="A", account_id="A", company_name="甲公司"),
                row(shop_code="B", account_id="B", company_name="乙公司")]
        result = resolve_dim(rows, {"platform": "抖音", "shop": "MOCK冲饮旗舰店", "company": "乙公司"})
        self.assertEqual(MAPPING_MATCHED, result["mapping_status"])
        self.assertEqual("B", result["shop_code"])

    def test_inactive_and_expired_rows_are_distinguished(self):
        inactive = resolve_dim([row(is_active=False)], {"platform": "抖音", "shop": "MOCK冲饮旗舰店"})
        self.assertEqual(MAPPING_INACTIVE, inactive["mapping_status"])
        expired = resolve_dim([row(valid_to=date(2020, 1, 1))], {"platform": "抖音", "shop": "MOCK冲饮旗舰店"})
        self.assertEqual(MAPPING_EXPIRED, expired["mapping_status"])

    def test_missing_metadata_and_unknown_shop(self):
        self.assertEqual(MAPPING_MISSING_METADATA, resolve_dim([row()], {"platform": "抖音"})["mapping_status"])
        self.assertEqual(MAPPING_NOT_FOUND, resolve_dim([row()], {"platform": "抖音", "shop": "不存在"})["mapping_status"])


if __name__ == "__main__":
    unittest.main()
