"""Bounded, read-only merchant probe using fresh local request signatures."""
import argparse
import asyncio
import json

from commerce_api.core.contracts import Profile
from commerce_api.core.errors import CommerceError
from commerce_api.core.registry import Registry
from commerce_api.platforms.douyin.backends.merchant.client import Client
from commerce_api.platforms.douyin.backends.merchant.api.reports.orders import HISTORY
from commerce_api.runtime.sessions import SessionStore, session_key
from commerce_api.runtime.storage import Paths, read_json


async def run(name):
    paths = Paths()
    profile = Profile(**read_json(paths.file("config", "profiles"), {})[name])
    store = SessionStore(paths)
    credential = store.load(session_key(profile.id, "douyin", "merchant"))
    client = Client(Registry().backend("douyin", "merchant"), credential, profile, store=store)
    try:
        identity = await client.identity()
        body = await client.get(HISTORY, {"page": 1, "size": 10})
        data = body.get("data") or {}
        print(json.dumps({"transport": "direct_http", "fresh_local_signature": True,
            "identity_verified": bool(identity), "code": body.get("code"),
            "history_total": body.get("total"), "page_rows": len(data.get("task_list") or [])}))
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    try:
        asyncio.run(run(args.profile))
    except CommerceError as exc:
        print(json.dumps({"ok": False, "error": exc.public()}, ensure_ascii=False))
        return 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
