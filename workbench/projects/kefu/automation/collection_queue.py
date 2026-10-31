"""评论、体验分和接待量共用的跨进程串行队列。"""
from __future__ import annotations

import asyncio
import contextlib
import errno
import os
from pathlib import Path

from .review_errors import ContractError

DEFAULT_ORDER = ["score", "reviews", "reception"]


def plan_order(db):
    return [row[0] for row in db.execute("SELECT kind FROM collection_plan_order ORDER BY position")]


def save_order(db, order):
    if not isinstance(order, list) or len(order) != 3 or any(not isinstance(kind, str) for kind in order) or set(order) != set(DEFAULT_ORDER):
        raise ContractError("执行顺序必须恰好包含体验分、评论和接待量各一次")
    with db:
        db.execute("DELETE FROM collection_plan_order")
        db.executemany("INSERT INTO collection_plan_order(kind,position) VALUES(?,?)", [(kind, index) for index, kind in enumerate(order)])
    return {"plan_order": plan_order(db)}


@contextlib.contextmanager
def execution_lock(db):
    """锁的存活期覆盖整个任务，等待人工时也不允许另一类任务抢占。"""
    filename = db.execute("PRAGMA database_list").fetchone()[2]
    if not filename:
        # 内存数据库仅用于单进程测试；并发验收使用临时文件数据库。
        yield True
        return
    path = Path(filename).with_suffix(".collection.lock")
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b" "); handle.flush()
        handle.seek(0)
        acquired = False
        try:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK) and getattr(exc, "winerror", None) not in (32, 33):
                    raise
            yield acquired
        finally:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)


def next_run(db):
    return db.execute("""SELECT q.* FROM (
        SELECT id,kind,created_at FROM metric_runs WHERE status='queued'
        UNION ALL SELECT id,'reviews',created_at FROM review_runs WHERE status='queued'
        ) q JOIN collection_plan_order p ON p.kind=q.kind ORDER BY p.position,q.created_at,q.id LIMIT 1""").fetchone()


def interrupt_run(db, kind, run_id):
    from .metric_worker import now
    table = "review_runs" if kind == "reviews" else "metric_runs"
    with db:
        db.execute(f"UPDATE {table} SET status='failed',message='采集进程已中断，成功检查点已保留',finished_at=? WHERE id=? AND status='running'", (now(), run_id))
        if kind == "reviews":
            db.execute("UPDATE review_run_shops SET status='failed',message='采集进程已中断' WHERE run_id=? AND status='running'", (run_id,))
        else:
            db.execute("UPDATE metric_run_items SET status='failed',message='采集进程已中断' WHERE run_id=? AND status='running'", (run_id,))


async def run_next(db, *, poll_auth=False):
    from . import metric_worker, review_worker
    with execution_lock(db) as acquired:
        if not acquired:
            return False
        # 获得 OS 锁后仍为 running 的任务只能来自已退出的持锁进程。
        for row in db.execute("SELECT id,kind FROM metric_runs WHERE status='running' UNION ALL SELECT id,'reviews' FROM review_runs WHERE status='running'").fetchall():
            interrupt_run(db, row["kind"], row["id"])
        # 在同一把锁内统一检查三类计划，再挑选队首，避免同时到点的竞争。
        metric_worker.schedule_due(db)
        review_worker.schedule_due(db)
        queued = next_run(db)
        if queued:
            kind, run_id = queued["kind"], queued["id"]
            table = "review_runs" if kind == "reviews" else "metric_runs"
            run = db.execute(f"SELECT * FROM {table} WHERE id=? AND status='queued'", (run_id,)).fetchone()
            try:
                await (review_worker.execute_run(db, run) if kind == "reviews" else metric_worker.execute_run(db, run))
            except asyncio.CancelledError:
                interrupt_run(db, kind, run_id)
                raise
            return True
        if poll_auth:
            from .metric_auth import poll_auth_status
            await poll_auth_status(db)
        return False
