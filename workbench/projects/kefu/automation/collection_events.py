"""异常事件的唯一写入入口。

服务登录检查与采集任务都写这一张表，按 dedupe_key 合并未恢复事件：
同一店铺持续失效只保留一条待处理记录，关联期间失败的任务；恢复后标记已恢复，
再次失效才产生新事件。日志页面只读取这份数据，不重复保存多份。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _items(raw) -> list[str]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, str) and item]
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [item for item in value if isinstance(item, str) and item] if isinstance(value, list) else []


def _merge(raw, value: str, limit: int = 20) -> str:
    items = _items(raw)
    if value and value not in items:
        items.append(value)
    return json.dumps(items[-limit:], ensure_ascii=False)


def profile_info(db, profile_id: str) -> tuple[str, str]:
    """平台键与店铺名统一取账号主表，避免旧视图里平台是中文名称。"""
    if not profile_id:
        return "", ""
    row = db.execute("SELECT platform,expected_shop_name,shop_name FROM metric_profiles WHERE profile_id=?", (profile_id,)).fetchone()
    if not row:
        return "", ""
    return row["platform"] or "", row["expected_shop_name"] or row["shop_name"] or ""


def record(db, *, dedupe_key: str, category: str, message: str, source: str = "service",
           severity: str = "warning", profile_id: str = "", task_kind: str = "", run_id: str = "") -> int:
    """写入或合并一条未恢复事件；返回事件 id。"""
    if source not in ("service", "run"):
        raise ValueError("事件来源无效")
    if severity not in ("warning", "danger"):
        severity = "warning"
    platform, shop_name = profile_info(db, profile_id)
    stamp = now()
    row = db.execute("SELECT * FROM collection_events WHERE dedupe_key=? AND status='open'", (dedupe_key,)).fetchone()
    with db:
        if row:
            run_ids = _merge(row["run_ids"], run_id) if run_id else row["run_ids"]
            sources = _merge(row["sources"], source, limit=4)
            task_count = len(_items(run_ids))
            db.execute("""UPDATE collection_events SET sources=?,category=?,severity=?,platform=?,shop_name=?,task_kind=?,
                run_ids=?,task_count=?,message=?,occurrences=occurrences+1,last_seen_at=?,updated_at=?
                WHERE id=? AND status='open'""",
                (sources, category, severity, platform or row["platform"], shop_name or row["shop_name"],
                 task_kind or row["task_kind"], run_ids, task_count, message, stamp, stamp, row["id"]))
            return int(row["id"])
        run_ids = json.dumps([run_id], ensure_ascii=False) if run_id else "[]"
        try:
            cursor = db.execute("""INSERT INTO collection_events(dedupe_key,source,sources,category,severity,platform,profile_id,
                shop_name,task_kind,run_ids,task_count,message,occurrences,status,first_seen_at,last_seen_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,'open',?,?,?)""",
                (dedupe_key, source, json.dumps([source]), category, severity, platform, profile_id,
                 shop_name, task_kind, run_ids, 1 if run_id else 0, message, stamp, stamp, stamp))
            return int(cursor.lastrowid or 0)
        except sqlite3.IntegrityError:
            # 另一个 worker 刚好插入了同一条未恢复事件，改为合并到它上面。
            pass
    existing = db.execute("SELECT id,run_ids,sources,task_kind FROM collection_events WHERE dedupe_key=? AND status='open'", (dedupe_key,)).fetchone()
    if not existing:
        return 0
    with db:
        run_ids = _merge(existing["run_ids"], run_id) if run_id else existing["run_ids"]
        db.execute("""UPDATE collection_events SET sources=?,category=?,message=?,occurrences=occurrences+1,
            run_ids=?,task_count=?,last_seen_at=?,updated_at=? WHERE id=?""",
            (_merge(existing["sources"], source, 4), category, message, run_ids, len(_items(run_ids)), stamp, stamp, existing["id"]))
    return int(existing["id"])


def recover(db, *, dedupe_key: str | None = None, prefix: str | None = None) -> int:
    """把匹配的未恢复事件标记为已恢复；返回处理条数。"""
    clauses = ["status='open'"]
    bindings: list[str] = []
    if dedupe_key:
        clauses.append("dedupe_key=?")
        bindings.append(dedupe_key)
    if prefix:
        clauses.append("dedupe_key LIKE ?")
        bindings.append(prefix.replace("%", "") + "%")
    if len(clauses) == 1:
        return 0
    stamp = now()
    with db:
        cursor = db.execute(f"UPDATE collection_events SET status='recovered',recovered_at=?,updated_at=? WHERE {' AND '.join(clauses)}",
                            (stamp, stamp, *bindings))
    return int(cursor.rowcount or 0)


def recover_auth(db, profile_id: str) -> int:
    return recover(db, dedupe_key="auth:" + profile_id)


def recover_run(db, profile_id: str, task_kind: str) -> int:
    return recover(db, prefix=f"run:{profile_id}:{task_kind}:")


def link_run(db, *, dedupe_key: str, run_id: str, task_kind: str = "") -> int:
    """把失败任务挂到已存在的未恢复事件上，不重复累加发生次数。"""
    if not run_id:
        return 0
    row = db.execute("SELECT id,run_ids,task_kind FROM collection_events WHERE dedupe_key=? AND status='open'", (dedupe_key,)).fetchone()
    if not row:
        return 0
    run_ids = _merge(row["run_ids"], run_id)
    stamp = now()
    with db:
        db.execute("UPDATE collection_events SET run_ids=?,task_count=?,task_kind=?,last_seen_at=?,updated_at=? WHERE id=?",
                   (run_ids, len(_items(run_ids)), task_kind or row["task_kind"], stamp, stamp, row["id"]))
    return 1
