"""三类采集共用账号清单。旧评论入口只保留兼容视图，不另存账号和登录状态。"""
from __future__ import annotations

import sqlite3
import json
from .review_config import PROJECT


def initialize_accounts(db):
    # executescript 会隐式提交，因此在同一个脚本中开始事务，再逐条执行迁移。
    try:
        db.executescript("BEGIN IMMEDIATE;\n" + "\n".join(
            (PROJECT / "db" / name).read_text(encoding="utf-8") for name in ("reviews.sql", "metrics-collection.sql")))
        db.execute("CREATE TABLE IF NOT EXISTS collection_schema(version INTEGER PRIMARY KEY)")
        if not db.execute("SELECT 1 FROM collection_schema WHERE version=1").fetchone():
            if db.execute("SELECT 1 FROM review_profiles r JOIN metric_profiles m ON r.profile_id=m.profile_id WHERE m.platform<>'douyin' LIMIT 1").fetchone():
                raise ValueError("同一 profile 的平台不一致，请核对店铺配置后再合并")
            execute_schema(db, "collection-accounts.sql")
        if not db.execute("SELECT 1 FROM collection_schema WHERE version=2").fetchone():
            db.execute("CREATE TEMP TABLE collection_scope_migration(kind TEXT,profile_id TEXT)")
            db.execute("CREATE TEMP TABLE collection_scope_migration_kinds(kind TEXT)")
            if "profile_ids" in [row[1] for row in db.execute("PRAGMA table_info(metric_collection_settings)")]:
                for row in db.execute("SELECT kind,profile_ids FROM metric_collection_settings").fetchall():
                    ids = json.loads(row[1])
                    if not isinstance(ids, list) or any(not isinstance(identifier, str) for identifier in ids):
                        raise ValueError("旧采集范围无效，请核对配置")
                    if ids:
                        db.execute("INSERT INTO collection_scope_migration_kinds VALUES(?)", (row[0],))
                        db.executemany("INSERT INTO collection_scope_migration VALUES(?,?)", [(row[0], identifier) for identifier in ids])
            execute_schema(db, "collection-shop-scopes.sql")
        if not db.execute("SELECT 1 FROM collection_schema WHERE version=3").fetchone():
            execute_schema(db, "collection-availability.sql")
        if not db.execute("SELECT 1 FROM collection_schema WHERE version=4").fetchone():
            execute_schema(db, "collection-events.sql")
        if not db.execute("SELECT 1 FROM collection_schema WHERE version=5").fetchone():
            execute_schema(db, "collection-notification-links.sql")
        if not db.execute("SELECT 1 FROM collection_schema WHERE version=6").fetchone():
            execute_schema(db, "collection-plan-order.sql")
        if not db.execute("SELECT 1 FROM collection_schema WHERE version=7").fetchone():
            execute_schema(db, "collection-auth-check.sql")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return db


def execute_schema(db, name):
    statement = ""
    for line in (PROJECT / "db" / name).read_text(encoding="utf-8").splitlines(True):
        statement += line
        if sqlite3.complete_statement(statement):
            db.execute(statement)
            statement = ""


def require_available(db, profile_id, kind=None):
    from .review_errors import AccountUnavailable
    row = db.execute("SELECT * FROM metric_profiles WHERE profile_id=?", (profile_id,)).fetchone()
    if not row or row["excluded"] or row["disabled"]:
        raise AccountUnavailable("店铺已停用、关店或移除，本次采集已跳过")
    if kind and not row["collect_" + kind]:
        raise AccountUnavailable("店铺未启用此类采集，本次采集已跳过")


def set_availability(db, profile_id, disabled):
    from .review_errors import ContractError
    if not isinstance(disabled, bool) or not isinstance(profile_id, str):
        raise ContractError("店铺停用参数无效")
    with db:
        profile = db.execute("SELECT * FROM metric_profiles WHERE profile_id=?", (profile_id,)).fetchone()
        if not profile:
            raise ContractError("店铺不存在，请先同步店铺")
        if not disabled and profile["excluded"]:
            raise ContractError("账号已移除或平台信息不匹配，请核对后同步店铺")
        if not disabled and profile["shop_name"] and db.execute("SELECT 1 FROM metric_profiles WHERE platform=? AND shop_name=? AND profile_id<>? AND excluded=0 AND disabled=0", (profile["platform"], profile["shop_name"], profile_id)).fetchone():
            raise ContractError("该入库店铺已关联其他启用账号，请先核对店铺映射")
        db.execute("UPDATE metric_profiles SET disabled=?,availability_configured=1 WHERE profile_id=?", (int(disabled), profile_id))
    return {"profileId": profile_id, "disabled": disabled}


def configure_profile(db, body, shops):
    from .metric_profiles import PLATFORMS
    from .review_errors import ContractError
    profile_id = body.get("profileId")
    if not isinstance(profile_id, str) or not profile_id:
        raise ContractError("请先选择店铺")
    profile = db.execute("SELECT * FROM metric_profiles WHERE profile_id=?", (profile_id,)).fetchone()
    if not profile:
        raise ContractError("店铺不存在，请先同步店铺")
    auth_check = body.get("authCheckEnabled", bool(profile["auth_check_enabled"]))
    if not isinstance(auth_check, bool):
        raise ContractError("自动检查登录状态必须为开启或关闭")
    name = body.get("shopName", profile["shop_name"])
    expected = body.get("expectedShopName", profile["expected_shop_name"])
    if not isinstance(name, str) or not isinstance(expected, str) or not expected or len(expected) > 100:
        raise ContractError("店铺名称无效")
    scope = body.get("scope", {kind: bool(profile["collect_" + kind]) for kind in ("reviews", "reception", "score")})
    if not isinstance(scope, dict) or any(not isinstance(scope.get(kind), bool) for kind in ("reviews", "reception", "score")):
        raise ContractError("请分别指定评论、接待量和体验分的采集范围")
    matches = [shop for shop in shops if shop.get("platform") == PLATFORMS[profile["platform"]]["name"] and shop.get("name") == name]
    if name and len(matches) != 1:
        raise ContractError("请从该平台有效范围选择精确入库店铺")
    spec = matches[0] if matches else {}
    supported = {"reviews": bool(profile["review_enabled"]), "reception": bool(spec.get("reception")), "score": bool(spec.get("score"))}
    # 旧映射入口仅调整映射，自动保留仍受支持的采集项。
    if "scope" not in body:
        scope = {kind: enabled and supported[kind] for kind, enabled in scope.items()}
    if any(scope[kind] and not supported[kind] for kind in supported):
        raise ContractError("所选入库店铺或平台不支持该采集类型")
    identity_changed = name != profile["shop_name"] or expected != profile["expected_shop_name"]
    with db:
        if identity_changed and db.execute("SELECT 1 FROM metric_runs WHERE status IN('queued','running') UNION ALL SELECT 1 FROM review_runs WHERE status IN('queued','running') LIMIT 1").fetchone():
            raise ContractError("采集任务进行中，请结束后再修改店铺映射")
        if name and db.execute("SELECT 1 FROM metric_profiles WHERE platform=? AND shop_name=? AND excluded=0 AND disabled=0 AND profile_id<>?", (profile["platform"], name, profile_id)).fetchone():
            raise ContractError("该店铺已关联另一个启用账号，请核对映射")
        db.execute("""UPDATE metric_profiles SET shop_name=?,expected_shop_name=?,score_enabled=?,reception_enabled=?,
            collect_reviews=?,collect_reception=?,collect_score=?,auth_check_enabled=? WHERE profile_id=?""",
            (name, expected, int(supported["score"]), int(supported["reception"]), int(scope["reviews"]), int(scope["reception"]), int(scope["score"]), int(auth_check), profile_id))
        if identity_changed:
            db.execute("DELETE FROM metric_auth_status WHERE profile_id=?", (profile_id,))
    return {"profile": dict(db.execute("SELECT * FROM metric_profiles WHERE profile_id=?", (profile_id,)).fetchone())}


SCOPE_KINDS = ("reviews", "reception", "score")
# 范围键用 reviews，能力列沿用建表时的单数命名。
SCOPE_CAPABILITY = {"reviews": "review_enabled", "reception": "reception_enabled", "score": "score_enabled"}


def batch_configure(db, body, shops):
    """批量设置采集范围：一次事务内按店铺保留未指定的类别，不支持的类别跳过。"""
    from .metric_profiles import PLATFORMS
    from .review_errors import ContractError
    identifiers = body.get("profileIds")
    if not isinstance(identifiers, list) or not identifiers or len(identifiers) > 100 \
            or any(not isinstance(identifier, str) or not identifier or len(identifier) > 100 for identifier in identifiers):
        raise ContractError("请先选择要批量设置的店铺")
    scope = body.get("scope")
    if not isinstance(scope, dict):
        raise ContractError("请分别指定评论、接待量和体验分的采集范围")
    choices = {kind: scope.get(kind, "keep") for kind in SCOPE_KINDS}
    if any(value not in ("on", "off", "keep") for value in choices.values()):
        raise ContractError("采集范围只能设置为开启、关闭或不修改")
    if all(value == "keep" for value in choices.values()):
        raise ContractError("请至少设置一类采集范围")
    if db.execute("SELECT 1 FROM metric_runs WHERE status IN('queued','running') UNION ALL SELECT 1 FROM review_runs WHERE status IN('queued','running') LIMIT 1").fetchone():
        raise ContractError("采集任务进行中，请结束后再修改采集范围")
    updated, skipped = 0, 0
    with db:
        for profile_id in dict.fromkeys(identifiers):
            profile = db.execute("SELECT * FROM metric_profiles WHERE profile_id=?", (profile_id,)).fetchone()
            if not profile:
                raise ContractError("店铺不存在，请先同步店铺")
            if profile["excluded"]:
                raise ContractError(f"{profile['expected_shop_name'] or profile['profile_name']} 账号不可用，请先核对身份后再设置")
            values = []
            for kind in SCOPE_KINDS:
                current = bool(profile["collect_" + kind])
                supported = bool(profile[SCOPE_CAPABILITY[kind]])
                choice = choices[kind]
                if choice == "keep":
                    values.append(int(current))
                elif choice == "off":
                    values.append(0)
                elif supported:
                    values.append(1)
                else:
                    values.append(0)
                    skipped += 1
            if values != [int(profile["collect_" + kind]) for kind in SCOPE_KINDS]:
                db.execute("UPDATE metric_profiles SET collect_reviews=?,collect_reception=?,collect_score=? WHERE profile_id=?",
                           (*values, profile_id))
                updated += 1
    return {"updated": updated, "skipped": skipped, "total": len(set(identifiers))}
