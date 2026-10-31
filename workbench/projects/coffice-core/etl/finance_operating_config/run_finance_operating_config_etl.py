#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""创建并刷新经营预算、GSV目标、推广充值和整体营销费用指标链路。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg2


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_FILES = (
    "common/383_finance_operating_configuration_postgres.sql",
    "common/384_dwd_finance_operating_configuration_detail_postgres.sql",
    "common/385_dws_finance_operating_configuration_monthly_postgres.sql",
    "ads/386_ads_finance_operating_configuration_monthly_postgres.sql",
    "common/387_refresh_dwd_finance_operating_configuration_detail_postgres.sql",
    "common/388_refresh_dws_finance_operating_configuration_monthly_postgres.sql",
    "ads/389_refresh_ads_finance_operating_configuration_monthly_postgres.sql",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新经营预算配置DWD/DWS/ADS。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    connection = psycopg2.connect(host=args.host, port=args.port, dbname=args.dbname, user=args.user, password=args.password)
    try:
        with connection.cursor() as cursor:
            for relative in SQL_FILES:
                cursor.execute((PROJECT_ROOT / "sql" / relative).read_text(encoding="utf-8"))
            cursor.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM dwd.dwd_finance_operating_configuration_detail),
                  (SELECT COUNT(*) FROM dws.dws_finance_operating_shop_monthly),
                  (SELECT COUNT(*) FROM dws.dws_finance_operating_global_monthly),
                  (SELECT COUNT(*) FROM ads.ads_finance_promotion_budget_company_shop_monthly),
                  (SELECT COUNT(*) FROM ads.ads_finance_budget_global_monthly)
                """
            )
            counts = cursor.fetchone()
        connection.commit()
        print("经营预算配置ETL完成：DWD=%s，店铺DWS=%s，整体DWS=%s，店铺ADS=%s，整体ADS=%s" % counts)
        return 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
