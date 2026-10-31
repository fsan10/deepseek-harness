"""多平台指标队列、日级检查点与定时执行；正式采集没有浏览器依赖。"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .review_config import PROJECT, load_runtime_env
load_runtime_env()
from .collection_alerts import flush_alerts, queue_alert
from .metric_collect import fetch_metrics
from .metric_parsers import NoMetricData
from .metric_profiles import PLATFORMS
from .review_errors import AccountUnavailable, AuthRequired, ContractError, HumanRequired, NetworkError, ReviewError

CN = timezone(timedelta(hours=8))


def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path():
    configured = Path(os.environ.get("KEFU_DB_PATH") or PROJECT / "data" / "kefu.sqlite")
    return configured if configured.is_absolute() else PROJECT / configured


def connect():
    path = db_path(); path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    from .collection_accounts import initialize_accounts
    initialize_accounts(db)
    return db


def period(start, end, lookback=1):
    try:
        yesterday = datetime.now(CN).date() - timedelta(days=1)
        last = date.fromisoformat(end) if end else yesterday
        first = date.fromisoformat(start) if start else last - timedelta(days=lookback - 1)
        if first > last or last > yesterday or (last - first).days >= 31: raise ValueError()
        return first, last
    except (ValueError, TypeError):
        raise ContractError("请选择不晚于昨天、单次最多 31 天的有效日期范围") from None


def selected_profiles(db, kind, identifiers, *, skip_unavailable=False):
    if kind not in ("reception", "score"): raise ContractError("采集类型无效")
    if not isinstance(identifiers, list) or len(identifiers) > 100 or any(not isinstance(i, str) or len(i) > 100 for i in identifiers):
        raise ContractError("店铺选择参数无效")
    profiles = [dict(p) for p in db.execute("SELECT * FROM metric_profiles ORDER BY platform,profile_name")]
    known = {p["profile_id"]: p for p in profiles}
    valid = {p["profile_id"]: p for p in profiles if not p["excluded"] and not p["disabled"] and p["shop_name"] and p[kind + "_enabled"] and p["collect_" + kind]}
    for identifier in identifiers:
        profile = known.get(identifier)
        can_skip = profile and skip_unavailable and (profile["excluded"] or profile["disabled"] or not profile["collect_" + kind])
        if profile is None or identifier not in valid and not can_skip:
            raise ContractError("所选店铺已停用、移除、未配置映射或不支持此类采集")
    chosen = [valid[i] for i in dict.fromkeys(identifiers) if i in valid] if identifiers else list(valid.values())
    if not chosen: raise ContractError("没有可采集店铺，请先同步并核对映射和能力范围")
    return chosen


def reception_checkpoints(db, profile_ids, first, last, *, exclude_run=""):
    """按精确 profile 和业务日期复用真实入库回执，不依赖任务的触发方式或整体状态。"""
    if not profile_ids or first > last:
        return {}
    placeholders = ",".join("?" for _ in profile_ids)
    rows = db.execute(f"""SELECT i.* FROM metric_run_items i
        JOIN metric_runs r ON r.id=i.run_id JOIN metric_profiles p ON p.profile_id=i.profile_id
        WHERE r.kind='reception' AND i.run_id<>? AND i.profile_id IN ({placeholders})
        AND i.requested_date BETWEEN ? AND ? AND i.status='success' AND i.report_date=i.requested_date
        AND i.record_count=1 AND i.import_request_id<>'' AND i.payload_sha256<>''
        AND p.excluded=0 AND p.disabled=0 AND p.collect_reception=1 AND p.reception_enabled=1
        ORDER BY i.collected_at DESC,i.finished_at DESC,r.created_at DESC""",
        (exclude_run, *profile_ids, first, last)).fetchall()
    result = {}
    for row in rows:
        result.setdefault((row["profile_id"], row["requested_date"]), row)
    return result


def reuse_reception_checkpoints(db, run_id, checkpoints):
    for item in checkpoints.values():
        db.execute("""UPDATE metric_run_items SET status='success',message=?,error_code='',report_date=?,
            record_count=?,source_metric=?,import_request_id=?,payload_sha256=?,collected_at=?,finished_at=?
            WHERE run_id=? AND profile_id=? AND requested_date=? AND status='pending'""",
            (f"复用已成功入库的同店同日接待量（任务 {item['run_id']}）", item["report_date"], item["record_count"],
             item["source_metric"], item["import_request_id"], item["payload_sha256"], item["collected_at"],
             item["finished_at"], run_id, item["profile_id"], item["requested_date"]))


def enqueue(db, body):
    if not isinstance(body, dict): raise ContractError("请求需要 JSON 对象")
    kind = body.get("kind")
    if kind not in ("reception", "score"): raise ContractError("采集类型无效")
    db.execute("BEGIN IMMEDIATE")
    try:
        action = body.get("action", "collect")
        if action in ("cancel", "retry"):
            run_id = body.get("runId")
            if not isinstance(run_id, str) or len(run_id) > 100: raise ContractError("任务标识无效")
            run = db.execute("SELECT * FROM metric_runs WHERE id=? AND kind=?", (run_id, kind)).fetchone()
            if not run: raise ContractError("找不到该采集任务")
            if action == "cancel":
                if run["status"] not in ("queued", "running"): raise ContractError("该任务已经结束")
                db.execute("UPDATE metric_runs SET status='cancelled',message='用户已取消，成功检查点已保留',finished_at=? WHERE id=?", (now(), run_id))
                db.execute("UPDATE metric_run_items SET status='cancelled',message='用户已取消' WHERE run_id=? AND status IN('pending','running')", (run_id,))
            else:
                if run["status"] not in ("partial", "failed", "needs_human", "cancelled"): raise ContractError("该任务无需重试")
                if db.execute("SELECT 1 FROM metric_runs WHERE kind=? AND status IN('queued','running')", (kind,)).fetchone(): raise ContractError("已有同类任务在排队或运行")
                db.execute("UPDATE metric_run_items SET status='pending',message='',error_code='',finished_at=NULL WHERE run_id=? AND status NOT IN('success','no_data','skipped')", (run_id,))
                if kind == "reception" and run["trigger_type"] == "scheduled":
                    profiles = [row[0] for row in db.execute("SELECT DISTINCT profile_id FROM metric_run_items WHERE run_id=? AND status='pending'", (run_id,))]
                    reuse_reception_checkpoints(db, run_id, reception_checkpoints(db, profiles, run["start_date"], run["end_date"], exclude_run=run_id))
                db.execute("UPDATE metric_runs SET status='queued',message='等待重试未完成店铺和日期',finished_at=NULL WHERE id=?", (run_id,))
            db.commit()
            return {"id": run_id, "status": "cancelled" if action == "cancel" else "queued"}
        if db.execute("SELECT 1 FROM metric_runs WHERE kind=? AND status IN('queued','running')", (kind,)).fetchone(): raise ContractError("已有同类任务在排队或运行")
        chosen = selected_profiles(db, kind, body.get("profileIds", []), skip_unavailable=body.get("trigger_type") == "scheduled")
        settings = db.execute("SELECT * FROM metric_collection_settings WHERE kind=?", (kind,)).fetchone()
        checkpoints = {}
        if kind == "score":
            if body.get("from") or body.get("to"): raise ContractError("体验分仅采集接口最新快照，不允许把当前分数回填历史日期")
            days = ["latest"]; first = last = "latest"
        else:
            start, end = period(body.get("from"), body.get("to"), settings["lookback_days"])
            if body.get("trigger_type") == "scheduled":
                # 历史缺口按店铺逐日认定，手动补采同样有效；配置的回溯窗口仍按原计划采集。
                lookback_first = end - timedelta(days=settings["lookback_days"] - 1)
                checkpoints = reception_checkpoints(db, [p["profile_id"] for p in chosen], start.isoformat(),
                    (lookback_first - timedelta(days=1)).isoformat())
                while start < lookback_first and all((p["profile_id"], start.isoformat()) in checkpoints for p in chosen):
                    start += timedelta(days=1)
            first, last = start.isoformat(), end.isoformat()
            days = [(start + timedelta(days=n)).isoformat() for n in range((end - start).days + 1)]
        run_id = str(uuid.uuid4())
        db.execute("INSERT INTO metric_runs(id,kind,trigger_type,start_date,end_date,profile_ids,created_at) VALUES(?,?,?,?,?,?,?)",
            (run_id, kind, body.get("trigger_type", "manual"), first, last, json.dumps([p["profile_id"] for p in chosen]), now()))
        db.executemany("INSERT INTO metric_run_items(run_id,profile_id,requested_date) VALUES(?,?,?)", [(run_id, p["profile_id"], day) for p in chosen for day in days])
        reuse_reception_checkpoints(db, run_id, checkpoints)
        db.commit()
        return {"id": run_id, "status": "queued", "items": len(chosen) * len(days)}
    except Exception:
        db.rollback(); raise


async def import_records(records, request_id, *, transport=None):
    key = os.environ.get("IMPORT_API_KEY", "")
    base = os.environ.get("KEFU_IMPORT_BASE_URL", "http://127.0.0.1:3000").rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ContractError("内部导入地址必须是本机 HTTP 服务，不允许向外部发送密钥")
    if not key: raise ContractError("未配置 IMPORT_API_KEY，请在 .env.local 配置后重启服务")
    if not records or len(records) > 200: raise ContractError("单店单日指标数量必须为 1 至 200 条，未写入任何数据")
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=45, transport=transport) as client:
        for dry_run in (True, False):
            try:
                response = await client.post(base + "/api/import", headers={"Authorization": "Bearer " + key},
                    json={"requestId": request_id + ("-validate" if dry_run else ""), "source": "商家WebAPI", "dryRun": dry_run, "records": records})
                body = response.json()
            except (httpx.RequestError, ValueError):
                raise NetworkError("本地导入接口不可用；请保持客服网页服务运行后重试") from None
            if response.status_code != 200 or body.get("ok") is not True:
                raise ContractError(f"本地导入校验或写入失败（HTTP {response.status_code}），请核对店铺范围与导入密钥")
            expected = body.get("valid" if dry_run else "processed")
            if expected != len(records): raise ContractError("本地导入回执数量与指标数量不一致")
    return len(records)


async def execute_run(db, run):
    run_id = run["id"]
    with db:
        db.execute("UPDATE metric_runs SET status='running',started_at=COALESCE(started_at,?),heartbeat_at=?,message='正在检查 HTTP 登录状态' WHERE id=? AND status='queued'", (now(), now(), run_id))
    try:
        items = db.execute("SELECT * FROM metric_run_items WHERE run_id=? AND status NOT IN('success','no_data','skipped') ORDER BY profile_id,requested_date", (run_id,)).fetchall()
        blocked = {}
        for item in items:
            if db.execute("SELECT status FROM metric_runs WHERE id=?", (run_id,)).fetchone()[0] != "running": return
            profile = dict(db.execute("SELECT * FROM metric_profiles WHERE profile_id=?", (item["profile_id"],)).fetchone())
            with db:
                db.execute("UPDATE metric_run_items SET status='running',message='HTTP 检查店铺并取数' WHERE run_id=? AND profile_id=? AND requested_date=?", (run_id, item["profile_id"], item["requested_date"]))
            try:
                from .collection_accounts import require_available
                require_available(db, profile["profile_id"], run["kind"])
                if not profile[run["kind"] + "_enabled"] or not profile["shop_name"]: raise ContractError("店铺已排除或采集映射失效")
                if profile["profile_id"] in blocked: raise blocked[profile["profile_id"]]
                from .metric_auth import with_login_recovery
                result = await with_login_recovery(db, profile, lambda: fetch_metrics(profile, run["kind"], None if run["kind"] == "score" else date.fromisoformat(item["requested_date"])))
                from .metric_auth import record_auth
                record_auth(db, profile, "valid", "HTTP 登录有效", identity=result["identity"])
                if db.execute("SELECT status FROM metric_runs WHERE id=?", (run_id,)).fetchone()[0] != "running": return
                request_id = "webapi-" + hashlib.sha256(f"{run_id}:{profile['profile_id']}:{item['requested_date']}".encode()).hexdigest()[:40]
                rows = result["records"]
                require_available(db, profile["profile_id"], run["kind"])
                count = await import_records(rows, request_id)
                digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                with db:
                    db.execute("""UPDATE metric_run_items SET status='success',message=?,error_code='',report_date=?,record_count=?,source_metric=?,
                        import_request_id=?,payload_sha256=?,collected_at=?,finished_at=? WHERE run_id=? AND profile_id=? AND requested_date=?""",
                        (f"已入库 {count} 项", result["report_date"], count, result["source_metric"], request_id, digest, now(), now(), run_id, profile["profile_id"], item["requested_date"]))
                from .collection_events import recover_run
                recover_run(db, profile["profile_id"], run["kind"])
            except AccountUnavailable as exc:
                with db:
                    db.execute("UPDATE metric_run_items SET status='skipped',message=?,error_code=?,finished_at=? WHERE run_id=? AND profile_id=? AND requested_date=?", (str(exc), exc.code, now(), run_id, profile["profile_id"], item["requested_date"]))
            except NoMetricData as exc:
                with db:
                    db.execute("UPDATE metric_run_items SET status='no_data',message=?,error_code=?,finished_at=? WHERE run_id=? AND profile_id=? AND requested_date=?", (str(exc), exc.code, now(), run_id, profile["profile_id"], item["requested_date"]))
            except Exception as exc:
                message = str(exc) if isinstance(exc, ReviewError) else f"采集运行失败（{type(exc).__name__}），请查看配置与平台状态"
                code = exc.code if isinstance(exc, ReviewError) else "INTERNAL_ERROR"
                human = isinstance(exc, HumanRequired)
                if human or code in ("LOGIN_FAILED", "LOGIN_TIMEOUT"):
                    blocked[profile["profile_id"]] = exc
                    from .metric_auth import record_auth
                    record_auth(db, profile, "auth_required" if isinstance(exc, AuthRequired) else "needs_human" if human else "error", message, code)
                    from .collection_events import link_run
                    link_run(db, dedupe_key="auth:" + profile["profile_id"], run_id=run_id, task_kind=run["kind"])
                with db:
                    db.execute("UPDATE metric_run_items SET status=?,message=?,error_code=?,finished_at=? WHERE run_id=? AND profile_id=? AND requested_date=?",
                        ("needs_human" if human else "failed", message, code, now(), run_id, profile["profile_id"], item["requested_date"]))
                if not human and code not in ("LOGIN_FAILED", "LOGIN_TIMEOUT"):
                    from .collection_events import record
                    event_id = record(db, dedupe_key=f"run:{profile['profile_id']}:{run['kind']}:{code}", source="run",
                           category="run_failed", severity="danger", message=message,
                           profile_id=profile["profile_id"], task_kind=run["kind"], run_id=run_id)
                    queue_alert(db, f"run:{run_id}:{profile['profile_id']}:{code}", profile["profile_id"], code,
                        f"客服数据采集 · {'接待量' if run['kind']=='reception' else '店铺体验分'} · {PLATFORMS[profile['platform']]['name']} · {profile['expected_shop_name']}\n{item['requested_date']}：{message}\n成功记录已保留，请处理后重试未完成部分。",
                        event_id=event_id)
        states = db.execute("SELECT status,record_count FROM metric_run_items WHERE run_id=?", (run_id,)).fetchall()
        good = sum(s["status"] in ("success", "no_data") for s in states)
        skipped = sum(s["status"] == "skipped" for s in states)
        status = ("success" if good else "cancelled") if good + skipped == len(states) else "partial" if good else "needs_human" if any(s["status"] == "needs_human" for s in states) else "failed"
        with db:
            db.execute("UPDATE metric_runs SET status=?,message=?,collected_count=?,finished_at=?,heartbeat_at=? WHERE id=? AND status='running'",
                (status, f"{good}/{len(states)} 个店铺日期完成" + (f"；{skipped} 项因店铺停用或排除而跳过" if skipped else ""), sum(s["record_count"] for s in states), now(), now(), run_id))
        if status == "success":
            from .collection_events import recover_run
            for item in db.execute("SELECT DISTINCT profile_id FROM metric_run_items WHERE run_id=? AND message LIKE '复用已成功入库%'", (run_id,)).fetchall():
                recover_run(db, item["profile_id"], run["kind"])
    except Exception as exc:
        with db:
            db.execute("UPDATE metric_runs SET status='failed',message=?,finished_at=? WHERE id=? AND status='running'",
                (str(exc) if isinstance(exc, ReviewError) else "任务启动失败，请检查运行环境", now(), run_id))


def next_schedule(settings, base, advance=False):
    hour, minute = map(int, settings["run_at"].split(":"))
    candidate = base.astimezone(CN).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if advance or candidate <= base: candidate += timedelta(days=settings["frequency_days"])
    return candidate.astimezone(timezone.utc).isoformat(timespec="seconds")


def schedule_due(db, current=None):
    current = current or datetime.now(timezone.utc)
    for settings in db.execute("SELECT * FROM metric_collection_settings WHERE enabled=1").fetchall():
        if not settings["next_run_at"]:
            with db: db.execute("UPDATE metric_collection_settings SET next_run_at=? WHERE kind=?", (next_schedule(settings, current), settings["kind"]))
            continue
        if datetime.fromisoformat(settings["next_run_at"]) > current: continue
        if db.execute("SELECT 1 FROM metric_runs WHERE kind=? AND status IN('queued','running')", (settings["kind"],)).fetchone(): continue
        # 接待量同一轮计划只重试一次旧任务；持续失败仍保留原检查点，不能阻塞本期。
        unfinished = db.execute("""SELECT id FROM metric_runs WHERE kind=? AND trigger_type='scheduled'
            AND status IN('failed','partial','needs_human')
            AND (kind<>'reception' OR finished_at IS NULL OR julianday(finished_at)<julianday(?))
            ORDER BY created_at LIMIT 1""", (settings["kind"], settings["next_run_at"])).fetchone()
        if unfinished:
            # 原任务日期范围不变；接待量本期仍到期，旧任务结束后继续创建本期任务。
            enqueue(db, {"kind": settings["kind"], "action": "retry", "runId": unfinished[0]})
            if settings["kind"] != "reception":
                with db:
                    db.execute("UPDATE metric_collection_settings SET next_run_at=? WHERE kind=?", (next_schedule(settings, current, True), settings["kind"]))
            continue
        body = {"kind": settings["kind"], "trigger_type": "scheduled"}
        covered = False
        if settings["kind"] == "reception":
            last = current.astimezone(CN).date() - timedelta(days=1)
            first = lookback_first = last - timedelta(days=settings["lookback_days"] - 1)
            # 跨次定时任务覆盖缺口；单次上限 31 天，超出时显式提醒，不能悄悄截断。
            previous = db.execute("SELECT MAX(end_date) FROM metric_runs WHERE kind='reception' AND trigger_type='scheduled' AND status='success'").fetchone()[0]
            if previous: first = min(first, date.fromisoformat(previous) + timedelta(days=1))
            attempted = db.execute("""SELECT start_date,end_date FROM metric_runs
                WHERE kind='reception' AND trigger_type='scheduled' AND status IN('success','failed','partial','needs_human')
                AND julianday(finished_at)>=julianday(?) ORDER BY start_date,end_date""",
                (settings["next_run_at"],)).fetchall()
            # 只越过本轮已尝试的连续旧日期，保留尚未尝试的缺口及配置要求的回溯范围。
            # 失败部分仍留在原任务中，下一轮计划继续按原检查点重试。
            for tried in attempted:
                if tried["start_date"] <= first.isoformat() <= tried["end_date"]:
                    first = min(lookback_first, date.fromisoformat(tried["end_date"]) + timedelta(days=1))
            body.update({"from": first.isoformat(), "to": last.isoformat()})
            # 旧任务若已经覆盖本期，或创建任务后推进计划前曾中断，均不重复创建。
            covered = any(tried["start_date"] <= first.isoformat() and tried["end_date"] >= last.isoformat() for tried in attempted)
        try:
            if not covered:
                enqueue(db, body)
        except ReviewError as exc:
            queue_alert(db, "schedule:" + settings["kind"] + ":" + settings["next_run_at"], "", exc.code, "定时采集未启动：" + str(exc))
        with db:
            db.execute("UPDATE metric_collection_settings SET next_run_at=? WHERE kind=?", (next_schedule(settings, current, True), settings["kind"]))


@contextlib.contextmanager
def worker_lock():
    path = db_path().with_suffix(".metrics.lock"); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0: handle.write(b" "); handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try: yield
        finally:
            handle.seek(0)
            if os.name == "nt": msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(handle, fcntl.LOCK_UN)


async def worker(parent_pid):
    from .review_worker import parent_alive, watch_parent
    db = connect()
    async def heartbeat():
        while True:
            with db:
                db.execute("INSERT INTO metric_worker_state(id,pid,heartbeat_at,message) VALUES(1,?,?,'运行中') ON CONFLICT(id) DO UPDATE SET pid=excluded.pid,heartbeat_at=excluded.heartbeat_at,message=excluded.message", (os.getpid(), now()))
                db.execute("UPDATE metric_runs SET heartbeat_at=? WHERE status='running'", (now(),))
                db.execute("UPDATE review_runs SET heartbeat_at=? WHERE status='running'", (now(),))
            await asyncio.sleep(5)
    owner = asyncio.current_task()
    pulse = asyncio.create_task(heartbeat())
    monitor = asyncio.create_task(watch_parent(parent_pid, owner))
    try:
        while parent_alive(parent_pid):
            from .collection_queue import run_next
            await run_next(db, poll_auth=True)
            await flush_alerts(db)
            await asyncio.sleep(2)
    except asyncio.CancelledError:
        pass
    finally:
        pulse.cancel(); monitor.cancel()
        await asyncio.gather(pulse, monitor, return_exceptions=True)
        with db:
            db.execute("UPDATE metric_worker_state SET message='网页服务已停止' WHERE id=1 AND pid=?", (os.getpid(),))
        db.close()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args()
    if args.parent_pid <= 0: parser.error("parent PID is required")
    try:
        with worker_lock(): asyncio.run(worker(args.parent_pid))
    except OSError:
        # 重复进程取得锁失败，既不覆盖心跳也不改写在途任务。
        return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
