"""Run the user-authorized historical recoveries through the ordinary controller."""
import copy
import hashlib
import json
import logging
import sys
import uuid
from datetime import date
from pathlib import Path

from scripts.auto_download.run_all_platform_downloads import (
    ControllerRunLock, ResumeCheckpoint, DownloadController, configure_logger, load_config, redact,
)
from apps.fund_split_adjust.server import load_project_env
from scripts.auto_download.ledger import atomic_json, RunJournal

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(__file__).resolve().parent
DEST = Path(r"C:\Users\win\Desktop\data")
LOGS = DEST / ".automation_logs/all_platform_downloads"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def retry_archived_day24():
    """Retry only the already-downloaded artifact using the authorized automation API."""
    from scripts.auto_download.ingest_api import submit_archived_reports
    from apps.automation_center.report_plan import china_today
    original_run = "20261026_102845_32c323d6"
    ledger = json.loads((DEST / ".automation_logs/report_ledger" / f"{original_run}.json").read_text(encoding="utf-8"))
    payload = next(item["payload"] for item in ledger["events"] if item["event"] == "step_downloaded"
        and item["payload"].get("module_name") == "jd_order_download")
    assert payload["return_code"] == 0 and payload["artifacts"]
    config = json.loads((CONFIG_DIR / "day24.json").read_text(encoding="utf-8"))
    plan = config["profiles"][0]
    metadata = plan["expected_metadata"]
    assert payload["metadata"] == metadata
    for artifact in payload["artifacts"]:
        path = (DEST / artifact["relative_path"]).resolve()
        assert path.is_relative_to(DEST.resolve()) and digest(path) == artifact["file_hash"]
        assert artifact["business_date_start"] == "2026-09-24" and artifact["business_date_end"] == "2026-10-24"
    run_id = "20261026_jd24_ingest_retry_" + uuid.uuid4().hex[:8]
    logger = logging.getLogger("historical_ingest_retry")
    lock = ControllerRunLock(path=LOGS / "controller.lock",wait_seconds=0,run_id=run_id,execution_lane="interactive",logger=logger)
    lock.acquire()
    try:
        journal = RunJournal(DEST,run_id,"interactive",trigger_type="retry")
        journal.emit("started",{"date":"2026-10-24"})
        journal.emit("step_started",payload)
        ingest = submit_archived_reports(DEST,payload["artifacts"],metadata=metadata,report_types=["jd_order"],source="api")
        assert ingest["submitted"] == 1 and ingest["ingest_run_id"]
        result = {"name":"订单","module":"jd_order_download","status":"success","return_code":0,
            "execution_lane":"interactive","started_at":payload["started_at"],"finished_at":payload["finished_at"],
            "duration_seconds":payload["duration_seconds"],"artifacts":payload["artifacts"],"ingest":ingest}
        fingerprint = hashlib.sha256(json.dumps(config,ensure_ascii=False,sort_keys=True,separators=(",", ":")).encode()).hexdigest()
        context_hash = hashlib.sha256(json.dumps({"project_root":str(ROOT.resolve()),"destination":str(DEST.resolve())},ensure_ascii=False,sort_keys=True,separators=(",", ":")).encode()).hexdigest()
        checkpoint = ResumeCheckpoint(path=LOGS / "checkpoints/checkpoint_2026-10-24.json",scope="2026-10-24",
            config_fingerprint=fingerprint,logger=logger,execution_context_fingerprint=context_hash,require_scope_match=True)
        before = copy.deepcopy(checkpoint.data["profiles"])
        checkpoint.record_success(plan["profile_name"],metadata,plan["steps"][0],result)
        checkpoint.record_success(plan["profile_name"],metadata,{"name":"订单","module":"jd_order_download","args":[]},result)
        for name, entry in before.items():
            for key,value in entry["steps"].items():
                assert checkpoint.data["profiles"][name]["steps"][key] == value
        journal.emit("step_succeeded",{**payload,**result})
        journal.emit("run_finished",{"status":"success"})
        receipt = {"run_id":run_id,"source_download_run":original_run,"business_date":"2026-10-24",
            "trigger_type":"retry","status":"success","profile":plan["profile_name"],"result":result}
        atomic_json(CONFIG_DIR / "day24_ingest_retry.json",receipt)
        print(json.dumps({"day":"2026-10-24","status":"success","reused_archived_file":True,"ingest_submitted":1},ensure_ascii=False),flush=True)
    finally:
        lock.release()


def execute_retry(day,config_path):
    """Use the controller's existing retry origin and API robot identity."""
    from scripts.auto_download.run_all_platform_downloads import china_now
    run_id = china_now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    logger = configure_logger(LOGS / f"{run_id}.log")
    lock = ControllerRunLock(path=LOGS / "controller.lock",wait_seconds=21600,
        run_id=run_id,execution_lane="interactive",logger=logger)
    lock.acquire()
    controller = None
    try:
        config = load_config(config_path)
        controller = DownloadController(config=config,config_path=config_path,destination=DEST,logger=logger,
            run_id=run_id,summary_path=LOGS / f"{run_id}.summary.json",mcp_url=config["mcp_url"],
            checkpoint_scope=day,execution_lane="interactive",business_date=date.fromisoformat(day),
            require_daily_checkpoint=True,trigger_type="retry")
        code = controller.run()
        controller.write_summary()
        return code
    except Exception as exc:
        logger.exception("历史自动化重试失败：%s",redact(exc))
        if controller:
            controller.summary["status"] = "failed"
            controller.summary["error"] = redact(exc)
            controller.write_summary()
        return 1
    finally:
        lock.release()


def reconcile(day, config):
    summaries = []
    for path in LOGS.glob("*.summary.json"):
        if path.stat().st_mtime < RUN_STARTED:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("business_date") == day and Path(data["config"]).resolve() == config.resolve():
            summaries.append((path, data))
    assert len(summaries) == 1, "Expected one completed historical controller summary"
    path, summary = summaries[0]
    assert summary["status"] in {"success", "success_with_warnings"}
    source_config = json.loads(config.read_text(encoding="utf-8"))
    ordinary_config = json.loads((ROOT / "scripts/auto_download/all_platform_downloads.json").read_text(encoding="utf-8"))
    logger = logging.getLogger("verified_historical_recovery")
    lock = ControllerRunLock(path=LOGS / "controller.lock", wait_seconds=0,
        run_id=summary["run_id"] + "_verified_registration", execution_lane="interactive", logger=logger)
    lock.acquire()
    try:
        config_hash = hashlib.sha256(json.dumps(ordinary_config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        context_hash = hashlib.sha256(json.dumps({"project_root":str(ROOT.resolve()), "destination":str(DEST.resolve())},ensure_ascii=False,sort_keys=True,separators=(",", ":")).encode()).hexdigest()
        checkpoint = ResumeCheckpoint(path=LOGS / f"checkpoints/checkpoint_{day}.json",scope=day,
            config_fingerprint=config_hash,execution_context_fingerprint=context_hash,require_scope_match=True,logger=logger)
        before = copy.deepcopy(checkpoint.data["profiles"])
        files = 0
        for profile in summary["profiles"]:
            assert profile["status"] == "success"
            metadata = {key:profile[key] for key in ("platform","company","shop")}
            plan = next(item for item in source_config["profiles"] if item["profile_name"] == profile["profile"])
            for result in profile["steps"]:
                assert result["status"] in {"success","skipped_checkpoint"} and result["return_code"] == 0
                if result["module"] not in {"jd_order_download","kuaishou_order_download"}:
                    assert result["status"] == "skipped_checkpoint", "Do not replay successful non-order steps"
                    continue
                step = next(item for item in plan["steps"] if item["module"] == result["module"])
                source = checkpoint.successful_step(profile["profile"],metadata,step)
                assert source and source["finished_at"] == result["finished_at"]
                assert result["artifacts"], "Real successful report artifact required"
                for artifact in result["artifacts"]:
                    report = (DEST / artifact["relative_path"]).resolve()
                    assert report.is_relative_to(DEST.resolve()) and report.stat().st_size == artifact["file_size_bytes"]
                    assert digest(report) == artifact["file_hash"] and report.name.startswith(day.replace("-", ""))
                    files += 1
                canonical = {"name":step["name"],"module":step["module"],"args":[]}
                existing = checkpoint.successful_step(profile["profile"],metadata,canonical)
                if existing:
                    assert existing["finished_at"] == result["finished_at"]
                else:
                    checkpoint.record_success(profile["profile"],metadata,canonical,result)
        for name, entry in before.items():
            for key, value in entry["steps"].items():
                assert checkpoint.data["profiles"][name]["steps"][key] == value
        print(json.dumps({"day":day,"summary":str(path),"status":summary["status"],"verified_report_files":files,"normal_checkpoint_registered":True},ensure_ascii=False),flush=True)
    finally:
        lock.release()


if __name__ == "__main__":
    import time
    load_project_env()
    RUN_STARTED = time.time()
    original_config = ROOT / "scripts/auto_download/all_platform_downloads.json"
    today_checkpoint = LOGS / "checkpoints/checkpoint_2026-10-26.json"
    original_hash, today_hash = digest(original_config), digest(today_checkpoint)
    baseline = json.loads(original_config.read_text(encoding="utf-8"))
    historical24 = json.loads((LOGS / "checkpoints/checkpoint_2026-10-24.json").read_text(encoding="utf-8"))
    if historical24["profiles"]["JD-京东-MOCK饮品旗舰店"]["steps"].get("订单|jd_order_download|[]",{}).get("status") != "success":
        retry_archived_day24()
    for day, filename in (("2026-10-24","day24.json"),("2026-10-25","day25.json")):
        config = CONFIG_DIR / filename
        plans = json.loads(config.read_text(encoding="utf-8"))["profiles"]
        old = json.loads((LOGS / f"checkpoints/checkpoint_{day}.json").read_text(encoding="utf-8"))
        for plan in plans:
            status = baseline.get("profile_status",{}).get(plan["profile_name"],{})
            assert status.get("enabled",True) and status.get("status","active") in {"active","正常","启用","运行"}
            identity = {key:old["profiles"][plan["profile_name"]][key] for key in ("platform","company","shop")}
            assert identity == plan["expected_metadata"]
            for step in plan["steps"][1:]:
                record = old["profiles"][plan["profile_name"]]["steps"].get(ResumeCheckpoint.step_key(step))
                assert record and record["status"] == "success", "Historical non-order success missing"
        if all(old["profiles"][plan["profile_name"]]["steps"].get(ResumeCheckpoint.step_key(
            {"name":"订单","module":plan["steps"][0]["module"],"args":[]}),{}).get("status") == "success" for plan in plans):
            print(json.dumps({"day":day,"status":"skipped_checkpoint"}),flush=True)
            continue
        code = execute_retry(day,config)
        if code:
            raise SystemExit(code)
        reconcile(day,config)
        assert digest(original_config) == original_hash and digest(today_checkpoint) == today_hash
