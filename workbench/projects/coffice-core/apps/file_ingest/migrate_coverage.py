"""Apply only the coverage/retry schema; never seed mappings or refresh metrics."""
import argparse
import json
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from etl.common.settlement_sources import load_pg_env

ROOT=Path(__file__).resolve().parents[2]
FILES=('468_ingest_source_day_selection_postgres.sql','436_settlement_source_registry_postgres.sql',
       '460_finance_source_selection_postgres.sql','469_ingest_coverage_workflow_postgres.sql')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',default=str(ROOT/'.env'))
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    load_pg_env(args.env_file)
    with psycopg2.connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout='3s'; SET LOCAL statement_timeout='30s'")
            if args.apply:
                cur.execute("SELECT count(*) n FROM ops.etl_run WHERE status='running'")
                if cur.fetchone()['n']:
                    raise RuntimeError('存在执行中的ETL，请待其结束后应用迁移；本次未修改结构')
                for name in FILES:cur.execute((ROOT/'sql/common'/name).read_text(encoding='utf-8'))
            cur.execute("SELECT to_regclass('common.ingest_source_day_selection') IS NOT NULL AS source_selection_ready")
            status=dict(cur.fetchone())
            cur.execute("""SELECT COUNT(*) AS fields FROM information_schema.columns
                WHERE (table_schema,table_name,column_name) IN
                (('ops','ingest_run','import_mode'),('ops','ingest_run','coverage_preflight'),
                 ('ops','ingest_run','coverage_result'),('ops','ingest_file_task','coverage'),
                 ('ops','etl_run','parent_etl_run_id'))""")
            status['workflow_fields']=cur.fetchone()['fields']
            status['applied']=args.apply
    print(json.dumps(status,ensure_ascii=False))


if __name__=='__main__':main()
