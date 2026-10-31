import unittest

from scripts.auto_download.playwright.qianchuan_login import (
    parse_aavid_from_url,
    resolve_account,
)
from scripts.auto_download.playwright.qianchuan_promotion_fee_download import (
    select_latest_daily_record,
)


class SelectLatestDailyRecordTests(unittest.TestCase):
    def test_reads_first_date_row_and_skips_total(self) -> None:
        headers, row = select_latest_daily_record(
            [{"headers": ["日期", "余额总消耗(元)", "非赠款余额(元)"], "rows": [
                ["总计", "100.00", "-"],
                ["2026-08-13", " 84,017.50\n", "226,580.10"],
                ["2026-08-12", "39,862.63", "137,084.59"],
            ]}]
        )

        self.assertEqual(["日期", "余额总消耗(元)", "非赠款余额(元)"], headers)
        self.assertEqual(["2026-08-13", "84,017.50", "226,580.10"], row)

    def test_rejects_changed_row_width(self) -> None:
        tables = [{"headers": ["日期", "余额总消耗(元)"], "rows": [["2026-08-13"]]}]

        with self.assertRaisesRegex(RuntimeError, "列数"):
            select_latest_daily_record(tables)

    def test_rejects_empty_table_skeleton(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "有效业务日期行"):
            select_latest_daily_record([{"headers": ["日期", "余额总消耗(元)"], "rows": []}])


class QianchuanAccountResolutionTests(unittest.TestCase):
    def test_auto_uses_existing_matching_account_before_default(self) -> None:
        account = resolve_account(
            "auto",
            "津果日记生物科技(南京)有限公司",
            "MOCK冲饮旗舰店",
            existing_aavids=["1854896545860682"],
        )

        self.assertEqual("1854896545860682", account.aavid)

    def test_auto_selects_default_for_new_shop_profile(self) -> None:
        account = resolve_account(
            "auto",
            "墨客咖时(南京)生物科技有限公司",
            "MOCK官方旗舰店",
        )

        self.assertEqual("1855526984749068", account.aavid)

    def test_explicit_secondary_account_is_not_rewritten(self) -> None:
        account = resolve_account(
            "1860540938445002",
            "津果日记生物科技(南京)有限公司",
            "MOCK冲饮旗舰店",
        )

        self.assertEqual("1860540938445002", account.aavid)

    def test_parse_aavid_supports_home_and_finance_urls(self) -> None:
        self.assertEqual(
            "1854896545860682",
            parse_aavid_from_url(
                "https://qianchuan.jinritemai.com/home?aavid=1854896545860682"
            ),
        )
        self.assertEqual(
            "1854896545860682",
            parse_aavid_from_url(
                "https://qianchuan.jinritemai.com/cg_trade/finance/wallet?aadvid=1854896545860682"
            ),
        )
