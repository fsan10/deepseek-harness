import json
import unittest
from datetime import date

import httpx

from automation.metric_collect import fetch_metrics
from automation.metric_http import MetricHttpSession
from automation.metric_parsers import parse_xhs_reception
from automation.review_errors import ContractError


PROFILE = {"profile_id": "xhs-test", "platform": "xiaohongshu", "shop_name": "测试店",
           "expected_shop_name": "测试店"}


def response(day, value):
    stamp = int(day.replace("-", ""))
    return {"code": 0, "data": [{"blockKey": "sellerCSOverall", "statisticsDate": str(stamp),
                                 "data": [{"dtm": {"value": stamp}, "caseCnt": {"value": value}}]}]}


class XhsReceptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_requested_day_uses_single_day_instead_of_last_seven_days(self):
        filters = []
        def handle(request):
            if request.url.path.endswith("/seller/info/v2"):
                return httpx.Response(200, json={"code": 0, "data": {"seller_name": "测试店", "seller_id": "test-id"}})
            filt = json.loads(request.content)["requestBody"]["blockElements"][0]["filterMap"]
            filters.append(filt)
            # dateType=2 是近7日：即便汇总日期碰巧相同，也不能把汇总值当成单日值。
            value = 3 if filt["dateType"] == 1 else 14
            return httpx.Response(200, json=response(filt["date"], value))
        credentials = {"profile_id": "xhs-test", "user_agent": "test", "cookies": []}
        async with MetricHttpSession(PROFILE, credentials, transport=httpx.MockTransport(handle)) as client:
            result = await fetch_metrics(PROFILE, "reception", date(2026, 10, 27), client=client)
        self.assertEqual(filters, [{"dateSelectType": "day", "dateType": 1, "date": "2026-10-27"}])
        self.assertEqual(result["records"][0]["reportDate"], "2026-10-27")
        self.assertEqual(result["records"][0]["value"], 3)

    def test_block_date_mismatch_still_fails(self):
        with self.assertRaises(ContractError):
            parse_xhs_reception(PROFILE, response("2026-10-28", 2), "2026-10-27")

    def test_metric_date_mismatch_still_fails(self):
        body = response("2026-10-27", 3)
        body["data"][0]["data"][0]["dtm"]["value"] = 20261028
        with self.assertRaises(ContractError):
            parse_xhs_reception(PROFILE, body, "2026-10-27")


if __name__ == "__main__":
    unittest.main()
