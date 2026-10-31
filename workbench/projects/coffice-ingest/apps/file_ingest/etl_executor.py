"""Internal registered-ETL entrypoint; the executing process owns the global lock."""
from __future__ import annotations

import argparse
import os
import uuid

from .service import FileIngestService, FileIngestWorker


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True, type=uuid.UUID)
    parser.add_argument('--worker-id', required=True, type=uuid.UUID)
    args = parser.parse_args()
    service = FileIngestService(argparse.Namespace(
        host=os.environ['PGHOST'], pg_port=int(os.environ['PGPORT']),
        dbname=os.environ['PGDATABASE'], user=os.environ['PGUSER'],
        password=os.getenv('PGPASSWORD'),
    ))
    connection = service.connect()
    connection.autocommit = True
    worker = None
    try:
        with connection.cursor() as cursor:
            # This connection survives a parent crash and protects the actual ETL
            # until it exits, including its metric transaction's commit/rollback.
            cursor.execute("SELECT pg_advisory_lock(hashtext('mock_coffice_global_etl'))")
            cursor.execute(
                "SELECT 1 FROM ops.etl_run WHERE etl_run_id=%s AND worker_id=%s AND status='running'",
                (str(args.run_id), str(args.worker_id)),
            )
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError('ETL执行归属已失效，停止执行')
        worker = FileIngestWorker(service, worker_name='etl-executor', worker_id=args.worker_id)
        worker._supervised = True
        worker._process_claimed_etl_run(str(args.run_id))
        return 0
    finally:
        try:
            if worker is not None:
                worker.stop()
        finally:
            connection.close()


if __name__ == '__main__':
    raise SystemExit(main())
