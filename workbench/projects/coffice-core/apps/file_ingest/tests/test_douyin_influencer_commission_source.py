from __future__ import annotations

import unittest

from apps.file_ingest.registry import PROJECT_ROOT


class DouyinInfluencerCommissionSourceTests(unittest.TestCase):
    def test_refresh_reads_fund_and_deduplicates_by_shop_flow(self):
        sql_text = (
            PROJECT_ROOT
            / "sql/douyin/influencer_commission/237_refresh_dwd_douyin_influencer_commission_event_detail_postgres.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("FROM ods.ods_douyin_fund_raw raw", sql_text)
        self.assertNotIn("FROM ods.ods_douyin_settlement_raw raw", sql_text)
        self.assertIn('raw."佣金"', sql_text)
        self.assertIn('raw."招商服务费"', sql_text)
        self.assertIn("ctx.shop_identity_key", sql_text)
        self.assertIn('raw."动帐流水号"', sql_text)
        self.assertIn("ROW_NUMBER() OVER", sql_text)
        self.assertIn("ORDER BY raw.batch_id DESC, raw.id DESC", sql_text)


if __name__ == "__main__":
    unittest.main()
