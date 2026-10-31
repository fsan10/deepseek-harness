"""评论 HTTP 适配；账号、认证状态、显式登录及会话存储统一由采集账号核心管理。"""
from __future__ import annotations

from .review_errors import AuthRequired, ReviewError
from .review_http import DirectHttpSession
from .review_session_store import SessionStore


def record_state(profile_id: str, state: str, message: str, code: str = "", shop: str = "", *, captured_at=None, db=None):
    from .review_worker import connect
    from .metric_auth import record_auth
    own = db is None
    db = db or connect()
    try:
        profile = db.execute("SELECT * FROM metric_profiles WHERE profile_id=?", (profile_id,)).fetchone()
        if profile:
            record_auth(db, dict(profile), state, message, code, identity={"shop_name": shop}, captured_at=captured_at)
    finally:
        if own: db.close()


def client_for_profile(profile: dict, *, store=None, db=None):
    store = store or SessionStore()
    def notify(state, message, code="", shop=""):
        record_state(profile["profile_id"], state, message, code, shop, db=db)
    try:
        credentials = store.load(profile["profile_id"])
    except ReviewError as exc:
        notify("auth_required" if isinstance(exc, AuthRequired) else "error", str(exc), exc.code)
        raise
    return DirectHttpSession(profile, credentials, store=store, on_state=notify)


async def check_profile(profile: dict, *, store=None, db=None):
    from .review_worker import connect
    from .metric_auth import check_profile as check_account
    own = db is None
    target = db or connect()
    try:
        canonical = dict(target.execute("SELECT * FROM metric_profiles WHERE profile_id=?", (profile["profile_id"],)).fetchone())
        return await check_account(target, canonical, store=store)
    finally:
        if own: target.close()


async def poll_auth_status(db):
    # 仅保留旧调用兼容；后台只由共用账号 worker 调用一次。
    from .metric_auth import poll_auth_status as poll_accounts
    await poll_accounts(db)


async def login_profile(profile: dict, *, store=None, db=None) -> dict:
    from .review_worker import connect
    from .metric_auth import login_profile as login_account
    from .collection_accounts import require_available
    own = db is None
    target = db or connect()
    try:
        require_available(target, profile["profile_id"])
        canonical = dict(target.execute("SELECT * FROM metric_profiles WHERE profile_id=?", (profile["profile_id"],)).fetchone())
        result = await login_account(target, canonical, store=store)
        return {**result, "browser_used_for": "login_only"}
    finally:
        if own: target.close()
