"""Execute production settlement SQL against disposable PostgreSQL temp tables.

No ODS, application sessions, audit rows, or persistent metric rows are written.
"""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
import unittest

import psycopg2

from etl.common.settlement_sources import load_pg_env


ROOT = Path(__file__).resolve().parents[3]


class PddSettlementRefundTests(unittest.TestCase):
    def setUp(self):
        load_pg_env()
        self.connection = psycopg2.connect(
            host=os.getenv("PGHOST", "192.168.77.111"),
            port=os.getenv("PGPORT", "5432"),
            dbname=os.getenv("PGDATABASE", "mock_coffice"),
            user=os.getenv("PGUSER", "postgres"),
            password=os.getenv("PGPASSWORD"),
            connect_timeout=10,
            options="-c statement_timeout=10000",
            application_name="pdd_settlement_temp_test",
        )
        self.addCleanup(self.connection.close)
        self.addCleanup(self.connection.rollback)
        self.cursor = self.connection.cursor()
        for name in ("income_source", "expense_source", "net_source"):
            self.cursor.execute(f"""CREATE TEMP TABLE {name} (
                stat_date DATE DEFAULT '2026-09-01', platform_code TEXT DEFAULT 'pdd',
                platform_name TEXT DEFAULT 'test', shop_code TEXT DEFAULT 'test',
                shop_name TEXT DEFAULT 'test', account_type TEXT, business_description TEXT,
                income_amount NUMERIC(18,2), expense_amount NUMERIC(18,2),
                source_signed_expense_amount NUMERIC(18,2),
                source_settlement_amount NUMERIC(18,2),
                source_updated_at TIMESTAMPTZ DEFAULT NOW()
            ) ON COMMIT DROP""")
        self.cursor.execute("""CREATE TEMP TABLE income_result (
            stat_date DATE,platform_code TEXT,platform_name TEXT,shop_code TEXT,shop_name TEXT,
            income_type_code TEXT,income_type_name TEXT,income_amount NUMERIC(18,2),
            included_event_count BIGINT,source_updated_at TIMESTAMPTZ,updated_at TIMESTAMPTZ
        ) ON COMMIT DROP""")
        self.cursor.execute("""CREATE TEMP TABLE expense_result (
            stat_date DATE,platform_code TEXT,platform_name TEXT,shop_code TEXT,shop_name TEXT,
            expense_type_code TEXT,expense_type_name TEXT,expense_amount NUMERIC(18,2),
            included_event_count BIGINT,source_updated_at TIMESTAMPTZ,updated_at TIMESTAMPTZ
        ) ON COMMIT DROP""")
        self.cursor.execute("""CREATE TEMP TABLE net_result (
            stat_date DATE,platform_code TEXT,platform_name TEXT,shop_code TEXT,shop_name TEXT,
            income_amount NUMERIC(18,2),expense_amount NUMERIC(18,2),
            display_expense_amount NUMERIC(18,2),settlement_net_amount NUMERIC(18,2),
            source_settlement_amount NUMERIC(18,2),validation_difference_amount NUMERIC(18,2),
            included_event_count BIGINT,source_updated_at TIMESTAMPTZ,updated_at TIMESTAMPTZ
        ) ON COMMIT DROP""")

    def refresh(self, rows):
        for table in ("income_source", "expense_source", "net_source"):
            self.cursor.executemany(f"""INSERT INTO pg_temp.{table} (
                account_type,business_description,income_amount,source_signed_expense_amount,
                expense_amount,source_settlement_amount
            ) VALUES (%s,%s,%s,%s,-%s::numeric,%s::numeric+%s::numeric)""",
                [(typ, desc, income, expense, expense, income, expense)
                 for typ, desc, income, expense in rows])
        names = {
            "dwd.dwd_pdd_settlement_income_event_detail": "pg_temp.income_source",
            "dwd.dwd_pdd_settlement_expense_event_detail": "pg_temp.expense_source",
            "dwd.dwd_pdd_settlement_net_event_detail": "pg_temp.net_source",
            "dws.dws_pdd_settlement_income_shop_daily_type": "pg_temp.income_result",
            "dws.dws_pdd_settlement_expense_shop_daily_type": "pg_temp.expense_result",
            "dws.dws_pdd_settlement_net_shop_daily": "pg_temp.net_result",
        }
        for relative_path in (
            "pdd/settlement_income/111_refresh_dws_pdd_settlement_income_shop_daily_type_postgres.sql",
            "pdd/settlement_expense/115_refresh_dws_pdd_settlement_expense_shop_daily_type_postgres.sql",
            "pdd/settlement_net/119_refresh_dws_pdd_settlement_net_shop_daily_postgres.sql",
        ):
            query = (ROOT / "sql" / relative_path).read_text(encoding="utf-8")
            for original, temporary in names.items():
                query = query.replace(original, temporary)
            self.cursor.execute(query)

    def assert_totals(self, income, expense, net, rows):
        self.cursor.execute("""SELECT income_amount,expense_amount,display_expense_amount,
            settlement_net_amount,source_settlement_amount,validation_difference_amount,
            included_event_count FROM pg_temp.net_result""")
        self.assertEqual(self.cursor.fetchone(),
                         (Decimal(income), Decimal(expense), -Decimal(expense),
                          Decimal(net), Decimal(net), Decimal("0"), rows))
        for table, column, expected in (("income_result", "income_amount", income),
                                        ("expense_result", "expense_amount", expense)):
            self.cursor.execute(f"SELECT COALESCE(SUM({column}),0) FROM pg_temp.{table}")
            self.assertEqual(self.cursor.fetchone()[0], Decimal(expected))
        self.cursor.execute("""SELECT
            (SELECT COALESCE(SUM(included_event_count),0) FROM pg_temp.income_result)+
            (SELECT COALESCE(SUM(included_event_count),0) FROM pg_temp.expense_result)""")
        self.assertEqual(self.cursor.fetchone()[0], rows)

    def test_refunds_move_once_and_transfers_and_fee_returns_stay(self):
        self.refresh([
            ("交易收入", "0010002|订单收入", "100", "0"),
            ("优惠券结算", "0010005|优惠券收入", "10", "0"),
            ("退款", "0020002|订单退款", "0", "-30"),
            ("优惠券结算", "0020005|优惠券退款", "0", "-5"),
            ("退款", "0040003|运费补偿", "0", "-2"),
            ("技术服务费", "0030002|技术服务费返还", "3", "0"),
            ("技术服务费", "0030002|技术服务费", "0", "-4"),
            ("提现", "0080001|提现", "0", "-20"),
            ("转账", "0070004|广告账户", "0", "-10"),
            ("扣款", "0040003|运费补偿", "0", "-6"),
            ("其他", None, "0", "-2"),
        ])
        self.assert_totals("76", "42", "34", 11)
        self.cursor.execute("SELECT income_amount,included_event_count FROM pg_temp.income_result WHERE income_type_code='coupon_settlement'")
        self.assertEqual(self.cursor.fetchone(), (Decimal("5"), 2))

    def test_refund_only_day_keeps_negative_income(self):
        self.refresh([("退款", "0020002|订单退款", "0", "-12")])
        self.assert_totals("-12", "0", "-12", 1)

    def test_coupon_code_controls_refund_instead_of_description_words(self):
        self.refresh([
            ("优惠券结算", "0020005|描述变更", "0", "-5"),
            ("优惠券结算", "0010005|退款字样", "0", "-7"),
            ("优惠券结算", "0010005|正常收入", "10", "0"),
        ])
        self.assert_totals("5", "7", "-2", 3)

    def test_monthly_view_uses_upstream_display_and_preserves_other_platform(self):
        self.cursor.execute("""CREATE TEMP TABLE monthly_source (
            stat_month DATE,platform_code TEXT,platform_name TEXT,company_code TEXT,
            company_name TEXT,shop_code TEXT,shop_name TEXT,income_amount NUMERIC(18,2),
            expense_amount NUMERIC(18,2),display_expense_amount NUMERIC(18,2),
            settlement_net_amount NUMERIC(18,2)
        ) ON COMMIT DROP""")
        self.cursor.execute("""INSERT INTO pg_temp.monthly_source VALUES
            ('2026-09-01','pdd','pdd','test','test','test','test',76,42,-42,34),
            ('2026-09-01','jd','jd','test','test','test','test',75,41,NULL,34)""")
        query = (ROOT / "sql/ads/settlement_net/418_view_settlement_net_company_shop_monthly_metric_postgres.sql").read_text(encoding="utf-8")
        query = query.replace("CREATE SCHEMA IF NOT EXISTS ads;", "")
        query = query.replace("ads.ads_settlement_net_company_shop_monthly", "pg_temp.monthly_source")
        query = query.replace("ads.v_settlement_net_company_shop_monthly_metric", "pg_temp.monthly_metrics")
        self.cursor.execute(query)
        self.cursor.execute("SELECT platform_code,metric_code,amount FROM pg_temp.monthly_metrics ORDER BY 1,2")
        self.assertEqual(self.cursor.fetchall(), [
            ("jd", "expense", Decimal("41")), ("jd", "income", Decimal("75")),
            ("jd", "settlement_net", Decimal("34")),
            ("pdd", "expense", Decimal("-42")), ("pdd", "income", Decimal("76")),
            ("pdd", "settlement_net", Decimal("34")),
        ])


if __name__ == "__main__":
    unittest.main()
