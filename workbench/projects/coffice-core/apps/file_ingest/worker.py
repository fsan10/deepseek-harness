from __future__ import annotations

import argparse
import os
import time

from .service import FileIngestService, FileIngestWorker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="数据导入与ETL串行Worker")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--pg-port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--migrate", action="store_true")
    parser.add_argument("--migrate-only", action="store_true", help="仅执行导入中心结构迁移，不领取导入或ETL任务。")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    service = FileIngestService(args)
    if args.migrate or args.migrate_only:
        for name in service.migrate():
            print(f"已执行SQL：{name}")
    if args.migrate_only:
        return 0
    worker = FileIngestWorker(service)
    recovered = worker.recover_stale()
    if any(recovered.values()):
        print(f"已处理中断任务：{recovered}")
    if args.once:
        try:
            worker.run_once()
        finally:
            worker.stop()
        return 0
    print("数据导入Worker已启动，按Ctrl+C退出")
    try:
        while True:
            if not worker.run_once():
                time.sleep(max(0.5, min(args.poll_seconds, 30)))
    except KeyboardInterrupt:
        return 0
    finally:
        worker.stop()


if __name__ == "__main__":
    raise SystemExit(main())
