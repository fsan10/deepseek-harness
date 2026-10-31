"""客服差评采集持久队列与定时任务。跟随网页服务进程存活，跨进程互斥。"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import errno
import io
import json
import logging
import os
import sqlite3
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

from .douyin_reviews import CN, ROOT, ContractError, HumanRequired, collect_shop, list_profiles
from .review_errors import AccountUnavailable

PROJECT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("KEFU_DB_PATH", str(PROJECT / "data" / "kefu.sqlite"))).resolve()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    from .collection_accounts import initialize_accounts
    initialize_accounts(db)
    return db


def sync_profiles(db: sqlite3.Connection, profiles: list[dict]) -> None:
    """旧评论 CLI 的薄适配；使用共用同步逻辑，保留其他平台及明确入库映射。"""
    from .collection_accounts import initialize_accounts
    from .metric_profiles import sync_profiles as sync_accounts
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='collection_schema'").fetchone():
        initialize_accounts(db)
    existing = [dict(p) for p in db.execute("SELECT * FROM metric_profiles WHERE platform<>'douyin'")]
    normalized = [{**p, "platform": "douyin", "expected_shop_name": p.get("shop_name", "")} for p in profiles]
    sync_accounts(db, existing + normalized, [], preserve_mapping=True)


def save_reviews(db: sqlite3.Connection, run_id: str, rows: list[dict]) -> None:
    columns = ["profile_id", "company", "shop_name", "comment_id", "order_id", "shop_order_id", "reviewed_at", "review_date",
               "review_level", "content", "product_id", "product_name", "sku_id", "sku_name", "product_code", "code_source",
               "enrichment_status", "keywords", "source_status", "collected_at", "run_id"]
    update = ",".join(f"{c}=excluded.{c}" for c in columns if c not in ("profile_id", "comment_id"))
    sql = f"INSERT INTO negative_reviews ({','.join(columns)}) VALUES ({','.join(':'+c for c in columns)}) ON CONFLICT(profile_id,comment_id) DO UPDATE SET {update}"
    db.executemany(sql, [{**row, "collected_at": now(), "run_id": run_id} for row in rows])


async def execute_run(db: sqlite3.Connection, run: sqlite3.Row) -> None:
    run_id = run["id"]
    with db:
        db.execute("UPDATE review_runs SET status='running',started_at=COALESCE(started_at,?),heartbeat_at=?,message='正在读取已同步店铺' WHERE id=?", (now(), now(), run_id))
    try:
        # 店铺清单由显式同步/登录维护；纯 HTTP 采集不依赖 Cloak 或浏览器在线。
        profiles = [dict(row) for row in db.execute("SELECT * FROM review_profiles ORDER BY profile_name").fetchall()]
        wanted = json.loads(run["profile_ids"])
        available = {p["profile_id"]: p for p in profiles if not p["excluded"]}
        known = {p["profile_id"]: p for p in profiles}
        if wanted and any(p not in known for p in wanted):
            raise ContractError("指定的 profile 已被移除或关店，请重新选择")
        chosen = [known[p] for p in wanted] if wanted else list(available.values())
        if not chosen:
            raise ContractError("没有已同步的抖音店铺，请先同步店铺并登录")
        with db:
            if not wanted:
                db.execute("UPDATE review_runs SET profile_ids=? WHERE id=?", (json.dumps([p["profile_id"] for p in chosen]), run_id))
            for p in chosen:
                db.execute("INSERT OR IGNORE INTO review_run_shops(run_id,profile_id,shop_name) VALUES (?,?,?)", (run_id, p["profile_id"], p["shop_name"] or p["profile_name"]))
        for profile in chosen:
            status = db.execute("SELECT status FROM review_run_shops WHERE run_id=? AND profile_id=?", (run_id, profile["profile_id"])).fetchone()[0]
            if status in ("success", "no_data", "skipped"):
                continue
            def progress(message: str):
                from .collection_accounts import require_available
                require_available(db, profile["profile_id"], "reviews")
                with db:
                    db.execute("UPDATE review_runs SET message=?,heartbeat_at=? WHERE id=?", (message, now(), run_id))
            with db:
                db.execute("UPDATE review_run_shops SET status='running',message='采集中' WHERE run_id=? AND profile_id=?", (run_id, profile["profile_id"]))
            try:
                from .collection_accounts import require_available
                require_available(db, profile["profile_id"], "reviews")
                from .metric_auth import with_login_recovery
                rows = await with_login_recovery(db, profile, lambda: collect_shop(profile, date.fromisoformat(run["start_date"]), date.fromisoformat(run["end_date"]), progress))
                require_available(db, profile["profile_id"], "reviews")
                missing = sum(not row["product_code"] for row in rows)
                status = "success" if rows else "no_data"
                message = f"已采集 {len(rows)} 条" + (f"，{missing} 条编码未设置或无法匹配" if missing else "") if rows else "中评、差评均为 0，已跳过"
                with db:
                    save_reviews(db, run_id, rows)
                    db.execute("UPDATE review_run_shops SET shop_name=?,status=?,message=?,collected_count=?,missing_code_count=?,finished_at=? WHERE run_id=? AND profile_id=?",
                               (profile["shop_name"], status, message, len(rows), missing, now(), run_id, profile["profile_id"]))
                    db.execute("UPDATE review_profiles SET shop_name=? WHERE profile_id=?", (profile["shop_name"], profile["profile_id"]))
                from .collection_events import recover_run
                recover_run(db, profile["profile_id"], "reviews")
            except AccountUnavailable as exc:
                with db:
                    db.execute("UPDATE review_run_shops SET status='skipped',message=?,finished_at=? WHERE run_id=? AND profile_id=?", (str(exc), now(), run_id, profile["profile_id"]))
            except Exception as exc:
                human = isinstance(exc, HumanRequired)
                message = str(exc) if isinstance(exc, (HumanRequired, ContractError)) else f"采集失败（{type(exc).__name__}），请检查平台状态后重试"
                with db:
                    db.execute("UPDATE review_run_shops SET status=?,message=?,finished_at=? WHERE run_id=? AND profile_id=?", ("needs_human" if human else "failed", message, now(), run_id, profile["profile_id"]))
                from .collection_events import link_run, record
                from .review_errors import AuthRequired
                code = getattr(exc, "code", "") or "REVIEW_ERROR"
                if human or code in ("LOGIN_FAILED", "LOGIN_TIMEOUT"):
                    # 会话回调可能已写入服务事件；此处只补关联任务，不重复累加。
                    if not link_run(db, dedupe_key="auth:" + profile["profile_id"], run_id=run_id, task_kind="reviews"):
                        record(db, dedupe_key="auth:" + profile["profile_id"], source="run",
                               category="auth_required" if isinstance(exc, AuthRequired) else "needs_human" if human else "check_error",
                               severity="danger" if isinstance(exc, AuthRequired) else "warning",
                               message=message, profile_id=profile["profile_id"], task_kind="reviews", run_id=run_id)
                else:
                    record(db, dedupe_key=f"run:{profile['profile_id']}:reviews:{code}", source="run",
                           category="run_failed", severity="danger", message=message,
                           profile_id=profile["profile_id"], task_kind="reviews", run_id=run_id)
        states = db.execute("SELECT status,collected_count FROM review_run_shops WHERE run_id=?", (run_id,)).fetchall()
        bad = [s for s in states if s["status"] not in ("success", "no_data", "skipped")]
        skipped = sum(s["status"] == "skipped" for s in states)
        count = sum(s["collected_count"] for s in states)
        status = ("cancelled" if skipped == len(states) else "success") if not bad else "partial" if len(bad) + skipped < len(states) else "needs_human" if any(s["status"] == "needs_human" for s in bad) else "failed"
        message = f"{len(states) - len(bad) - skipped}/{len(states)} 家店铺完成，共 {count} 条中差评" + (f"；{skipped} 家因店铺停用或排除而跳过" if skipped else "") + ("；可重试未完成店铺" if bad else "")
        with db:
            db.execute("UPDATE review_runs SET status=?,message=?,collected_count=?,finished_at=?,heartbeat_at=? WHERE id=?", (status, message, count, now(), now(), run_id))
    except Exception as exc:
        message = str(exc) if isinstance(exc, ContractError) else f"任务启动失败（{type(exc).__name__}），请检查采集运行环境"
        with db:
            db.execute("UPDATE review_runs SET status='failed',message=?,finished_at=? WHERE id=?", (message, now(), run_id))


def next_schedule(settings, base: datetime, *, advance: bool = False) -> str:
    hour, minute = map(int, settings["run_at"].split(":"))
    candidate = base.astimezone(CN).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if advance or candidate <= base:
        candidate += timedelta(days=int(settings["frequency_days"]))
    return candidate.astimezone(timezone.utc).isoformat(timespec="seconds")


def schedule_due(db: sqlite3.Connection, current: datetime | None = None):
    current = current or datetime.now(timezone.utc)
    settings = db.execute("SELECT * FROM review_settings WHERE id=1").fetchone()
    if not settings["enabled"]:
        return
    if not settings["next_run_at"]:
        with db:
            db.execute("UPDATE review_settings SET next_run_at=? WHERE id=1", (next_schedule(settings, current),))
        return
    if datetime.fromisoformat(settings["next_run_at"]) > current:
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        if db.execute("SELECT id FROM review_runs WHERE status IN ('queued','running')").fetchone():
            db.rollback(); return
        end = current.astimezone(CN).date() - timedelta(days=1)
        # 间隔大于回溯天数时，从上次完整定时采集继续补齐，防止中间日期漏采。
        start = end - timedelta(days=int(settings["lookback_days"]) - 1)
        last = db.execute("SELECT end_date FROM review_runs WHERE trigger_type='scheduled' AND status='success' ORDER BY end_date DESC LIMIT 1").fetchone()
        if last:
            start = min(start, date.fromisoformat(last[0]) + timedelta(days=1))
        unfinished = db.execute("SELECT MIN(start_date) FROM review_runs WHERE trigger_type='scheduled' AND status IN ('failed','partial','needs_human') AND end_date>?", (last[0] if last else "",)).fetchone()[0]
        if unfinished:
            start = min(start, date.fromisoformat(unfinished))
        db.execute("INSERT INTO review_runs(id,trigger_type,start_date,end_date,created_at) VALUES (?,'scheduled',?,?,?)", (str(uuid.uuid4()), start.isoformat(), end.isoformat(), now()))
        db.execute("UPDATE review_settings SET next_run_at=? WHERE id=1", (next_schedule(settings, current, advance=True),))
        db.commit()
    except Exception:
        db.rollback(); raise


def parent_alive(pid: int) -> bool:
    if not pid:
        return True
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
        kernel.CloseHandle(ctypes.c_void_p(handle))
        return code.value == 259
    try:
        os.kill(pid, 0); return True
    except OSError:
        return False


@contextlib.contextmanager
def worker_lock():
    lock_path = DB_PATH.with_suffix(".reviews.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if lock_path.stat().st_size == 0:
            handle.write(b" "); handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


async def watch_parent(parent_pid: int, owner: asyncio.Task, *, poll_interval: float = 1.0):
    """网页服务退出时，及时取消正在采集或等待人工的任务。"""
    while parent_alive(parent_pid):
        await asyncio.sleep(poll_interval)
    owner.cancel()


class BrowserLockBusy(RuntimeError):
    """已确认操作系统互斥锁正在被其他任务占用。"""


def report_lock_path(config: dict, *, project_root: Path, default_destination: Path) -> Path:
    """按报表总控同一套配置规则定位互斥锁，不按客服项目目录猜测。"""
    destination = Path(config.get("destination") or default_destination).expanduser()
    if not destination.is_absolute():
        destination = project_root / destination
    directory = Path(config.get("log_directory") or destination / ".automation_logs" / "all_platform_downloads").expanduser()
    if not directory.is_absolute():
        directory = project_root / directory
    return directory.resolve() / "controller.lock"


def create_browser_lock(run_id: str, logger: logging.Logger):
    from .douyin_reviews import prepare_shared_imports
    prepare_shared_imports()
    from scripts.auto_download.run_all_platform_downloads import ControllerRunLock, DEFAULT_CONFIG, DEFAULT_DEST, load_config

    class ReviewBrowserLock(ControllerRunLock):
        contended = False

        def _try_lock(self):
            self.contended = False
            try:
                super()._try_lock()
            except OSError as exc:
                self.contended = exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} or getattr(exc, "winerror", None) in {32, 33}
                raise

    config = load_config(DEFAULT_CONFIG)
    return ReviewBrowserLock(
        path=report_lock_path(config, project_root=ROOT, default_destination=DEFAULT_DEST),
        wait_seconds=0, run_id=run_id, execution_lane="kefu_reviews", logger=logger,
    )


@contextlib.contextmanager
def browser_lock_scope(lock):
    """acquire 中途失败也释放已取得的锁；只将真实竞争标记为等待。"""
    try:
        try:
            lock.acquire()
        except Exception as exc:
            if getattr(lock, "contended", False) and not lock.acquired:
                raise BrowserLockBusy("其他浏览器任务正在使用互斥锁") from exc
            raise
        yield
    finally:
        lock.release()


async def execute_with_browser_lock(db: sqlite3.Connection, run: sqlite3.Row, logger: logging.Logger):
    try:
        with browser_lock_scope(create_browser_lock(run["id"], logger)):
            await execute_run(db, run)
    except BrowserLockBusy:
        with db:
            db.execute("UPDATE review_runs SET message='等待其他浏览器任务释放互斥锁' WHERE id=?", (run["id"],))
    except Exception as exc:
        message = ("采集运行环境缺少北京时间数据（tzdata），请运行 scripts\\setup-reviews.ps1。"
                   if isinstance(exc, ZoneInfoNotFoundError)
                   else f"浏览器互斥锁初始化失败（{type(exc).__name__}），请检查锁文件访问权限或采集运行环境。")
        with db:
            db.execute("UPDATE review_runs SET status='failed',message=?,finished_at=? WHERE id=?", (message, now(), run["id"]))
        logger.error("差评任务互斥锁异常：run_id=%s error_type=%s", run["id"], type(exc).__name__)


async def worker(parent_pid: int):
    db = connect()
    logger = logging.getLogger("kefu.reviews"); logger.addHandler(logging.NullHandler())

    async def heartbeat():
        while True:
            with db:
                db.execute("INSERT INTO review_worker_state(id,pid,heartbeat_at,message) VALUES (1,?,?,'运行中') ON CONFLICT(id) DO UPDATE SET pid=excluded.pid,heartbeat_at=excluded.heartbeat_at,message=excluded.message", (os.getpid(), now()))
                db.execute("UPDATE review_runs SET heartbeat_at=? WHERE status='running'", (now(),))
                db.execute("UPDATE metric_runs SET heartbeat_at=? WHERE status='running'", (now(),))
            await asyncio.sleep(5)

    pulse = asyncio.create_task(heartbeat())
    owner = asyncio.current_task()
    monitor = asyncio.create_task(watch_parent(parent_pid, owner)) if parent_pid else None
    try:
        while parent_alive(parent_pid):
            from .collection_queue import run_next
            await run_next(db)
            await asyncio.sleep(3)
    except asyncio.CancelledError:
        pass  # run_next 只取消本进程实际持有的任务，不影响另一进程。
    finally:
        pulse.cancel()
        if monitor:
            monitor.cancel()
        await asyncio.gather(*([pulse, monitor] if monitor else [pulse]), return_exceptions=True)
        with db:
            db.execute("UPDATE review_worker_state SET message='网页服务已停止' WHERE id=1")
        db.close()


def export_xlsx():
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    columns = [("shop_name", "店铺"), ("company", "公司"), ("reviewed_at", "评价时间"), ("review_level", "评价等级"),
               ("order_id", "订单号"), ("content", "评价详情"), ("product_id", "产品ID"), ("product_name", "商品名称"),
               ("product_code", "商品编码"), ("sku_id", "规格ID"), ("sku_name", "商品规格"), ("keywords", "关键词"),
               ("code_source", "编码来源"), ("enrichment_status", "编码状态")]
    rows = json.load(sys.stdin)
    wb = Workbook(); ws = wb.active; ws.title = "差评汇总分析"
    ws.append([label for _, label in columns])
    for row in rows:
        ws.append([str(row.get(key) or "") for key, _ in columns])
        for cell in ws[ws.max_row]:
            # 所有ID与用户评价作为文本写入，保留19位编号并防止Excel公式注入。
            cell.data_type = "s"; cell.number_format = "@"
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4F46E5")
    widths = [26, 34, 22, 12, 25, 68, 25, 55, 24, 24, 40, 28, 22, 18]
    for i, width in enumerate(widths, 1):
        from openpyxl.utils import get_column_letter
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"; ws.auto_filter.ref = ws.dimensions
    output = io.BytesIO(); wb.save(output); sys.stdout.buffer.write(output.getvalue())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-pid", type=int, default=0)
    parser.add_argument("--sync-profiles", action="store_true")
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()
    if args.export:
        export_xlsx(); return
    if args.sync_profiles:
        profiles = list_profiles(); db = connect(); sync_profiles(db, profiles); db.close()
        print(json.dumps({"profiles": profiles}, ensure_ascii=False)); return
    try:
        with worker_lock():
            asyncio.run(worker(args.parent_pid))
    except OSError:
        # 另一个网页进程已拥有采集队列。
        return


if __name__ == "__main__":
    main()
