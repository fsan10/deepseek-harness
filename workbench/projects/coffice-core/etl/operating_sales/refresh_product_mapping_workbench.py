"""Initialize/rebuild only the mapping page snapshot from existing product DWS."""
from __future__ import annotations

import json
import argparse
import os

import psycopg2

from apps.fund_split_adjust.server import load_project_env
from etl.common.product_mapping_workbench import ROOT, create_workbench, lock_product_refresh, publish_workbench


def main():
    # Reuses the untracked project .env for this process only.
    load_project_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default=os.getenv('PGHOST', '192.168.77.111'))
    parser.add_argument('--port', type=int, default=int(os.getenv('PGPORT', '5432')))
    parser.add_argument('--dbname', default=os.getenv('PGDATABASE', 'mock_coffice'))
    parser.add_argument('--user', default=os.getenv('PGUSER', 'postgres'))
    args = parser.parse_args()
    connection = psycopg2.connect(host=args.host, port=args.port, dbname=args.dbname,
                                  user=args.user, password=os.getenv('PGPASSWORD'))
    try:
        with connection:
            with connection.cursor() as cursor:
                lock_product_refresh(cursor)
                create_workbench(cursor)
                cursor.execute("SELECT (completed_at IS NOT NULL OR requested_revision > 1) AND requested_revision > completed_revision "
                               "FROM ops.product_mapping_refresh_state WHERE state_key = 'product_mapping'")
                if cursor.fetchone()[0]:
                    raise RuntimeError('存在尚未处理的配置变更，请先完成商品后台刷新或完整运营成交ETL')
                cursor.execute((ROOT / "sql/common/398_operating_sales_product_code_observation_view_postgres.sql").read_text(encoding="utf-8"))
                result = publish_workbench(cursor)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
