"""Execute scoped SQL regressions and remove the entire temporary DB afterwards."""
import os
import unittest
import uuid

import psycopg2
from psycopg2 import sql
from etl.common.settlement_sources import load_pg_env


def main():
    load_pg_env()
    name='codex_incremental_test_'+uuid.uuid4().hex[:12]
    admin=psycopg2.connect();admin.autocommit=True
    with admin.cursor() as cur:
        cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        os.environ['INCREMENTAL_TEST_DB']=name
        suite=unittest.defaultTestLoader.loadTestsFromName('etl.common.tests.test_refresh_runtime')
        return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1
    finally:
        os.environ.pop('INCREMENTAL_TEST_DB',None)
        with admin.cursor() as cur:
            cur.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        admin.close()


if __name__=='__main__':raise SystemExit(main())
