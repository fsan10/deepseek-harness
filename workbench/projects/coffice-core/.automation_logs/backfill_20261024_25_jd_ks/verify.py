import hashlib
import json
import os
from pathlib import Path
from collections import Counter
from openpyxl import load_workbook
from apps.fund_split_adjust.server import load_project_env
from scripts.auto_download.ingest_api import _request
from scripts.auto_download.ledger import atomic_json

load_project_env()
root = Path(__file__).resolve().parent
dest = Path(r"C:\Users\win\Desktop\data")
logs = dest / ".automation_logs/all_platform_downloads"
day24 = json.loads((root / "day24_ingest_retry.json").read_text(encoding="utf-8"))
day25 = json.loads((logs / "20261026_103255_b390a725.summary.json").read_text(encoding="utf-8"))
assert day24["status"] == day25["status"] == "success"
assert day25["business_date"] == "2026-10-25"
assert day25["plan_count"] == day25["lane_plan_count"] == 4
assert not day25["warnings"] and not day25["cleanup_errors"]
results = [("2026-10-24",day24["profile"],day24["result"])]
for profile in day25["profiles"]:
    assert profile["status"] == "success"
    for step in profile["steps"]:
        assert step["status"] in {"success","skipped_checkpoint"} and step["return_code"] == 0
        if step["module"] in {"jd_order_download","kuaishou_order_download"}:
            results.append(("2026-10-25",profile["profile"],step))
        else:
            assert step["status"] == "skipped_checkpoint"
assert len(results) == 5
output = []
for day,profile,step in results:
    cp = json.loads((logs / f"checkpoints/checkpoint_{day}.json").read_text(encoding="utf-8"))
    assert cp["scope"] == day
    record = cp["profiles"][profile]["steps"][f"订单|{step['module']}|[]"]
    assert record["status"] == "success" and record["return_code"] == 0
    for artifact in step["artifacts"]:
        report = (dest / artifact["relative_path"]).resolve()
        assert report.is_relative_to(dest.resolve())
        assert report.stat().st_size == artifact["file_size_bytes"]
        assert hashlib.sha256(report.read_bytes()).hexdigest() == artifact["file_hash"]
        workbook = load_workbook(report,read_only=True,data_only=True)
        try:
            assert workbook.sheetnames
            row_counts = []
            for sheet in workbook:
                sheet.reset_dimensions()
                row_counts.append(sum(1 for row in sheet.iter_rows(values_only=True) if any(cell is not None for cell in row)))
            rows = sum(row_counts)
        finally:
            workbook.close()
    run_id = step["ingest"]["ingest_run_id"]
    data = _request(os.getenv("INGEST_API_BASE_URL","http://127.0.0.1:8770").rstrip("/"),os.environ["INGEST_ROBOT_TOKEN"],
        f"/api/ingest/runs/{run_id}",None,"application/json","",method="GET")
    run = data.get("run") or data
    assert run.get("status") == "success"
    assert data.get("files") and all(item["status"] == "success" and item["loader_exit_code"] == 0 for item in data["files"])
    output.append({"day":day,"profile":profile,"archive_verified":True,"workbook_rows":rows,
        "checkpoint_status":record["status"],"ingest_run_id":run_id,"ingest_status":run.get("status"),
        "file_statuses":dict(Counter(item.get("status") for item in data.get("files",[]))),
        "loader_exit_codes":[item["loader_exit_code"] for item in data["files"]],
        "task_statuses":dict(Counter(item.get("status") for item in data.get("tasks",[])))})
atomic_json(root / "verification.json",{"results":output})
print(json.dumps({"results":output},ensure_ascii=False))
