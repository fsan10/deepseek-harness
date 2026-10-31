from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone

from .service import AutomationService


class AutomationScheduler:
    def __init__(self, service: AutomationService, *, poll_seconds: int = 30, clock=None) -> None:
        self.service = service
        self.poll_seconds = max(10, min(int(poll_seconds), 300))
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run_once(self) -> list[dict]:
        created: list[dict] = []
        self.service.sync_report_journals()
        for job in self.service.due_jobs(self.clock()):
            if job.get("source_kind") == "flow":
                run, was_created = self.service.create_scheduled_flow_run(
                    str(job["flow_id"]), job["schedule_key"], job["local_date"], "AutomationScheduler"
                )
            else:
                run, was_created = self.service.create_scheduled_run(
                    int(job["job_id"]), job["schedule_key"], job["local_date"], "AutomationScheduler"
                )
            if was_created:
                # Worker owns the gate before any browser operation. Finishing
                # an already queued run here races with Worker claiming it.
                created.append(run)
        return created

    def serve_forever(self) -> None:
        while True:
            try:
                created = self.run_once()
                for run in created:
                    print(f"已创建 Automation Run：{run['automation_run_id']}")
            except Exception as exc:  # scheduler must survive transient database errors
                print(f"AutomationScheduler 扫描失败：{type(exc).__name__}: {exc}")
            time.sleep(self.poll_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Automation Workbench 数据库调度器")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--pg-port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--once", action="store_true")
    return parser


def main() -> int:
    from apps.fund_split_adjust.server import load_project_env

    load_project_env()
    args = build_parser().parse_args()
    args.password = os.getenv("PGPASSWORD")
    scheduler = AutomationScheduler(AutomationService(args), poll_seconds=args.poll_seconds)
    if args.once:
        scheduler.run_once()
        return 0
    print("AutomationScheduler 已启动；计划来自系统任务与已发布 Flow")
    try:
        scheduler.serve_forever()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
