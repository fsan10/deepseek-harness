"""Deployment checks for the report calendar; never runs a download or ETL."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from apps.automation_center.service import AutomationService
from apps.fund_split_adjust.server import load_project_env


def service_from_env(root: Path | None = None) -> AutomationService:
    load_project_env()
    args = argparse.Namespace(host=os.getenv("PGHOST", "192.168.77.111"), pg_port=int(os.getenv("PGPORT", "5432")),
                              dbname=os.getenv("PGDATABASE", "mock_coffice"), user=os.getenv("PGUSER", "postgres"),
                              password=os.getenv("PGPASSWORD"))
    return AutomationService(args, archive_root=root)


def main():
    parser = argparse.ArgumentParser(description="报表日历迁移与只读部署核验")
    parser.add_argument("action", choices=("migrate", "check", "sync"))
    args = parser.parse_args()
    service = service_from_env()
    if args.action == "migrate":
        path = Path(__file__).resolve().parents[2]/"sql/common/432_automation_report_calendar_postgres.sql"
        with service.transaction() as cursor:
            cursor.execute(path.read_text(encoding="utf-8"))
        print("报表日历迁移完成（只涉及自动化运行与归档元数据）")
    elif args.action == "sync":
        print(f"已同步外部运行：{service.sync_report_journals()}")
    else:
        inventory = service.report_targets(refresh=True)
        print(f"当前报表清单：{len({t['profile_name'] for t in inventory['items']})} 个Profile，{len(inventory['items'])} 类店铺报表")
        from apps.automation_center.report_plan import china_today
        calendar = service.report_calendar({'month':china_today().strftime('%Y-%m')})
        print(f"报表日历：{calendar['month']}，{len(calendar['days'])} 天，读取成功")
        with service.transaction() as cursor:
            cursor.execute("SELECT job_code,enabled,schedule_type FROM ops.automation_job WHERE job_code='platform_download_backfill'")
            row = cursor.fetchone()
            print("补跑任务：" + ("已启用，手动触发" if row and row["enabled"] and row["schedule_type"] == "manual" else "配置未就绪"))


if __name__ == "__main__":
    main()
