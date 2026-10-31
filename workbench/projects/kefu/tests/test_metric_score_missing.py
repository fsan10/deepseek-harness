"""抖音体验分的缺失占位值不影响其他正常指标，也不能变成零。"""
from __future__ import annotations

import unittest

from automation.metric_parsers import number, parse_douyin_reception, parse_douyin_score
from automation.review_errors import ContractError


def score_payloads():
    profile = {"platform": "douyin", "shop_name": "测试店", "expected_shop_name": "测试店"}
    overview = {"data": {
        "has_data": True,
        "done_info": {"done_date": "20261026"},
        "formal_score_info": {key: {"score": score} for key, score in (
            ("experience_score", 87), ("goods_score", 83),
            ("logistics_score", 84), ("service_score", 87))},
    }}
    details = {"data": {
        "has_data": True,
        "shop_name": "测试店",
        "done_info": {"done_date": "20261026"},
        "shop_order_latest_30_cnt": 32,
        "formal_score_metric_info": {
            "shop_sub_score": [
                {"sub_score_node": 1, "sub_score_name": "商品体验"},
                {"sub_score_node": 3, "sub_score_name": "服务体验"},
            ],
            "metrics": [
                {"node_id": 108, "title": "商品综合评分",
                 "value": {"value_type": 4, "value_figure": -9999}},
                {"node_id": 103, "title": "商品品质退货率",
                 "value": {"value_type": 2, "value_figure": 0}},
                {"node_id": 317, "title": "飞鸽人工会话不满意率",
                 "value": {"value_type": 2, "value_figure": -9999}},
                {"node_id": 309, "title": "飞鸽人工会话平响时长",
                 "value": {"value_type": 6, "value_figure": 14.226}},
            ],
        },
    }}
    return profile, overview, details


class DouyinMissingScoreTests(unittest.TestCase):
    def test_missing_details_preserve_main_scores_and_real_zero(self):
        rows = parse_douyin_score(*score_payloads())
        values = {row["metricName"]: row["value"] for row in rows}
        self.assertEqual(values, {
            "店铺体验分": 87, "商品体验分": 83, "物流体验分": 84,
            "服务体验分": 87, "近30天有效订单": 32,
            "商品品质退货率": "0%", "飞鸽人工会话平响时长": 14.226,
        })
        self.assertTrue(all(row["reportDate"] == "2026-10-26" for row in rows))

    def test_missing_sentinel_numeric_string_and_null(self):
        for missing in (-9999, -9999.0, "-9999", None):
            with self.subTest(missing=missing):
                profile, overview, details = score_payloads()
                metrics = details["data"]["formal_score_metric_info"]["metrics"]
                metrics[0]["value"]["value_figure"] = missing
                metrics[2]["value"]["value_figure"] = missing
                self.assertEqual(len(parse_douyin_score(profile, overview, details)), 7)

    def test_all_details_missing_still_keep_main_scores(self):
        profile, overview, details = score_payloads()
        for metric in details["data"]["formal_score_metric_info"]["metrics"]:
            metric["value"]["value_figure"] = -9999
        rows = parse_douyin_score(profile, overview, details)
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["metricCategory"] == "总览" for row in rows))

    def test_real_negative_and_malformed_details_still_fail_with_name(self):
        for invalid in (-1, -0.01, "-0.1", -9998, True, "NaN", "invalid", float("inf")):
            with self.subTest(invalid=invalid):
                profile, overview, details = score_payloads()
                details["data"]["formal_score_metric_info"]["metrics"][0]["value"]["value_figure"] = invalid
                with self.assertRaisesRegex(ContractError, "商品综合评分"):
                    parse_douyin_score(profile, overview, details)

    def test_sentinel_does_not_bypass_main_score_or_reception_validation(self):
        profile, overview, details = score_payloads()
        overview["data"]["formal_score_info"]["experience_score"]["score"] = -9999
        with self.assertRaises(ContractError):
            parse_douyin_score(profile, overview, details)
        with self.assertRaises(ContractError):
            number(-9999)
        with self.assertRaises(ContractError):
            parse_douyin_reception(profile, {"data": {"list": [
                {"date": "20261026", "shop_serv_conv_cnt": {"value": -9999}},
            ]}}, "2026-10-26")


if __name__ == "__main__":
    unittest.main()
